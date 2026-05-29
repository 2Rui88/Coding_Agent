"""TTY 输入处理 — 基于 prompt_toolkit 的多行输入 + 斜杠命令补全。

对应 TypeScript 版本 tui/input.ts + tui/input-parser.ts。
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from commands.registry import registry

# prompt_toolkit 样式
INPUT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "separator": "dim",
})


class SlashCompleter(Completer):
    """斜杠命令自动补全器。"""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if text.startswith("/"):
            for cmd in registry.complete(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                )


# 快捷键绑定
def make_key_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _(event):
        """Alt+Enter 插入换行（多行模式）。"""
        event.current_buffer.insert_text("\n")

    @kb.add("c-o")
    def _(event):
        """Ctrl+O 显示斜杠菜单。"""
        event.current_buffer.insert_text("/")

    return kb


def create_session(history_path: str | None = None) -> PromptSession:
    """创建 prompt_toolkit 会话。"""
    history = None
    if history_path:
        try:
            history = FileHistory(history_path)
        except Exception:
            pass

    return PromptSession(
        message=[
            ("class:prompt", "> "),
        ],
        style=INPUT_STYLE,
        completer=SlashCompleter(),
        key_bindings=make_key_bindings(),
        history=history,
        multiline=False,
    )


async def read_input(session: PromptSession) -> str:
    """读取一行用户输入。

    Returns:
        用户输入的文本（去除首尾空白）
    """
    try:
        text = await session.prompt_async()
        return text.strip()
    except (EOFError, KeyboardInterrupt):
        return "/exit"
