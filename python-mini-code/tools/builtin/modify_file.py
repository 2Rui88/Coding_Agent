"""modify_file — 全文替换（展示 diff 后应用）。"""

from pathlib import Path

from pydantic import BaseModel

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.diff import apply_reviewed_change
from tools.workspace import resolve_tool_path


class ModifyFileInput(BaseModel):
    path: str
    content: str


async def _run(input: ModifyFileInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "write")
    try:
        original = Path(target).read_text(encoding="utf-8")
    except FileNotFoundError:
        # 新文件，直接写入
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(input.content, encoding="utf-8")
        return ToolResult(ok=True, output=f"Created new file: {input.path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))

    if original == input.content:
        return ToolResult(ok=True, output=f"No changes needed: {input.path}")

    return await apply_reviewed_change(context, input.path, target, input.content)


modify_file_tool = ToolDefinition(
    name="modify_file",
    description="Replace the entire content of a file, showing a diff before applying.",
    input_schema=ModifyFileInput.model_json_schema(),
    input_model=ModifyFileInput,
    run=_run,
)
