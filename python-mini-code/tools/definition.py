"""工具定义与注册中心。

ToolDefinition 是 Pydantic + Protocol 的混合：用 Pydantic 定义 schema，用 async callable 定义执行逻辑。
ToolRegistry 管理工具的生命周期：注册、查找、执行、释放。
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel

from infra.types import ToolContext, ToolResult

# ---------------------------------------------------------------------------
# ToolDefinition
# ---------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)


class ToolDefinition(BaseModel, Generic[T]):
    """工具定义 — 包含元数据和执行函数。

    TypeVar T 是输入参数的 Pydantic 模型，用于运行时校验。
    """
    name: str
    description: str
    input_schema: dict[str, Any]
    input_model: type[T]
    run: Callable[[T, ToolContext], ToolResult]

    class Config:
        arbitrary_types_allowed = True

    def to_anthropic_format(self) -> dict[str, Any]:
        """转换为 Anthropic API 的 tool 格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """工具注册中心 — 负责工具的注册、查找、执行和释放。

    支持动态添加（MCP 工具代理）和批量释放（MCP 客户端关闭）。
    """

    def __init__(self, tools: list[ToolDefinition] | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        self._disposers: list[Callable[[], None]] = []
        self._skills: list[dict] = []
        self._mcp_servers: list[dict] = []

        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        """注册一个工具（同名工具不会覆盖已有注册）。"""
        if tool.name not in self._tools:
            self._tools[tool.name] = tool

    def add_tools(self, tools: list[ToolDefinition]) -> None:
        """批量注册工具。"""
        for tool in tools:
            self.register(tool)

    def find(self, name: str) -> ToolDefinition | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    def list(self) -> list[ToolDefinition]:
        """返回所有已注册工具的列表。"""
        return list(self._tools.values())

    def to_anthropic_format(self) -> list[dict[str, Any]]:
        """将所有工具转为 Anthropic API 格式。"""
        return [tool.to_anthropic_format() for tool in self._tools.values()]

    def add_disposer(self, disposer: Callable[[], None]) -> None:
        """注册释放回调（工具销毁时调用）。"""
        self._disposers.append(disposer)

    def dispose(self) -> None:
        """释放所有注册的资源。"""
        for disposer in self._disposers:
            try:
                disposer()
            except Exception:
                pass  # 释放失败不影响其他资源
        self._disposers.clear()

    # ---- 元数据 ----

    @property
    def skills(self) -> list[dict]:
        return self._skills

    @skills.setter
    def skills(self, value: list[dict]) -> None:
        self._skills = value

    @property
    def mcp_servers(self) -> list[dict]:
        return self._mcp_servers

    @mcp_servers.setter
    def mcp_servers(self, value: list[dict]) -> None:
        self._mcp_servers = value

    # ---- 执行 ----

    async def execute(
        self,
        tool_name: str,
        raw_input: Any,
        context: ToolContext,
    ) -> ToolResult:
        """执行工具调用。

        步骤：查找 → Schema 校验 → 执行 → 异常包裹
        """
        tool = self.find(tool_name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {tool_name}")

        try:
            parsed = tool.input_model.model_validate(raw_input)
        except Exception as e:
            return ToolResult(ok=False, output=str(e))

        try:
            result = tool.run(parsed, context)
            # 支持同步和异步工具
            if hasattr(result, "__await__"):
                return await result  # type: ignore
            return result
        except Exception as e:
            return ToolResult(ok=False, output=str(e))
