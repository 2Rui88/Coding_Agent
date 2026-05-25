"""Microcompact — 零 LLM 工具结果清理。

将旧的 read_file/run_command/grep_files/list_files/web_fetch
等可重现工具的输出替换为占位标记，保留最近 3 个结果。

对应 TypeScript 版本 compact/microcompact.ts。
"""

from __future__ import annotations

from context.constants import (
    CLEAR_MARKER,
    COMPACTABLE_TOOLS,
    KEEP_RECENT_TOOL_RESULTS,
    MICROCOMPACT_THRESHOLD,
)
from context.strategy import CompactionResult, CompactionStrategy
from infra.tokens.counter import compute_context_stats, estimate_tokens
from infra.types import ChatMessage


class MicrocompactStrategy(CompactionStrategy):
    """微压缩：清除旧的可重现工具结果。"""

    name = "micro"
    threshold = MICROCOMPACT_THRESHOLD

    async def apply(
        self,
        messages: list[ChatMessage],
        model_name: str,
        model=None,
    ) -> CompactionResult:
        tokens_before = estimate_tokens(messages, model_name)

        # 1. 检查触发
        stats = compute_context_stats(messages, model_name)
        if stats["utilization"] < self.threshold:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="micro",
            )

        # 2. 收集可压缩的工具结果索引
        compactable_indices: list[int] = []
        for i, msg in enumerate(messages):
            if (
                msg.role == "tool_result"
                and hasattr(msg, "tool_name")
                and msg.tool_name in COMPACTABLE_TOOLS
            ):
                compactable_indices.append(i)

        if len(compactable_indices) <= KEEP_RECENT_TOOL_RESULTS:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="micro",
                metadata={"reason": "too_few_compactable"},
            )

        # 3. 保留最后 N 个，清除其余
        keep_from = len(compactable_indices) - KEEP_RECENT_TOOL_RESULTS
        indices_to_clear = set(compactable_indices[:keep_from])

        changed = False
        result: list[ChatMessage] = []
        for i, msg in enumerate(messages):
            if i in indices_to_clear and msg.role == "tool_result":
                content = getattr(msg, "content", "")
                if content != CLEAR_MARKER:
                    changed = True
                    result.append(msg.model_copy(update={"content": CLEAR_MARKER}))
                else:
                    result.append(msg)
            else:
                result.append(msg)

        if not changed:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="micro",
            )

        tokens_after = estimate_tokens(result, model_name)
        return CompactionResult(
            messages=result, did_compact=True,
            tokens_before=tokens_before, tokens_after=tokens_after,
            kind="micro",
            metadata={
                "cleared_count": len(indices_to_clear),
                "kept_count": KEEP_RECENT_TOOL_RESULTS,
            },
        )
