"""UserInterface 协议 — 交互层抽象。

TTY 模式和管道模式各自实现此协议。
Agent Loop 只依赖此接口，不感知具体交互方式。

对应 TypeScript 版本中 tty-app.ts 和 index.ts 管道模式的公共抽象。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UserInterface(ABC):
    """交互层抽象接口。

    所有交互模式（TTY / Pipe / 未来 HTTP）实现此接口。
    """

    @abstractmethod
    async def display_banner(self, status: dict[str, Any]) -> None:
        """显示启动横幅。status 包含 model, cwd, tools_count 等。"""
        ...

    @abstractmethod
    async def display_assistant(self, content: str, kind: str = "final") -> None:
        """显示助手回复。kind: final | progress。"""
        ...

    @abstractmethod
    async def display_tool_call(self, tool_name: str, tool_input: Any) -> None:
        """显示工具调用。"""
        ...

    @abstractmethod
    async def display_tool_result(
        self, tool_name: str, output: str, is_error: bool = False,
    ) -> None:
        """显示工具执行结果。"""
        ...

    @abstractmethod
    async def display_compaction(self, kind: str, tokens_freed: int) -> None:
        """显示压缩事件。"""
        ...

    @abstractmethod
    async def display_retry(self, reason: str, attempt: int) -> None:
        """显示重试/恢复事件。"""
        ...

    @abstractmethod
    async def read_input(self) -> str:
        """读取用户输入。"""
        ...

    @abstractmethod
    async def prompt_permission(
        self, request: Any,  # PermissionRequest
    ) -> Any:  # PermissionResult
        """弹出权限审批交互。管道模式中此方法抛出异常或无操作。"""
        ...

    @abstractmethod
    async def on_shutdown(self) -> None:
        """即将关闭时的清理。"""
        ...
