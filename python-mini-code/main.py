"""mini-code — AI 终端编程助手。

入口文件，负责组件初始化、模式分发。
"""

from __future__ import annotations

import asyncio
import os
import sys

from agent.loop import run_agent_turn
from commands.registry import CommandContext, registry

# 导入内置命令（触发装饰器注册）
import commands.builtin.basic  # noqa: F401

from config.settings import RuntimeConfig
from context.pipeline import create_default_pipeline
from infra.types import MessageList
from mcp.proxy import create_mcp_backed_tools
from model.anthropic import AnthropicAdapter
from perm.manager import PermissionManager
from skills.discover import discover_skills
from tools.builtin import (
    ask_user_tool,
    edit_file_tool,
    grep_files_tool,
    list_files_tool,
    modify_file_tool,
    patch_file_tool,
    read_file_tool,
    run_command_tool,
    web_fetch_tool,
    web_search_tool,
    write_file_tool,
)
from tools.definition import ToolRegistry
from ui.pipe.app import PipeUI


# ---- 工厂函数 ----

async def _make_registry(cwd: str, config: RuntimeConfig) -> ToolRegistry:
    """创建工具注册中心。"""
    registry_obj = ToolRegistry([
        ask_user_tool, list_files_tool, grep_files_tool,
        read_file_tool, write_file_tool, modify_file_tool,
        edit_file_tool, patch_file_tool, run_command_tool,
        web_fetch_tool, web_search_tool,
    ])

    skills = await discover_skills(cwd)
    registry_obj.skills = [
        {"name": s.name, "description": s.description, "source": s.source}
        for s in skills
    ]

    if config.mcp_servers:
        mcp_result = await create_mcp_backed_tools(cwd, config.mcp_servers)
        registry_obj.add_tools(mcp_result["tools"])
        registry_obj.mcp_servers = mcp_result["servers"]
        registry_obj.add_disposer(mcp_result["dispose"])

    return registry_obj


def _build_system_prompt(
    cwd: str, tools: ToolRegistry, permissions: PermissionManager | None,
) -> str:
    parts = [
        "You are mini-code, a terminal coding assistant.",
        f"Current cwd: {cwd}",
        "If you need user clarification, call the ask_user tool.",
        "Structured protocol: <progress> when working, <final> when complete.",
    ]
    skills = tools.skills
    if skills:
        parts.append(
            "Available skills:\n"
            + "\n".join(f"- {s['name']}: {s['description']}" for s in skills)
        )
    servers = tools.mcp_servers
    if servers:
        parts.append(
            "Connected MCP servers:\n"
            + "\n".join(
                f"- {s['name']}: {s['status']}, tools={s.get('tool_count', 0)}"
                for s in servers
            )
        )
    return "\n\n".join(parts)


# ---- 管道模式 ----

async def _run_pipe_mode(cwd: str, config: RuntimeConfig) -> None:
    """管道模式：利用 PipeUI 处理单轮输入输出。"""
    tools = await _make_registry(cwd, config)
    permissions = PermissionManager(cwd, prompt=None)
    model = AnthropicAdapter(tools, config)
    ui = PipeUI()

    await ui.display_banner({
        "model": config.model, "cwd": cwd,
        "tools_count": len(tools.list()),
        "skills_count": len(tools.skills),
        "mcp_count": len(tools.mcp_servers),
    })

    messages: MessageList = [
        {"role": "system", "content": _build_system_prompt(cwd, tools, permissions)},
    ]

    # 读取输入
    user_input = await ui.read_input()
    if not user_input:
        return

    # 斜杠命令
    if user_input.startswith("/"):
        ctx = CommandContext(
            cwd=cwd, config=config, tools=tools, permissions=permissions,
        )
        parts = user_input.split(maxsplit=1)
        cmd_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        cmd = registry.get(cmd_name)
        if cmd is not None:
            try:
                result = await cmd.handler(args, ctx)
                print(result)
            except SystemExit:
                pass
            return
        print(f"Unknown: {cmd_name}")
        return

    messages.append({"role": "user", "content": user_input})
    permissions.begin_turn()

    pipeline = create_default_pipeline()
    async for event in run_agent_turn(
        model=model, tools=tools, messages=messages, cwd=cwd,
        permissions=permissions, max_steps=25,
        model_name=config.model, pipeline=pipeline,
    ):
        match event.type:
            case "model_response":
                await ui.display_assistant(
                    event.content, kind=getattr(event, "kind", "final"),
                )
            case "tool_calls":
                for c in event.calls:
                    await ui.display_tool_call(
                        c.get("tool_name", "?"), c.get("input", {}),
                    )
            case "tool_result":
                await ui.display_tool_result(
                    event.tool_name, event.output, event.is_error,
                )
            case "compaction":
                await ui.display_compaction(
                    event.kind, event.data.get("tokens_freed", 0),
                )
            case "empty_response_retry":
                await ui.display_retry("empty_response", event.attempt)
            case "thinking_recovery":
                await ui.display_retry(event.stop_reason, event.attempt)
            case "turn_complete":
                pass
            case "max_steps":
                print("\n[Max steps reached]")

    permissions.end_turn()
    await tools.dispose()


# ---- TTY 模式 ----

async def _run_tty_mode(cwd: str, config: RuntimeConfig) -> None:
    """TTY 模式：全屏终端交互。"""
    from ui.tty.app import TtyUI

    tools = await _make_registry(cwd, config)
    permissions = PermissionManager(cwd, prompt=None)
    model = AnthropicAdapter(tools, config)

    # 将 prompt 回调绑定到 TtyUI
    ui = TtyUI(
        model=model, tools=tools, config=config,
        permissions=permissions, cwd=cwd,
    )
    permissions.prompt = ui.prompt_permission

    messages: MessageList = [
        {"role": "system", "content": _build_system_prompt(cwd, tools, permissions)},
    ]

    try:
        await ui.run(messages, max_steps=25)
    finally:
        await tools.dispose()
        await ui.on_shutdown()


# ---- 入口 ----

async def main() -> None:
    cwd = os.getcwd()
    config = await RuntimeConfig.load()

    if sys.stdout.isatty() and sys.stdin.isatty():
        await _run_tty_mode(cwd, config)
    else:
        await _run_pipe_mode(cwd, config)


if __name__ == "__main__":
    asyncio.run(main())
