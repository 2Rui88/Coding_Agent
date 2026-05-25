"""ContextCollapse — LLM 摘要折叠。

将旧消息段提交 LLM 生成摘要，摘要注入模型可见投影视图
但原始消息完整保留在转录中。

核心设计："投影视图与真相源分离"——
project_collapsed_view() 在模型侧返回压缩后的消息，
原始 messages 永不修改。

对应 TypeScript 版本 compact/context-collapse.ts。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from context.constants import (
    COLLAPSE_KEEP_RECENT_MESSAGES,
    COLLAPSE_MAX_FAILURES,
    COLLAPSE_MAX_SPANS_PER_PASS,
    COLLAPSE_MIN_TOKENS_TO_SAVE,
    COLLAPSE_TARGET_USAGE,
    CONTEXT_COLLAPSE_THRESHOLD,
)
from context.groups import build_message_groups, is_boundary_message, message_id
from context.strategy import CompactionResult, CompactionStrategy
from infra.tokens.counter import compute_context_stats, estimate_tokens, mark_provider_usage_stale
from infra.types import ChatMessage


# ---- 数据结构 ----

@dataclass
class CollapseSpan:
    id: str
    start_message_id: str
    end_message_id: str
    message_ids: list[str]
    summary: str
    tokens_before: int
    tokens_after: int
    status: str = "staged"  # staged | committed
    created_at: int = 0
    reason: str = "context_pressure"


@dataclass
class CollapseState:
    spans: list[CollapseSpan] = field(default_factory=list)
    enabled: bool = True
    consecutive_failures: int = 0


# ---- 投影视图 ----

def project_collapsed_view(
    messages: list[ChatMessage],
    state: CollapseState,
) -> list[ChatMessage]:
    """生成模型可见的投影视图——用摘要消息替代折叠的 span。

    原始 messages 不变。投影后的消息列表中，
    每个 committed span 被一条 context_summary 消息替代。
    """
    if not state.enabled or not state.spans:
        return list(messages)

    committed = [s for s in state.spans if s.status == "committed"]
    if not committed:
        return list(messages)

    # 建立消息 ID → 索引的映射
    id_to_idx: dict[str, int] = {}
    for i, m in enumerate(messages):
        id_to_idx[message_id(m, i)] = i

    # 解析每个 span 在消息列表中的位置
    projections: list[dict] = []
    for span in committed:
        indices = []
        for mid in span.message_ids:
            idx = id_to_idx.get(mid)
            if idx is None:
                break
            indices.append(idx)
        else:
            # 检查连续性
            valid = all(
                indices[j] + 1 == indices[j + 1]
                for j in range(len(indices) - 1)
            )
            if valid:
                projections.append({
                    "start": indices[0],
                    "end": indices[-1] + 1,
                    "span": span,
                })

    projections.sort(key=lambda p: p["start"])
    occupied: set[int] = set()
    result: list[ChatMessage] = []

    cursor = 0
    for proj in projections:
        # 跳过重叠投影
        if any(i in occupied for i in range(proj["start"], proj["end"])):
            continue

        # 复制光标到投影起始的未折叠消息
        while cursor < proj["start"]:
            result.append(
                mark_provider_usage_stale(
                    messages[cursor],
                    "context-collapsed after this usage was recorded",
                )
            )
            cursor += 1

        # 插入摘要消息
        span = proj["span"]
        summary_msg: dict = {
            "id": f"collapse-summary-{span.id}",
            "role": "context_summary",
            "content": (
                f"[Collapsed context summary]\n"
                f"This summary replaces messages {span.start_message_id} "
                f"through {span.end_message_id}.\n\n"
                f"{span.summary}"
            ),
            "compressed_count": len(span.message_ids),
            "timestamp": span.created_at,
        }
        result.append(summary_msg)

        for i in range(proj["start"], proj["end"]):
            occupied.add(i)
        cursor = proj["end"]

    while cursor < len(messages):
        result.append(
            mark_provider_usage_stale(
                messages[cursor],
                "context-collapsed after this usage was recorded",
            )
        )
        cursor += 1

    return result


# ---- 摘要提示词 ----

def _build_collapse_prompt(conversation_text: str) -> str:
    return (
        "You are creating a local context-collapse summary for an AI coding session.\n"
        "The summary will replace only this older message span in the model-visible context.\n\n"
        "Produce the final summary in <summary> tags.\n\n"
        "Preserve:\n"
        "- User intent and active goals\n"
        "- Completed tasks and current state\n"
        "- Important decisions and constraints\n"
        "- Tool calls and tool results that still matter\n"
        "- File paths, function names, config keys, commands\n"
        "- Errors, failures, warnings with exact messages\n\n"
        "Rules: Do not invent facts. Keep it concise but specific.\n\n"
        f"Messages to summarize:\n\n{conversation_text}"
    )


def _parse_summary(response_text: str) -> str | None:
    """从 LLM 响应中提取 <summary> 标签内容。"""
    import re
    m = re.search(
        r"<summary>(.*?)</summary>",
        response_text, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _messages_to_text(messages: list[ChatMessage]) -> str:
    """将消息列表转为纯文本供 LLM 摘要。"""
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
            import json
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


# ---- 候选查找 ----

def _find_collapse_candidate(
    messages: list[ChatMessage],
    state: CollapseState,
    tokens_to_save: int,
) -> dict | None:
    """找到一段可以折叠的连续消息。"""
    if len(messages) == 0:
        return None

    # 确定尾部保留区
    last_user = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user = i
            break

    protected_start = min(
        max(0, len(messages) - COLLAPSE_KEEP_RECENT_MESSAGES),
        last_user if last_user >= 0 else len(messages),
    )
    if protected_start <= 0:
        return None

    # 排除已折叠的消息
    collapsed_ids = set()
    for span in state.spans:
        collapsed_ids.update(span.message_ids)

    # 分组
    groups = build_message_groups(messages)

    # 找安全 run
    safe_runs: list[list[MessageGroup]] = []
    current_run: list[MessageGroup] = []

    for g_idx, group in enumerate(groups):
        protected = (
            group.protected
            or group.start >= protected_start
            or any(
                message_id(m, group.start + offset) in collapsed_ids
                for offset, m in enumerate(group.messages)
            )
            or any(is_boundary_message(m) for m in group.messages)
        )

        if protected:
            if current_run:
                safe_runs.append(current_run)
                current_run = []
            continue

        current_run.append(group)

    if current_run:
        safe_runs.append(current_run)

    # 遍历 run，找第一个满足 tokens_to_save 的候选
    for run in safe_runs:
        tokens = 0
        for idx, group in enumerate(run):
            tokens += group.tokens
            estimated_after = max(128, int(tokens * 0.15))
            if tokens - estimated_after >= tokens_to_save:
                last = run[idx]
                selected = messages[run[0].start:last.end]
                msg_ids = [
                    message_id(m, run[0].start + offset)
                    for offset, m in enumerate(selected)
                ]
                return {
                    "start": run[0].start,
                    "end": last.end,
                    "message_ids": msg_ids,
                    "messages": selected,
                    "tokens_before": tokens,
                    "estimated_tokens_after": estimated_after,
                    "tokens_to_save": tokens - estimated_after,
                }

    return None


# ---- 策略 ----

class ContextCollapseStrategy(CompactionStrategy):
    """上下文折叠：用 LLM 摘要替代旧消息段。"""

    name = "collapse"
    threshold = CONTEXT_COLLAPSE_THRESHOLD

    def __init__(self):
        self.state = CollapseState()

    async def apply(
        self,
        messages: list[ChatMessage],
        model_name: str,
        model=None,
    ) -> CompactionResult:
        tokens_before = estimate_tokens(messages, model_name)

        if not self.state.enabled:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="collapse",
                metadata={"reason": "disabled"},
            )

        stats = compute_context_stats(messages, model_name)
        if stats["utilization"] < self.threshold:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="collapse",
                metadata={"reason": "below_threshold"},
            )

        # 计算需要节省的 token 数
        desired = max(
            COLLAPSE_MIN_TOKENS_TO_SAVE,
            int(
                stats["total_tokens"]
                - stats["effective_input"] * COLLAPSE_TARGET_USAGE
            ),
        )

        planned: list[CollapseSpan] = []
        current_projection = project_collapsed_view(messages, self.state)

        for _pass in range(COLLAPSE_MAX_SPANS_PER_PASS):
            proj_stats = compute_context_stats(current_projection, model_name)
            if proj_stats["utilization"] <= COLLAPSE_TARGET_USAGE and planned:
                break

            candidate = _find_collapse_candidate(
                messages, self.state, desired,
            )
            if candidate is None:
                break

            # 调用 LLM 生成摘要
            if model is None:
                self.state.consecutive_failures += 1
                break

            try:
                prompt_text = _messages_to_text(candidate["messages"])
                summary = await model.summarize(
                    candidate["messages"],
                    _build_collapse_prompt(prompt_text),
                )
                if not summary:
                    parsed = None
                else:
                    parsed = _parse_summary(summary)

                if not parsed:
                    self.state.consecutive_failures += 1
                    if self.state.consecutive_failures >= COLLAPSE_MAX_FAILURES:
                        self.state.enabled = False
                    break

                ts = int(time.time() * 1000)
                span = CollapseSpan(
                    id=f"collapse-{ts}-{_pass}-{candidate['message_ids'][0]}",
                    start_message_id=candidate["message_ids"][0],
                    end_message_id=candidate["message_ids"][-1],
                    message_ids=candidate["message_ids"],
                    summary=parsed,
                    tokens_before=candidate["tokens_before"],
                    tokens_after=candidate["estimated_tokens_after"],
                    status="staged",
                    created_at=ts,
                )

                if candidate["tokens_to_save"] < COLLAPSE_MIN_TOKENS_TO_SAVE:
                    if not planned:
                        self.state.consecutive_failures += 1
                    break

                span.status = "committed"
                planned.append(span)

            except Exception:
                self.state.consecutive_failures += 1
                if self.state.consecutive_failures >= COLLAPSE_MAX_FAILURES:
                    self.state.enabled = False
                break

        if not planned:
            return CompactionResult(
                messages=messages, did_compact=False,
                tokens_before=tokens_before, tokens_after=tokens_before,
                kind="collapse",
                metadata={"reason": "no_plans"},
            )

        # 提交 spans
        self.state.spans.extend(planned)
        self.state.consecutive_failures = 0

        projected = project_collapsed_view(messages, self.state)
        tokens_after = estimate_tokens(projected, model_name)

        return CompactionResult(
            messages=projected, did_compact=True,
            tokens_before=tokens_before, tokens_after=tokens_after,
            kind="collapse",
            metadata={
                "spans_committed": len(planned),
                "total_spans": len(self.state.spans),
            },
        )
