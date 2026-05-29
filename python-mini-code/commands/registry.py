"""斜杠命令注册表 — 装饰器注册 + 自动补全 + 帮助生成。

替代 TypeScript 版 cli-commands.ts 中的 18 分支 if-else 链。

用法:
    @register_slash("/help", "/help", "Show available commands")
    async def cmd_help(args: str, ctx: CommandContext) -> str:
        return registry.format_help()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class CommandContext:
    """命令执行上下文。"""
    cwd: str
    config: Any  # RuntimeConfig
    tools: Any  # ToolRegistry
    permissions: Any  # PermissionManager | None


@dataclass
class SlashCommand:
    name: str
    usage: str
    description: str
    handler: Callable[[str, CommandContext], Awaitable[str]]


class CommandRegistry:
    """斜杠命令注册表。"""

    def __init__(self):
        self._commands: dict[str, SlashCommand] = {}

    def register(
        self,
        name: str,
        usage: str,
        description: str,
        handler: Callable[[str, CommandContext], Awaitable[str]],
    ) -> None:
        self._commands[name] = SlashCommand(
            name=name, usage=usage, description=description, handler=handler,
        )

    def get(self, name: str) -> SlashCommand | None:
        return self._commands.get(name)

    def complete(self, prefix: str) -> list[str]:
        """自动补全 — 返回匹配的命令名列表。"""
        return [cmd.usage for cmd in self._commands.values() if cmd.usage.startswith(prefix)]

    def format_help(self) -> str:
        """生成帮助文本。"""
        lines = ["Available commands:"]
        for cmd in sorted(self._commands.values(), key=lambda c: c.name):
            lines.append(f"  {cmd.usage:30s} {cmd.description}")
        return "\n".join(lines)

    def list_commands(self) -> list[SlashCommand]:
        return list(self._commands.values())


# 全局注册表
registry = CommandRegistry()


def register_slash(name: str, usage: str, description: str):
    """装饰器：注册斜杠命令。"""
    def decorator(func):
        registry.register(name, usage, description, func)
        return func
    return decorator
