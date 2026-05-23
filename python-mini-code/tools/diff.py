"""文件修改审查 — 展示 diff 并请求权限确认后写入。"""

import difflib
from pathlib import Path

from infra.types import ToolContext, ToolResult


def _generate_diff(original: str, modified: str, path: str) -> str:
    """生成 unified diff 文本。"""
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )


async def apply_reviewed_change(
    context: ToolContext,
    display_path: str,
    resolved_path: str,
    new_content: str,
) -> ToolResult:
    """展示 diff，请求权限确认，然后写入文件。

    Args:
        context: 工具执行上下文
        display_path: 用户看到的路径（可能是相对路径）
        resolved_path: 已解析的绝对路径
        new_content: 修改后的文件内容
    """
    try:
        original = Path(resolved_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ToolResult(ok=False, output=f"File not found: {display_path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))

    diff = _generate_diff(original, new_content, resolved_path)

    if context.permissions is not None:
        try:
            await context.permissions.ensure_edit(resolved_path, diff)
        except Exception as e:
            return ToolResult(ok=False, output=str(e))

    try:
        Path(resolved_path).write_text(new_content, encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"Successfully applied changes to {display_path}",
        )
    except Exception as e:
        return ToolResult(ok=False, output=str(e))
