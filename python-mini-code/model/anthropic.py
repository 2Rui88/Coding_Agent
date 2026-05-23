"""Anthropic API 适配器 — 薄封装官方 SDK。

职责：
  1. 将内部的 ChatMessage 列表转换为 Anthropic Messages API 格式
  2. 调用 API 并处理响应
  3. 解析响应为内部 AgentStep 格式
  4. 重试由 tenacity 统一管理
"""

from __future__ import annotations

import re
from typing import Any

from anthropic import AsyncAnthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import RuntimeConfig
from infra.types import (
    AgentStep,
    ChatMessage,
    ProviderUsage,
    StepDiagnostics,
    ToolCall,
)
from tools.definition import ToolRegistry


# ---------------------------------------------------------------------------
# 消息转换
# ---------------------------------------------------------------------------

def _build_snip_boundary_text() -> str:
    return (
        "[Snipped earlier conversation segment]\n\n"
        "A middle portion of the earlier conversation was removed "
        "to preserve context space. The recent conversation "
        "and active task context are preserved."
    )


def _to_assistant_text(msg: ChatMessage) -> str:
    """将 assistant / assistant_progress 消息转为 API 文本格式。"""
    if msg.role == "assistant_progress":
        return f"<progress>\n{msg.content}\n</progress>"
    return msg.content


def to_anthropic_format(
    messages: list[ChatMessage],
) -> tuple[str, list[dict[str, Any]]]:
    """将内部消息列表转换为 Anthropic Messages API 格式。

    Returns:
        (system_prompt, api_messages)
    """
    system_parts: list[str] = []
    api_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.role

        if role == "system":
            system_parts.append(msg.content)
            continue

        if role == "user":
            api_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": msg.content}],
            })
            continue

        if role in ("assistant", "assistant_progress"):
            api_messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": _to_assistant_text(msg)}],
            })
            continue

        if role == "assistant_thinking":
            for block in msg.blocks:
                api_messages.append({
                    "role": "assistant",
                    "content": [block],
                })
            continue

        if role == "assistant_tool_call":
            api_messages.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": msg.tool_use_id,
                    "name": msg.tool_name,
                    "input": msg.input,
                }],
            })
            continue

        if role == "context_summary":
            api_messages.append({
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": f"[Context Summary from earlier conversation]\n{msg.content}",
                }],
            })
            continue

        if role == "snip_boundary":
            api_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": _build_snip_boundary_text()}],
            })
            continue

        # tool_result
        api_messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": msg.tool_use_id,
                "content": msg.content,
                "is_error": msg.is_error,
            }],
        })

    return "\n\n".join(system_parts), api_messages


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def _normalize_usage(raw_usage: Any) -> ProviderUsage | None:
    """从 API 响应中提取标准化的 usage。"""
    if raw_usage is None:
        return None
    input_tokens = (
        getattr(raw_usage, "input_tokens", 0) or 0
    ) + (
        getattr(raw_usage, "cache_creation_input_tokens", 0) or 0
    ) + (
        getattr(raw_usage, "cache_read_input_tokens", 0) or 0
    )
    output_tokens = getattr(raw_usage, "output_tokens", 0) or 0
    total = input_tokens + output_tokens
    if total <= 0:
        return None
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        source="anthropic",
    )


_FINAL_PATTERN = re.compile(r"<final>(.*?)</final>", re.DOTALL | re.IGNORECASE)
_PROGRESS_PATTERN = re.compile(r"<progress>(.*?)</progress>", re.DOTALL | re.IGNORECASE)


def _parse_assistant_text(content: str) -> tuple[str, str | None]:
    """解析 <final> / <progress> 标记。"""
    content = content.strip()

    m = _FINAL_PATTERN.search(content)
    if m:
        return m.group(1).strip(), "final"

    m = _PROGRESS_PATTERN.search(content)
    if m:
        return m.group(1).strip(), "progress"

    return content, None


def parse_anthropic_response(response: Any) -> AgentStep:
    """将 Anthropic API 响应解析为内部 AgentStep。"""
    tool_calls: list[ToolCall] = []
    text_parts: list[str] = []
    thinking_blocks: list[dict[str, Any]] = []
    block_types: list[str] = []
    ignored_block_types: list[str] = []

    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", "unknown")
        block_types.append(block_type)

        if block_type == "text":
            text_parts.append(str(getattr(block, "text", "")))
        elif block_type == "tool_use":
            tool_calls.append(ToolCall(
                id=str(getattr(block, "id", "")),
                tool_name=str(getattr(block, "name", "")),
                input=getattr(block, "input", {}),
            ))
        elif block_type in ("thinking", "redacted_thinking"):
            thinking_blocks.append(dict(block))  # type: ignore
        else:
            ignored_block_types.append(block_type)

    parsed_text, kind = _parse_assistant_text("\n".join(text_parts).strip())
    diagnostics = StepDiagnostics(
        stop_reason=getattr(response, "stop_reason", None),
        block_types=block_types,
        ignored_block_types=ignored_block_types,
    )
    usage = _normalize_usage(getattr(response, "usage", None))

    if tool_calls:
        return AgentStep(
            type="tool_calls",
            content=parsed_text or "",
            calls=tool_calls,
            thinking_blocks=thinking_blocks,
            diagnostics=diagnostics,
            usage=usage,
        )

    return AgentStep(
        type="assistant",
        content=parsed_text,
        kind=kind or "final",
        thinking_blocks=thinking_blocks,
        diagnostics=diagnostics,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# 适配器
# ---------------------------------------------------------------------------

async def _call_api(
    client: AsyncAnthropic,
    model_name: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
) -> Any:
    """调用 Anthropic Messages API（含 tenacity 重试）。"""
    decorated = retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, max=8),
        retry=retry_if_exception_type(
            (Exception,)
        ),  # tenacity 会处理 429/5xx
        reraise=True,
    )(client.messages.create)

    return await decorated(
        model=model_name,
        system=system,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
    )


class AnthropicAdapter:
    """Anthropic API 适配器 — 对官方 SDK 的薄封装。"""

    def __init__(self, tools: ToolRegistry, config: RuntimeConfig):
        self.name = config.model
        self.tools = tools
        self.config = config
        self.client = AsyncAnthropic(
            api_key=config.api_key,
            auth_token=config.auth_token,
            base_url=config.base_url,
            max_retries=0,  # 由 tenacity 管理重试
        )
        self._max_tokens = config.max_output_tokens or _default_max_tokens(config.model)

    async def next(self, messages: list[ChatMessage]) -> AgentStep:
        """执行一次模型推理。

        Args:
            messages: 完整的 ChatMessage 列表

        Returns:
            解析后的 AgentStep（assistant 或 tool_calls）
        """
        system, api_messages = to_anthropic_format(messages)

        response = await _call_api(
            self.client,
            self.name,
            system,
            api_messages,
            self.tools.to_anthropic_format(),
            self._max_tokens,
        )

        return parse_anthropic_response(response)

    async def summarize(
        self, messages: list[ChatMessage], prompt: str
    ) -> str | None:
        """请求模型生成摘要（用于上下文压缩）。"""
        try:
            response = await self.client.messages.create(
                model=self.name,
                system="You are a precise assistant that summarizes conversations concisely.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            for block in response.content:
                if getattr(block, "type", "") == "text":
                    return str(getattr(block, "text", ""))
            return None
        except Exception:
            return None


def _default_max_tokens(model: str) -> int:
    """根据模型名推断默认 max_tokens（保守值）。"""
    m = model.lower()
    if "opus-4-6" in m or "sonnet-4-6" in m:
        return 64000
    if "haiku-4-5" in m or "sonnet-4" in m:
        return 64000
    if "opus-4" in m:
        return 32000
    return 32000
