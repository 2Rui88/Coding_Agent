"""公共消息分组逻辑。

TypeScript 版中 snipCompact.ts 和 context-collapse.ts 各自实现了
buildMessageGroups()，逻辑相似但不完全相同。
Python 版提取为共享模块，各策略注入差异化的 is_protected() 判断函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from infra.tokens.counter import estimate_tokens
from infra.types import ChatMessage


@dataclass
class MessageGroup:
    """一组相邻的消息（通常是 tool_call + tool_result 成对）。"""
    start: int       # 在原始 messages 中的起始索引
    end: int         # 结束索引（不包含）
    messages: list[ChatMessage]
    tokens: int
    protected: bool = False
    reasons: list[str] = field(default_factory=list)


def is_boundary_message(msg: ChatMessage) -> bool:
    """判断是否为不可删除的边界消息。"""
    return msg.role in ("system", "context_summary", "snip_boundary")


def message_id(msg: ChatMessage, index: int) -> str:
    """获取消息的唯一标识，优先使用 id 字段。"""
    return getattr(msg, "id", None) or f"message-{index}"


def build_message_groups(
    messages: list[ChatMessage],
    is_protected: Callable[[MessageGroup], bool] | None = None,
) -> list[MessageGroup]:
    """将消息列表分组，tool_call + tool_result 成对。

    分组规则：
      - assistant_tool_call + tool_result (tool_use_id 匹配) 成对
      - assistant_thinking + 后续 tool_calls + tool_results 成组
      - 其他消息各成单独组
      - 边界消息 (system/context_summary/snip_boundary) 标记为受保护

    Args:
        messages: 消息列表
        is_protected: 可选的额外保护判断函数

    Returns:
        MessageGroup 列表，按原始顺序排列
    """
    groups: list[MessageGroup] = []

    i = 0
    while i < len(messages):
        msg = messages[i]

        # tool_call → 与后续 tool_result 配对
        if msg.role == "assistant_tool_call":
            group_msgs: list[ChatMessage] = [msg]
            cursor = i + 1
            # 收集后续连续的 tool_call
            while cursor < len(messages) and messages[cursor].role == "assistant_tool_call":
                group_msgs.append(messages[cursor])
                cursor += 1
            # 收集后续匹配的 tool_result
            seen_ids = {
                m.tool_use_id
                for m in group_msgs
                if hasattr(m, "tool_use_id")
            }
            while cursor < len(messages) and messages[cursor].role == "tool_result":
                tr = messages[cursor]
                if hasattr(tr, "tool_use_id") and tr.tool_use_id in seen_ids:
                    group_msgs.append(tr)
                    cursor += 1
                else:
                    break

            tokens = estimate_tokens(group_msgs, "cl100k_base")
            group = MessageGroup(
                start=i, end=cursor,
                messages=group_msgs,
                tokens=tokens,
            )
            if is_protected:
                group.protected = is_protected(group)
            groups.append(group)
            i = cursor
            continue

        # thinking 块 → 与后续 tool_calls + results 成组
        if msg.role == "assistant_thinking":
            group_msgs = [msg]
            cursor = i + 1
            while cursor < len(messages) and messages[cursor].role == "assistant_tool_call":
                group_msgs.append(messages[cursor])
                cursor += 1
            seen_ids = {
                m.tool_use_id
                for m in group_msgs
                if hasattr(m, "tool_use_id")
            }
            while cursor < len(messages) and messages[cursor].role == "tool_result":
                tr = messages[cursor]
                if hasattr(tr, "tool_use_id") and tr.tool_use_id in seen_ids:
                    group_msgs.append(tr)
                    cursor += 1
                else:
                    break

            tokens = estimate_tokens(group_msgs, "cl100k_base")
            # thinking 组如果有未闭合的 tool_call → 受保护
            has_tool_call = any(m.role == "assistant_tool_call" for m in group_msgs)
            has_result = any(m.role == "tool_result" for m in group_msgs)
            group = MessageGroup(
                start=i, end=cursor,
                messages=group_msgs,
                tokens=tokens,
                protected=has_tool_call and not _group_is_closed(group_msgs),
            )
            if is_protected and not group.protected:
                group.protected = is_protected(group)
            groups.append(group)
            i = cursor
            continue

        # 孤立 tool_result → 单独组，强制受保护
        if msg.role == "tool_result":
            tokens = estimate_tokens([msg], "cl100k_base")
            group = MessageGroup(
                start=i, end=i + 1,
                messages=[msg],
                tokens=tokens,
                protected=True,
                reasons=["orphan_tool_result"],
            )
            groups.append(group)
            i += 1
            continue

        # 边界消息 → 强制受保护
        if is_boundary_message(msg):
            tokens = estimate_tokens([msg], "cl100k_base")
            group = MessageGroup(
                start=i, end=i + 1,
                messages=[msg],
                tokens=tokens,
                protected=True,
                reasons=["boundary_message"],
            )
            groups.append(group)
            i += 1
            continue

        # 普通消息 → 单独组
        tokens = estimate_tokens([msg], "cl100k_base")
        group = MessageGroup(
            start=i, end=i + 1,
            messages=[msg],
            tokens=tokens,
        )
        if is_protected:
            group.protected = is_protected(group)
        groups.append(group)
        i += 1

    return groups


def _group_is_closed(group_messages: list[ChatMessage]) -> bool:
    """检查工具组是否闭合（所有 tool_call 都有对应 tool_result）。"""
    call_ids = {
        m.tool_use_id
        for m in group_messages
        if hasattr(m, "tool_use_id") and m.role == "assistant_tool_call"
    }
    result_ids = {
        m.tool_use_id
        for m in group_messages
        if hasattr(m, "tool_use_id") and m.role == "tool_result"
    }
    if not call_ids and not result_ids:
        return True
    return call_ids == result_ids


def find_safe_runs(
    groups: list[MessageGroup],
    candidate_start: int,
    candidate_end: int,
    min_messages: int = 6,
    min_tokens: int = 2000,
) -> list[list[MessageGroup]]:
    """在候选区间内找到由非保护组组成的连续安全 run。

    每个 run 是一段连续的未受保护的消息组，可以作为删除候选。
    """
    runs: list[list[MessageGroup]] = []
    current: list[MessageGroup] = []

    for group in groups:
        # 只考虑在候选区间内的组
        if group.end <= candidate_start or group.start >= candidate_end:
            continue

        if group.protected:
            if current:
                runs.append(current)
                current = []
            continue

        current.append(group)

    if current:
        runs.append(current)

    # 过滤太小的 run
    return [
        run for run in runs
        if _run_message_count(run) >= min_messages
        and _run_token_count(run) >= min_tokens
    ]


def _run_message_count(run: list[MessageGroup]) -> int:
    last = run[-1] if run else None
    first = run[0] if run else None
    if not last or not first:
        return 0
    return last.end - first.start


def _run_token_count(run: list[MessageGroup]) -> int:
    return sum(g.tokens for g in run)
