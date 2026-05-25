"""SnipCompact — 无模型安全区间删除。

从消息中间识别并移除安全段，用 snip_boundary 占位。
保护文件编辑附近、错误标记附近的消息。

对应 TypeScript 版本 compact/snipCompact.ts。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from context.constants import (
    SNIP_COMPACT_THRESHOLD,
    SNIP_KEEP_RECENT_MESSAGES,
    SNIP_MIN_MESSAGES_TO_REMOVE,
    SNIP_MIN_TOKENS_TO_FREE,
    SNIP_TARGET_USAGE,
    PROTECTED_TOOL_PATTERNS,
)
from context.groups import (
    MessageGroup,
    build_message_groups,
    find_safe_runs,
    message_id,
)
from context.strategy import CompactionResult, CompactionStrategy
from infra.tokens.counter import compute_context_stats
from infra.types import ChatMessage

# ---- 敏感标记 ----
ERROR_MARKERS = [
    "error", "failed", "failure", "exception",
    "traceback", "permission denied",
]


class SnipCompactStrategy(CompactionStrategy):
    """裁剪压缩：从中间移除安全段。"""

    name = "snip"
    threshold = SNIP_COMPACT_THRESHOLD

    async def apply(
        self,
        messages: list[ChatMessage],
        model_name: str,
        model=None,
    ) -> CompactionResult:
        tokens_before = _estimate(messages, model_name)

        # 1. 检查是否触发
        stats = compute_context_stats(messages, model_name)
        if stats["utilization"] < self.threshold:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="snip",
                metadata={"reason": "below_threshold"},
            )

        # 2. 确定候选区间
        candidate = _find_candidate_range(messages)
        if candidate is None:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="snip",
                metadata={"reason": "no_middle_range"},
            )

        # 3. 分组 + 标记保护
        groups = build_message_groups(
            messages,
            is_protected=lambda g: _has_protected_tool(g) or _has_important_error(g),
        )
        _mark_nearby_protection(groups)

        # 4. 找安全 run
        safe_runs = find_safe_runs(
            groups,
            candidate.start,
            candidate.end,
            min_messages=SNIP_MIN_MESSAGES_TO_REMOVE,
            min_tokens=SNIP_MIN_TOKENS_TO_FREE,
        )
        safe_runs.sort(key=lambda r: -sum(g.tokens for g in r))

        if not safe_runs:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="snip",
                metadata={"reason": "no_safe_interval"},
            )

        # 5. 选最优 run 并计算删除量
        best_run = safe_runs[0]
        target_tokens = int(
            stats["effective_input"] * SNIP_TARGET_USAGE
        )
        desired_free = max(
            SNIP_MIN_TOKENS_TO_FREE,
            tokens_before - target_tokens,
        )

        deletion = _select_deletion(best_run, desired_free)
        if deletion["messages_count"] < SNIP_MIN_MESSAGES_TO_REMOVE:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="snip",
                metadata={"reason": "below_min_messages"},
            )

        # 6. 执行删除
        removed = messages[deletion["start"]:deletion["end"]]
        removed_ids = [
            message_id(m, deletion["start"] + offset)
            for offset, m in enumerate(removed)
        ]

        boundary = _build_boundary(
            removed_count=len(removed),
            tokens_freed=deletion["tokens"],
            removed_ids=removed_ids,
        )
        boundary_tokens = _estimate([boundary], model_name)

        after = (
            list(messages[:deletion["start"]])
            + [boundary]
            + list(messages[deletion["end"]:])
        )

        tokens_after = _estimate(after, model_name)
        if tokens_after >= tokens_before:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="snip",
                metadata={"reason": "no_token_reduction"},
            )

        return CompactionResult(
            messages=after, did_compact=True,
            tokens_before=tokens_before, tokens_after=tokens_after,
            kind="snip",
            metadata={
                "removed_count": len(removed),
                "removed_ids": removed_ids,
                "tokens_freed": deletion["tokens"] - boundary_tokens,
            },
        )


# ---- 辅助函数 ----

def _estimate(msgs: list[ChatMessage], model: str) -> int:
    from infra.tokens.counter import estimate_tokens
    return estimate_tokens(msgs, model)


def _find_candidate_range(messages: list[ChatMessage]) -> CandidateRange | None:
    if len(messages) <= SNIP_KEEP_RECENT_MESSAGES + SNIP_MIN_MESSAGES_TO_REMOVE:
        return None

    keep_start = max(0, len(messages) - SNIP_KEEP_RECENT_MESSAGES)

    last_user = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user = i
            break
    end = min(keep_start, last_user if last_user >= 0 else len(messages))
    if end <= 0:
        return None

    start = 0
    for i in range(end):
        from context.groups import is_boundary_message
        if is_boundary_message(messages[i]):
            start = i + 1

    if end - start < SNIP_MIN_MESSAGES_TO_REMOVE:
        return None

    return CandidateRange(start=start, end=end)


@dataclass
class CandidateRange:
    start: int
    end: int


def _has_protected_tool(group: MessageGroup) -> bool:
    for m in group.messages:
        if not hasattr(m, "tool_name"):
            continue
        name = m.tool_name.lower()
        for pattern in PROTECTED_TOOL_PATTERNS:
            if pattern in name:
                return True
        if any(p in name for p in ("patch", "write", "edit", "modify")):
            return True
    return False


def _has_important_error(group: MessageGroup) -> bool:
    for m in group.messages:
        content = _message_content(m).lower()
        if any(marker in content for marker in ERROR_MARKERS):
            return True
    return False


def _message_content(msg: ChatMessage) -> str:
    roles = {"system", "user", "assistant", "assistant_progress", "context_summary", "snip_boundary"}
    if msg.role in roles:
        return getattr(msg, "content", "")
    if hasattr(msg, "tool_name") and msg.role == "tool_result":
        return getattr(msg, "content", "")
    return ""


def _mark_nearby_protection(groups: list[MessageGroup]) -> None:
    for i, group in enumerate(groups):
        if group.protected:
            for j in range(max(0, i - 1), min(len(groups), i + 2)):
                if not groups[j].protected:
                    groups[j].protected = True
                    groups[j].reasons.append("near_protected")


@dataclass
class _Deletion:
    start: int
    end: int
    tokens: int
    messages_count: int


def _select_deletion(run: list[MessageGroup], desired_free: int) -> dict[str, Any]:
    tokens = 0
    end_idx = -1
    for idx, group in enumerate(run):
        tokens += group.tokens
        end_idx = idx
        if tokens >= desired_free:
            break

    end_group = run[max(0, end_idx)] if run else None
    if not end_group:
        return {"start": 0, "end": 0, "tokens": 0, "messages_count": 0}

    return {
        "start": run[0].start,
        "end": end_group.end,
        "tokens": tokens,
        "messages_count": end_group.end - run[0].start,
    }


def _build_boundary(
    removed_count: int, tokens_freed: int, removed_ids: list[str]
) -> ChatMessage:
    ts = int(__import__("time").time() * 1000)
    from infra.types import SnipBoundary
    return SnipBoundary(
        id=f"snip-{ts}-{removed_ids[0] if removed_ids else 'none'}",
        role="snip_boundary",
        content=(
            "[Snipped earlier conversation segment]\n\n"
            "A middle portion of the earlier conversation was removed "
            "to preserve context space.\n\n"
            f"Removed: {removed_count} messages, ~{tokens_freed} tokens freed.\n"
            "Recent conversation and active task context are preserved."
        ),
        removed_message_ids=removed_ids,
        removed_count=removed_count,
        tokens_freed=tokens_freed,
        timestamp=ts,
    )
