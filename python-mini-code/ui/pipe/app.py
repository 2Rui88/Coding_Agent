"""管道模式 — 非 TTY 环境下的极简交互。

从 main.py 中抽离出来的管道模式逻辑。
实现 UserInterface 协议。
"""

from __future__ import annotations

import sys
from typing import Any

from ui.protocol import UserInterface


class PipeUI(UserInterface):
    """管道模式交互 — 纯文本输入输出。"""

    def __init__(self, input_text: str | None = None):
        self._input = input_text

    async def display_banner(self, status: dict[str, Any]) -> None:
        model = status.get("model", "?")
        cwd = status.get("cwd", ".")
        tools = status.get("tools_count", 0)
        skills = status.get("skills_count", 0)
        mcp = status.get("mcp_count", 0)
        print(f"mini-code 0.3.0 | model: {model} | cwd: {cwd}")
        print(f"tools: {tools} | skills: {skills} | mcp: {mcp}\n")

    async def display_assistant(self, content: str, kind: str = "final") -> None:
        if kind == "progress":
            print(f"\n[progress] {content}")
        else:
            print(f"\n{content}")

    async def display_tool_call(self, tool_name: str, tool_input: Any) -> None:
        print(f"\n[tool] {tool_name}: {tool_input}")

    async def display_tool_result(
        self, tool_name: str, output: str, is_error: bool = False,
    ) -> None:
        prefix = "[error]" if is_error else "[result]"
        preview = output[:300] + "..." if len(output) > 300 else output
        print(f"{prefix} {tool_name}: {preview}")

    async def display_compaction(self, kind: str, tokens_freed: int) -> None:
        print(f"\n[compaction] {kind}: freed ~{tokens_freed} tokens")

    async def display_retry(self, reason: str, attempt: int) -> None:
        print(f"\n[retry #{attempt}: {reason}]")

    async def read_input(self) -> str:
        if self._input is not None:
            return self._input
        if not sys.stdin.isatty():
            return sys.stdin.read().strip()
        try:
            return input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    async def prompt_permission(self, request: Any) -> Any:
        """管道模式不支持交互审批，自动拒绝。"""
        from perm.handlers.base import Decision, PermissionResult
        return PermissionResult(
            decision=Decision.DENY,
            reason="Pipe mode does not support interactive approval",
        )

    async def on_shutdown(self) -> None:
        pass
