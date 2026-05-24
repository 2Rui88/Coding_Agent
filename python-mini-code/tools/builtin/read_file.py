"""read_file — 读取文件内容。"""

from pathlib import Path

from pydantic import BaseModel, Field

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.workspace import resolve_tool_path


class ReadFileInput(BaseModel):
    path: str
    offset: int = 0
    limit: int | None = None


async def _run(input: ReadFileInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "read")
    try:
        content = Path(target).read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        total = len(lines)

        start = max(0, input.offset)
        end = len(lines) if input.limit is None else start + input.limit
        snippet = lines[start:end]
        output = "".join(snippet).rstrip("\n")
        if start > 0:
            header = f"[Showing lines {start + 1}-{min(end, total)} of {total}, TRUNCATED: yes]\n"
            output = header + output
        return ToolResult(ok=True, output=output)
    except FileNotFoundError:
        return ToolResult(ok=False, output=f"File not found: {input.path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))


read_file_tool = ToolDefinition(
    name="read_file",
    description="Read a file from the local filesystem with optional offset and limit.",
    input_schema=ReadFileInput.model_json_schema(),
    input_model=ReadFileInput,
    run=_run,
)
