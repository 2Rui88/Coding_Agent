"""MCP 客户端抽象接口。

对应 TypeScript 版本 mcp.ts 中的 McpClientLike 类型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class McpClient(ABC):
    """MCP 客户端抽象基类。

    子类：StdioMcpClient / StreamableHttpMcpClient。
    """

    @abstractmethod
    async def start(self) -> None:
        """启动客户端，完成 initialize 握手。"""
        ...

    @abstractmethod
    async def list_tools(self) -> list[dict]:
        """获取工具列表。"""
        ...

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> dict:
        """调用工具，返回 {ok, output}。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """关闭客户端。"""
        ...

    @property
    @abstractmethod
    def server_name(self) -> str:
        ...

    @property
    @abstractmethod
    def protocol(self) -> str | None:
        ...
