"""write_file — 写入文件（需要权限确认）。"""

from pathlib import Path

from pydantic import BaseModel, Field

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.workspace import resolve_tool_path


class WriteFileInput(BaseModel):
    path: str
    content: str


async def _run(input: WriteFileInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "write")

    if context.permissions is not None:
        try:
            await context.permissions.ensure_edit(target, f"Write new file: {input.path}")
        except Exception as e:
            return ToolResult(ok=False, output=str(e))

    try:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(input.content, encoding="utf-8")
        return ToolResult(ok=True, output=f"Wrote {len(input.content)} bytes to {input.path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))


write_file_tool = ToolDefinition(
    name="write_file",
    description="Write a file to the local filesystem.",
    input_schema=WriteFileInput.model_json_schema(),
    input_model=WriteFileInput,
    run=_run,
)
