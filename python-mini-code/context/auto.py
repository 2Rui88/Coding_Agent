"""AutoCompact — LLM 全文摘要压缩。

当上下文利用率达到临界值（85%）时触发。
调用 LLM 对全部历史做一次全文摘要，
摘要消息替代被压缩的旧消息。

仅在 Agent Turn 第一步触发，避免中途打断工具调用链。
连续失败 3 次后自动禁用。

对应 TypeScript 版本 compact/auto-compact.ts + compact/compact.ts。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from context.constants import (
    AUTOCOMPACT_THRESHOLD,
    MAX_COMPACTION_FAILURES,
    MAX_KEEP_TOKENS,
    MIN_EFFECTIVE_INPUT_FOR_AUTOCOMPACT,
    MIN_KEEP_MESSAGES,
    MIN_KEEP_TOKENS,
    SUMMARY_MAX_OUTPUT_TOKENS,
)
from context.strategy import CompactionResult, CompactionStrategy
from infra.tokens.counter import (
    compute_context_stats,
    estimate_tokens,
    mark_provider_usage_stale,
)
from infra.types import ChatMessage


@dataclass
class _AutoCompactState:
    consecutive_failures: int = 0
    disabled: bool = False


_state = _AutoCompactState()


def _reset_state() -> None:
    _state.consecutive_failures = 0
    _state.disabled = False


class AutoCompactStrategy(CompactionStrategy):
    """自动压缩：LLM 全文摘要。"""

    name = "auto"
    threshold = AUTOCOMPACT_THRESHOLD

    async def apply(
        self,
        messages: list[ChatMessage],
        model_name: str,
        model=None,
    ) -> CompactionResult:
        tokens_before = estimate_tokens(messages, model_name)

        if _state.disabled:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="auto",
                metadata={"reason": "disabled"},
            )

        stats = compute_context_stats(messages, model_name)
        if stats["effective_input"] < MIN_EFFECTIVE_INPUT_FOR_AUTOCOMPACT:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="auto",
                metadata={"reason": "too_small_window"},
            )

        if stats["utilization"] < self.threshold:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="auto",
                metadata={"reason": "below_threshold"},
            )

        if model is None:
            _state.consecutive_failures += 1
            return _noop(messages, tokens_before)

        try:
            result = await _compact(messages, model, model_name)
            if result is None:
                _state.consecutive_failures += 1
                if _state.consecutive_failures >= MAX_COMPACTION_FAILURES:
                    _state.disabled = True
                return _noop(messages, tokens_before)

            _state.consecutive_failures = 0
            return result
        except Exception:
            _state.consecutive_failures += 1
            if _state.consecutive_failures >= MAX_COMPACTION_FAILURES:
                _state.disabled = True
            return _noop(messages, tokens_before)


def _noop(messages: list[ChatMessage], tokens: int) -> CompactionResult:
    return CompactionResult(
        messages=messages, did_compact=False,
        tokens_before=tokens, tokens_after=tokens,
        kind="auto",
    )


# ---- 压缩核心逻辑 ----

def _find_retention_boundary(messages: list[ChatMessage]) -> int:
    """从尾部向前扫描，确定保留边界。

    保留最近的 MIN_KEEP_MESSAGES ~ MAX_KEEP_TOKENS 的消息。
    边界对齐到 API 轮次边界（tool_call + tool_result 不可拆分）。
    """
    token_sum = 0
    boundary = len(messages)

    for i in range(len(messages) - 1, 0, -1):
        msg_tokens = estimate_tokens([messages[i]], "cl100k_base")
        if token_sum + msg_tokens > MAX_KEEP_TOKENS:
            break
        token_sum += msg_tokens
        boundary = i

    # 确保至少保留 MIN_KEEP_MESSAGES
    min_boundary = max(1, len(messages) - MIN_KEEP_MESSAGES)
    boundary = min(boundary, min_boundary)

    if boundary <= 1 and len(messages) > MIN_KEEP_MESSAGES + 1:
        boundary = max(1, len(messages) - MIN_KEEP_MESSAGES)

    # 对齐到 tool_call 边界
    return _align_to_api_round(messages, boundary)


def _align_to_api_round(messages: list[ChatMessage], boundary: int) -> int:
    """确保边界不切割 tool_call + tool_result 对。"""
    start = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.role == "assistant_thinking":
            i += 1
            continue

        if msg.role == "assistant_tool_call":
            group_end = i + 1
            while group_end < len(messages) and messages[group_end].role == "assistant_tool_call":
                group_end += 1
            while group_end < len(messages) and messages[group_end].role == "tool_result":
                group_end += 1

            group_end_val = group_end - start
            if boundary > start and boundary < group_end_val:
                return start
            i = group_end
            start = i
            continue

        group_end = start + 1
        if boundary > start and boundary < group_end:
            return start
        i += 1
        start = i

    return boundary


def _messages_to_text(messages: list[ChatMessage]) -> str:
    """将消息列表转为 LLM 可读的纯文本。"""
    import json
    parts = []
    for msg in messages:
        role = msg.role
        if role == "user":
            parts.append(f"[User]: {msg.content}")
        elif role in ("assistant", "assistant_progress"):
            parts.append(f"[Assistant]: {msg.content}")
        elif role == "assistant_thinking":
            parts.append("[Assistant Thinking]: preserved reasoning block")
        elif role == "assistant_tool_call":
            parts.append(
                f"[Tool Call: {msg.tool_name}]: "
                f"{json.dumps(msg.input, ensure_ascii=False)}"
            )
        elif role == "tool_result":
            err = " ERROR" if getattr(msg, "is_error", False) else ""
            content = msg.content[:500] + ("..." if len(msg.content) > 500 else "")
            parts.append(f"[Tool Result{err}: {msg.tool_name}]: {content}")
        elif role == "context_summary":
            parts.append(f"[Previous Summary]: {msg.content}")
    return "\n\n".join(parts)


def _build_compact_prompt(conversation_text: str) -> str:
    return (
        "You are a helpful assistant that summarizes conversations concisely.\n\n"
        "Summarize the following AI coding assistant conversation. "
        "Keep it brief but preserve:\n"
        "- The user's goals and active tasks\n"
        "- Completed actions and current state\n"
        "- Important decisions, constraints, and open questions\n"
        "- Key file paths, commands run, and code changes made\n\n"
        "Produce the final summary in <summary> tags.\n\n"
        f"{conversation_text}"
    )


def _parse_summary(response_text: str) -> str | None:
    m = re.search(
        r"<summary>(.*?)</summary>",
        response_text, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


async def _compact(
    messages: list[ChatMessage],
    model,
    model_name: str,
) -> CompactionResult | None:
    """执行 LLM 全文摘要压缩。"""
    if len(messages) <= 2:
        return None

    tokens_before = estimate_tokens(messages, model_name)

    system_msgs = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]

    if len(non_system) <= MIN_KEEP_MESSAGES:
        return None

    boundary = _find_retention_boundary(messages)
    to_compress = messages[1:boundary]  # 跳过 system 消息
    to_keep = messages[boundary:]

    # 标记保留消息的 usage 为过期
    to_keep = [
        mark_provider_usage_stale(m, "conversation was compacted")
        for m in to_keep
    ]

    if not to_compress:
        return None

    conversation_text = _messages_to_text(to_compress)
    prompt = _build_compact_prompt(conversation_text)

    summary_content = await model.summarize(to_compress, prompt)
    if not summary_content:
        return None

    parsed = _parse_summary(summary_content)
    if not parsed:
        return None

    ts = int(time.time() * 1000)
    summary_msg: dict = {
        "id": f"compact-summary-{ts}",
        "role": "context_summary",
        "content": parsed,
        "compressed_count": len(to_compress),
        "timestamp": ts,
    }

    new_messages = system_msgs + [summary_msg] + to_keep
    tokens_after = estimate_tokens(new_messages, model_name)

    return CompactionResult(
        messages=new_messages, did_compact=True,
        tokens_before=tokens_before, tokens_after=tokens_after,
        kind="auto",
        metadata={
            "removed_count": len(to_compress),
            "summary_tokens": estimate_tokens([summary_msg], model_name),
        },
    )
