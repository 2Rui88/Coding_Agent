"""run_command — 在允许列表中执行开发命令（支持后台任务）。"""

import asyncio
import re
import shlex

from pydantic import BaseModel, Field

from infra.types import ToolContext, ToolResult
from tools.definition import ToolDefinition
from tools.workspace import resolve_tool_path

# 只读命令（自动放行）
READONLY_COMMANDS = {
    "pwd", "ls", "find", "rg", "grep", "cat", "head", "tail",
    "wc", "sed", "echo", "df", "du", "free", "uname", "uptime", "whoami",
}
# 开发命令（需要权限检查）
DEV_COMMANDS = {
    "git", "npm", "node", "python3", "python", "pytest",
    "bash", "sh", "bun", "cargo", "go", "make",
}
ALLOWED = READONLY_COMMANDS | DEV_COMMANDS


class RunCommandInput(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None


def _has_shell_chars(cmd: str) -> bool:
    return bool(re.search(r"[|&;<>()$`]", cmd))


def _is_background(cmd: str) -> bool:
    return cmd.rstrip().endswith("&") and not cmd.rstrip().endswith("&&")


async def _run(input: RunCommandInput, context: ToolContext) -> ToolResult:
    effective_cwd = input.cwd or context.cwd
    if input.cwd:
        effective_cwd = await resolve_tool_path(context, input.cwd, "list")

    # 解析命令
    if input.args:
        cmd_name = input.command.strip()
        cmd_args = [a.strip() for a in input.args]
        use_shell = False
    else:
        # 接受单字符串调用如 "git status"
        parts = shlex.split(input.command)
        if not parts:
            return ToolResult(ok=False, output="Empty command")
        cmd_name = parts[0]
        cmd_args = parts[1:]
        use_shell = _has_shell_chars(input.command)

    if not cmd_name:
        return ToolResult(ok=False, output="Empty command")

    is_background = _is_background(input.command) if use_shell else False

    # 权限检查
    if context.permissions is not None:
        if use_shell or cmd_name not in ALLOWED:
            try:
                await context.permissions.ensure_command(
                    "bash" if use_shell else cmd_name,
                    (["-lc", input.command.rstrip("&").strip()] if use_shell else cmd_args),
                    effective_cwd,
                )
            except Exception as e:
                return ToolResult(ok=False, output=str(e))

    # 后台执行
    if is_background:
        proc = await asyncio.create_subprocess_shell(
            input.command.rstrip("&").strip(),
            cwd=effective_cwd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return ToolResult(
            ok=True,
            output=f"Background command started.\nPID: {proc.pid}",
        )

    # 前台执行
    try:
        if use_shell:
            proc = await asyncio.create_subprocess_shell(
                input.command,
                cwd=effective_cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                cmd_name, *cmd_args,
                cwd=effective_cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        stdout, stderr = await proc.communicate()
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        output = out
        if err:
            output = f"{output}\n{err}" if output else err

        return ToolResult(ok=proc.returncode == 0, output=output.strip() or "(no output)")
    except FileNotFoundError:
        return ToolResult(ok=False, output=f"Command not found: {cmd_name}")
    except Exception as e:
        return ToolResult(ok=False, output=str(e))


run_command_tool = ToolDefinition(
    name="run_command",
    description="Run a development command from the allowlist. For shell pipelines use a full snippet.",
    input_schema=RunCommandInput.model_json_schema(),
    input_model=RunCommandInput,
    run=_run,
)
