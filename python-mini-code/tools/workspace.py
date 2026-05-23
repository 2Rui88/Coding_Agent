"""工作区路径解析 — 对应 TypeScript 版本的 workspace.ts。"""

import os
from pathlib import Path

from infra.types import ToolContext


async def resolve_tool_path(
    context: ToolContext, target: str, intent: str = "read"
) -> str:
    """解析并校验工具操作路径。

    - 相对路径基于 context.cwd 解析
    - 绝对路径通过权限管理器校验
    - 返回规范化的绝对路径
    """
    resolved = str(Path(target) if Path(target).is_absolute() else Path(context.cwd) / target)

    if context.permissions is not None:
        perm_intent = "write" if intent in ("write", "edit") else intent
        await context.permissions.ensure_path_access(resolved, perm_intent)

    return resolved
