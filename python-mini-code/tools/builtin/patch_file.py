"""patch_file — 对同一文件应用多个精确替换。"""

from pathlib import Path

from pydantic import BaseModel, Field

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.diff import apply_reviewed_change
from tools.workspace import resolve_tool_path


class PatchInput(BaseModel):
    path: str
    patches: list[dict] = Field(description="List of {search, replace} pairs applied in order.")


async def _run(input: PatchInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "write")
    try:
        original = Path(target).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ToolResult(ok=False, output=f"File not found: {input.path}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))

    current = original
    for i, patch in enumerate(input.patches):
        search = patch.get("search", "")
        replace = patch.get("replace", "")
        if search not in current:
            return ToolResult(ok=False, output=f"Patch {i + 1}: search text not found in {input.path}")
        current = current.replace(search, replace, 1)

    if current == original:
        return ToolResult(ok=True, output=f"No changes needed: {input.path}")

    return await apply_reviewed_change(context, input.path, target, current)


patch_file_tool = ToolDefinition(
    name="patch_file",
    description="Apply multiple search/replace patches to one file in order.",
    input_schema=PatchInput.model_json_schema(),
    input_model=PatchInput,
    run=_run,
)
