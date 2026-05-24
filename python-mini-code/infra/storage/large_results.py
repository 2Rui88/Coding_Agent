"""
大工具结果持久化 — 将超大输出落盘，上下文内替换为短预览 + 路径占位符。

对应 TypeScript 版本的 utils/tool-result-storage.ts。

关键阈值：
  - DEFAULT_MAX_RESULT_CHARS: 单条结果超过此值触发持久化（50KB）
  - MAX_BATCH_CHARS: 单批结果总共允许的字符数（200KB）
  - PREVIEW_CHARS: 占位符中保留的预览字符数（2KB）
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from config.paths import MINI_CODE_DIR

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TOOL_RESULTS_SUBDIR = "tool-results"
PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"

DEFAULT_MAX_RESULT_CHARS = 50_000
MAX_BATCH_CHARS = 200_000
PREVIEW_CHARS = 2_000

# ---------------------------------------------------------------------------
# 路径管理
# ---------------------------------------------------------------------------

_session_id = str(uuid.uuid4())[:8]


def _get_results_dir() -> Path:
    return MINI_CODE_DIR / TOOL_RESULTS_SUBDIR / _session_id


def _sanitize_filename(tool_use_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in tool_use_id)
    return safe or str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------

class ContentReplacementState:
    """跟踪已持久化的工具结果，避免重复写入。"""
    def __init__(self):
        self.seen_ids: set[str] = set()
        self.replacements: dict[str, str] = {}


def create_state() -> ContentReplacementState:
    return ContentReplacementState()


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def _format_chars(chars: int) -> str:
    if chars >= 1_000_000:
        return f"{chars / 1_000_000:.1f}M chars"
    if chars >= 1_000:
        return f"{round(chars / 1_000)}K chars"
    return f"{chars} chars"


def _build_placeholder(filepath: str, original_size: int, preview: str, has_more: bool) -> str:
    parts = [
        PERSISTED_OUTPUT_TAG,
        f"Output too large ({_format_chars(original_size)}). "
        f"Full output saved to: {filepath}",
        "",
        f"Preview (first {_format_chars(PREVIEW_CHARS)}):",
        preview,
    ]
    if has_more:
        parts.append("...")
    parts.append(PERSISTED_OUTPUT_CLOSING_TAG)
    return "\n".join(parts)


def _generate_preview(content: str) -> tuple[str, bool]:
    """生成预览文本，(preview, has_more)。"""
    if len(content) <= PREVIEW_CHARS:
        return content, False
    truncated = content[:PREVIEW_CHARS]
    last_nl = truncated.rfind("\n")
    if last_nl > PREVIEW_CHARS * 0.5:
        return content[:last_nl], True
    return truncated, True


async def replace_large_result(
    tool_use_id: str,
    tool_name: str,
    raw_content: str,
    state: ContentReplacementState | None = None,
    threshold: int = DEFAULT_MAX_RESULT_CHARS,
) -> str:
    """对超大工具结果做持久化替换。

    - 小于 threshold 的内容原样返回
    - 大于 threshold 的落盘并返回短占位符
    - 已处理过的 tool_use_id 直接返回缓存替换内容
    """
    if state is None:
        state = ContentReplacementState()

    # 已处理过
    previous = state.replacements.get(tool_use_id)
    if previous is not None:
        return previous

    content = raw_content.strip()
    if not content:
        state.seen_ids.add(tool_use_id)
        return f"({tool_name} completed with no output)"

    # 已是被持久化的占位符
    if content.startswith(PERSISTED_OUTPUT_TAG):
        state.seen_ids.add(tool_use_id)
        state.replacements[tool_use_id] = content
        return content

    # 小于阈值，直接返回
    if len(content) <= threshold:
        return content

    # 持久化到磁盘
    results_dir = _get_results_dir()
    results_dir.mkdir(parents=True, exist_ok=True)
    filepath = results_dir / f"{_sanitize_filename(tool_use_id)}.txt"

    try:
        filepath.write_text(content, encoding="utf-8")
    except FileExistsError:
        pass  # 已有同文件，继续使用

    preview, has_more = _generate_preview(content)
    replacement = _build_placeholder(str(filepath), len(content), preview, has_more)
    state.seen_ids.add(tool_use_id)
    state.replacements[tool_use_id] = replacement
    return replacement


async def apply_tool_result_budget(
    results: list[dict],
    state: ContentReplacementState,
    limit: int = MAX_BATCH_CHARS,
) -> list[dict]:
    """对一批工具结果做总字符数预算控制。

    如果所有结果的总大小超过 limit，优先对最大的结果做持久化。
    """
    if not results:
        return results

    visible_size = 0
    fresh: list[dict] = []  # (index, content, size)

    for i, r in enumerate(results):
        content = r["content"]
        previous = state.replacements.get(r["tool_use_id"])
        if previous is not None:
            visible_size += len(previous)
            continue
        if state.seen_ids.__contains__(r["tool_use_id"]):
            visible_size += len(content)
            continue
        fresh.append({"idx": i, "content": content, "size": len(content)})
        visible_size += len(content)

    if visible_size <= limit:
        return results

    # 按大小降序，优先替换最大的
    fresh.sort(key=lambda x: x["size"], reverse=True)

    for item in fresh:
        if visible_size <= limit:
            break
        replacement = await replace_large_result(
            item["idx"],
            results[item["idx"]].get("tool_name", "unknown"),
            item["content"],
            state,
        )
        results[item["idx"]]["content"] = replacement
        visible_size = visible_size - item["size"] + len(replacement)

    return results
