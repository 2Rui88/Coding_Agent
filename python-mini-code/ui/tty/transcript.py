"""转录管理 — 对话历史的内存存储与滚动。

对应 TypeScript 版本 tui/transcript.ts 中的转录数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TranscriptEntry:
    """单条转录条目。"""
    kind: Literal["user", "assistant", "progress", "tool_call", "tool_result", "compaction", "retry"]
    content: str = ""
    tool_name: str = ""
    is_error: bool = False


class Transcript:
    """转录管理器 — 存储对话历史并支持分页渲染。"""

    def __init__(self, max_entries: int = 500):
        self.entries: list[TranscriptEntry] = []
        self.max_entries = max_entries
        self._scroll_offset: int = 0

    def add(self, entry: TranscriptEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def add_user(self, content: str) -> None:
        self.add(TranscriptEntry(kind="user", content=content))

    def add_assistant(self, content: str, kind: str = "final") -> None:
        self.add(TranscriptEntry(
            kind="progress" if kind == "progress" else "assistant",
            content=content,
        ))

    def add_tool_call(self, tool_name: str) -> None:
        self.add(TranscriptEntry(kind="tool_call", tool_name=tool_name))

    def add_tool_result(self, tool_name: str, output: str, is_error: bool = False) -> None:
        self.add(TranscriptEntry(
            kind="tool_result", tool_name=tool_name,
            content=output, is_error=is_error,
        ))

    def add_compaction(self, kind: str, tokens_freed: int) -> None:
        self.add(TranscriptEntry(
            kind="compaction", content=str(tokens_freed), tool_name=kind,
        ))

    def add_retry(self, reason: str) -> None:
        self.add(TranscriptEntry(kind="retry", content=reason))

    @property
    def scroll_offset(self) -> int:
        return self._scroll_offset

    def scroll_up(self, lines: int = 5) -> None:
        self._scroll_offset = min(len(self.entries), self._scroll_offset + lines)

    def scroll_down(self, lines: int = 5) -> None:
        self._scroll_offset = max(0, self._scroll_offset - lines)

    def scroll_to_bottom(self) -> None:
        self._scroll_offset = 0

    def visible_entries(self, height: int = 20) -> list[TranscriptEntry]:
        """返回当前可见的条目（用于渲染）。"""
        start = max(0, len(self.entries) - height - self._scroll_offset)
        return self.entries[start:len(self.entries) - self._scroll_offset]
