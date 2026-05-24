"""edit_file — 精确文本替换（支持 replaceAll）。"""

from pathlib import Path

from pydantic import BaseModel

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.diff import apply_reviewed_change
from tools.workspace import resolve_tool_path


class EditFileInput(BaseModel):
    path: str
    search: str
    replace: str
    replace_all: bool = False


async def _run(input: EditFileInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "write")
    try:
        original = Path(target).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ToolResult(ok=False, output=f"File not found: {input.path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))

    if input.search not in original:
        return ToolResult(ok=False, output=f"Text not found in {input.path}")

    if input.replace_all:
        new_content = original.replace(input.search, input.replace)
    else:
        new_content = original.replace(input.search, input.replace, 1)

    return await apply_reviewed_change(context, input.path, target, new_content)


edit_file_tool = ToolDefinition(
    name="edit_file",
    description="Edit a text file by replacing exact text. Use replace_all=true to replace all occurrences.",
    input_schema=EditFileInput.model_json_schema(),
    input_model=EditFileInput,
    run=_run,
)
