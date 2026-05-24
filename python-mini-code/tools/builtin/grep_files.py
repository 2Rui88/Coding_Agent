"""grep_files — 文件内容搜索（使用子进程调用 rg / grep）。"""

import asyncio

from pydantic import BaseModel, Field

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.workspace import resolve_tool_path


class GrepFilesInput(BaseModel):
    pattern: str
    path: str = "."


async def _run(input: GrepFilesInput, context: ToolContext) -> ToolResult:
    target = await resolve_tool_path(context, input.path, "search")

    try:
        proc = await asyncio.create_subprocess_exec(
            "rg", "--line-number", "--color=never", "--no-heading",
            "--max-count=50",
            input.pattern, target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        try:
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", "--color=never",
                "-m", "50",
                input.pattern, target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return ToolResult(ok=False, output="Neither rg nor grep found. Install ripgrep or grep.")

    stdout, stderr = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode == 1 and not output:
        return ToolResult(ok=True, output=f"No matches found for: {input.pattern}")
    if proc.returncode != 0 and proc.returncode != 1:
        return ToolResult(ok=False, output=err or f"Search failed with code {proc.returncode}")

    return ToolResult(ok=True, output=output or "No matches found.")


grep_files_tool = ToolDefinition(
    name="grep_files",
    description="Search for a pattern in files using ripgrep or grep.",
    input_schema=GrepFilesInput.model_json_schema(),
    input_model=GrepFilesInput,
    run=_run,
)
