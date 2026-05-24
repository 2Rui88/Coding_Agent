"""Agent Loop — 核心多步执行循环 (async generator)。

对应 TypeScript 版本的 agent-loop.ts。

核心改进：用 AsyncGenerator 替代回调模式。
UI 层通过 async for 消费 AgentEvent 流，Agent 零 UI 依赖。

自愈机制：
  1. 空响应 → 注入续写提示重试（最多 2 次）
  2. pause_turn / max_tokens → thinking 截断恢复（最多 3 次）
  3. 工具错误 → 累计计数，超阈值时透出诊断信息
"""

from __future__ import annotations

from typing import AsyncGenerator

from agent.events import *
from infra.tokens.counter import compute_context_stats
from infra.types import (
    AgentStep,
    ChatMessage,
    MessageList,
    ToolContext,
)
from model.anthropic import AnthropicAdapter
from tools.definition import ToolRegistry


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _is_empty(content: str) -> bool:
    return content.strip() == ""


def _format_diagnostics(diagnostics: dict | None) -> str:
    if not diagnostics:
        return ""
    parts = []
    sr = diagnostics.get("stop_reason")
    bts = diagnostics.get("block_types", [])
    ignored = diagnostics.get("ignored_block_types", [])
    if sr:
        parts.append(f"stop_reason={sr}")
    if bts:
        parts.append(f"blocks={','.join(bts)}")
    if ignored:
        parts.append(f"ignored={','.join(ignored)}")
    return f" 诊断: {'; '.join(parts)}。" if parts else ""


def _is_recoverable_thinking(diagnostics: dict | None, is_empty: bool) -> bool:
    """判断是否可恢复的 thinking 截断情况。"""
    if not is_empty:
        return False
    if not diagnostics:
        return False
    sr = diagnostics.get("stop_reason", "")
    if sr not in ("pause_turn", "max_tokens"):
        return False
    blocks = diagnostics.get("block_types", [])
    ignored = diagnostics.get("ignored_block_types", [])
    return "thinking" in blocks or "thinking" in ignored


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

async def run_agent_turn(
    model: AnthropicAdapter,
    tools: ToolRegistry,
    messages: MessageList,
    cwd: str,
    permissions=None,
    max_steps: int = 25,
    model_name: str = "",
) -> AsyncGenerator[AgentEvent, None]:
    """执行一次 Agent Turn（用户输入到下一个回复）。

    Yields:
        AgentEvent — UI 层消费事件流
    """
    msgs: list[ChatMessage] = list(messages)
    empty_retry = 0
    thinking_retry = 0
    tool_error_count = 0
    saw_tool_result = False

    for step in range(max_steps):
        yield TurnStart(step=step)

        # 上下文统计（M2 会接入压缩 Pipeline）
        if model_name:
            stats = compute_context_stats(msgs, model_name)
            # 压缩钩子会在此处注入（M2）

        # 调用模型
        yield ModelRequest()
        response: AgentStep = await model.next(msgs)

        # ---- 处理 assistant 类型 ----
        if response.type == "assistant":
            is_empty = _is_empty(response.content)
            diag = response.diagnostics.model_dump() if response.diagnostics else None

            # 自愈 1: thinking 截断恢复
            if _is_recoverable_thinking(diag, is_empty) and thinking_retry < 3:
                thinking_retry += 1
                sr = diag.get("stop_reason", "")
                progress = (
                    "模型在 thinking 阶段触发 max_tokens，继续请求..."
                    if sr == "max_tokens"
                    else "模型返回 pause_turn，继续请求..."
                )
                yield ThinkingRecovery(stop_reason=sr, attempt=thinking_retry)
                msgs.append({"role": "assistant_progress", "content": progress})
                msgs.append({
                    "role": "user",
                    "content": (
                        "Resume immediately and continue with the next concrete "
                        "tool call, code change, or an explicit <final> answer."
                    ),
                })
                continue

            # 自愈 2: 空响应重试
            if is_empty and empty_retry < 2:
                empty_retry += 1
                yield EmptyResponseRetry(attempt=empty_retry)
                hint = (
                    "Your last response was empty after recent tool results. "
                    "Continue immediately by trying the next concrete step."
                    if saw_tool_result
                    else "Your last response was empty. Continue immediately."
                )
                msgs.append({"role": "user", "content": hint})
                continue

            # 空响应超过重试次数 → 终止
            if is_empty:
                fallback = (
                    f"工具执行后模型返回空响应。{_format_diagnostics(diag)}"
                    if saw_tool_result
                    else f"模型返回空响应。{_format_diagnostics(diag)}"
                )
                msgs.append({"role": "assistant", "content": fallback})
                yield TurnComplete(messages=msgs)
                return

            # 进度消息
            if response.kind == "progress":
                yield ModelResponse(
                    content=response.content,
                    kind="progress",
                    thinking_blocks=response.thinking_blocks,
                    diagnostics=diag,
                    usage=response.usage,
                )
                msgs.append({"role": "assistant_progress", "content": response.content})
                msgs.append({
                    "role": "user",
                    "content": "Continue from your <progress> update immediately.",
                })
                continue

            # 正常回复
            yield ModelResponse(
                content=response.content,
                kind=response.kind or "final",
                thinking_blocks=response.thinking_blocks,
                diagnostics=diag,
                usage=response.usage,
            )
            msgs.append({"role": "assistant", "content": response.content})
            yield TurnComplete(messages=msgs)
            return

        # ---- 处理 tool_calls 类型 ----
        # 先追加 thinking blocks
        if response.thinking_blocks:
            msgs.append({
                "role": "assistant_thinking",
                "blocks": response.thinking_blocks,
            })

        # 如果有文本内容且有工具调用，先追加文本
        if response.content and response.calls:
            if response.kind == "progress":
                msgs.append({"role": "assistant_progress", "content": response.content})
            else:
                msgs.append({"role": "assistant", "content": response.content})

        yield ToolCallEvent(calls=[
            {"id": c.id, "tool_name": c.tool_name, "input": c.input}
            for c in response.calls
        ])

        # 执行所有工具调用
        tool_results: list[dict] = []
        for call in response.calls:
            result = await tools.execute(
                call.tool_name,
                call.input,
                ToolContext(cwd=cwd, permissions=permissions),
            )
            saw_tool_result = True

            if not result.ok:
                tool_error_count += 1

            yield ToolResultEvent(
                call_id=call.id,
                tool_name=call.tool_name,
                output=result.output,
                is_error=not result.ok,
                await_user=result.await_user,
            )

            # 追加 tool_call + tool_result 到消息
            msgs.append({
                "role": "assistant_tool_call",
                "tool_use_id": call.id,
                "tool_name": call.tool_name,
                "input": call.input,
            })
            msgs.append({
                "role": "tool_result",
                "tool_use_id": call.id,
                "tool_name": call.tool_name,
                "content": result.output,
                "is_error": not result.ok,
            })

            # ask_user 中断回合
            if result.await_user:
                msgs.append({"role": "assistant", "content": result.output})
                yield TurnComplete(messages=msgs)
                return

        # 循环继续下一步

    # 达到最大步数
    max_step_msg = "达到最大工具步数限制。"
    msgs.append({"role": "assistant", "content": max_step_msg})
    yield MaxStepsReached(messages=msgs)
