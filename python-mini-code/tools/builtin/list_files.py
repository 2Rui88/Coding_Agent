"""list_files — 列出目录内容。"""

import os
from pathlib import Path

from pydantic import BaseModel, Field

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.workspace import resolve_tool_path


class ListFilesInput(BaseModel):
    path: str = "."


async def _run(input: ListFilesInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "list")

    entries = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower())):
            suffix = "/" if entry.is_dir() else ""
            try:
                stat = entry.stat()
                size = f"{stat.st_size:>8}"
            except OSError:
                size = "       -"
            entries.append(f"{size}  {entry.name}{suffix}")
    except FileNotFoundError:
        return ToolResult(ok=False, output=f"Directory not found: {input.path}")
    except PermissionError:
        return ToolResult(ok=False, output=f"Permission denied: {input.path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))

    return ToolResult(
        ok=True,
        output=f"Contents of {input.path}:\n" + "\n".join(entries),
    )


list_files_tool = ToolDefinition(
    name="list_files",
    description="List files and directories in a given path.",
    input_schema=ListFilesInput.model_json_schema(),
    input_model=ListFilesInput,
    run=_run,
)
