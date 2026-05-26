"""mini-code — AI 终端编程助手。

入口文件，负责参数解析、组件初始化、模式分发。
"""

from __future__ import annotations

import asyncio
import os
import sys

from agent.loop import run_agent_turn
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


async def _make_registry(cwd: str, config: RuntimeConfig) -> ToolRegistry:
    """创建工具注册中心（含内置工具 + MCP 工具 + Skill 元数据）。"""
    registry = ToolRegistry([
        ask_user_tool,
        list_files_tool,
        grep_files_tool,
        read_file_tool,
        write_file_tool,
        modify_file_tool,
        edit_file_tool,
        patch_file_tool,
        run_command_tool,
        web_fetch_tool,
        web_search_tool,
    ])

    # 发现 Skills
    skills = await discover_skills(cwd)
    registry.skills = [
        {"name": s.name, "description": s.description, "source": s.source}
        for s in skills
    ]

    # 连接 MCP 服务器
    if config.mcp_servers:
        mcp_result = await create_mcp_backed_tools(cwd, config.mcp_servers)
        registry.add_tools(mcp_result["tools"])
        registry.mcp_servers = mcp_result["servers"]
        registry.add_disposer(mcp_result["dispose"])

    return registry


def _list_tools(registry: ToolRegistry) -> str:
    lines = []
    for tool in registry.list():
        lines.append(f"  {tool.name}: {tool.description}")
    return "\n".join(lines)


async def _handle_slash(
    line: str, config: RuntimeConfig, tools: ToolRegistry,
) -> str | None:
    cmd = line.strip()
    if cmd == "/exit":
        print("Bye.")
        sys.exit(0)
    if cmd == "/help":
        return "Commands: /help /tools /status /model /skills /mcp /exit"
    if cmd == "/tools":
        return _list_tools(tools)
    if cmd == "/status":
        return f"model: {config.model}\nbase_url: {config.base_url}"
    if cmd == "/skills":
        skills = tools.skills
        if not skills:
            return "No skills discovered."
        return "\n".join(
            f"  {s['name']}: {s['description']} [{s.get('source', '?')}]"
            for s in skills
        )
    if cmd == "/mcp":
        servers = tools.mcp_servers
        if not servers:
            return "No MCP servers configured."
        return "\n".join(
            f"  {s['name']}: status={s['status']} tools={s.get('tool_count', 0)}"
            + (f" error={s.get('error', '')}" if s.get("error") else "")
            for s in servers
        )
    if cmd.startswith("/model "):
        return f"Model override: {cmd[7:].strip()} (restart to apply)"
    if cmd == "/model":
        return f"Current model: {config.model}"
    return None


def _build_system_prompt(
    cwd: str, tools: ToolRegistry, permissions: PermissionManager | None,
) -> str:
    parts = [
        "You are mini-code, a terminal coding assistant.",
        "Default behavior: inspect the repository, use tools, make code changes when appropriate, and explain results clearly.",
        "Prefer reading files, searching code, editing files, and running verification commands over giving purely theoretical advice.",
        f"Current cwd: {cwd}",
        "When making code changes, keep them minimal, practical, and working-oriented.",
        "If you need user clarification, call the ask_user tool.",
        "Structured response protocol:",
        "- When still working, start with <progress>.",
        "- Only when the task is complete, start with <final>.",
    ]

    # Skills 摘要
    skills = tools.skills
    if skills:
        parts.append(
            "Available skills:\n"
            + "\n".join(f"- {s['name']}: {s['description']}" for s in skills)
        )
    else:
        parts.append("Available skills: none discovered")

    # MCP 服务器状态
    servers = tools.mcp_servers
    if servers:
        parts.append(
            "Connected MCP servers:\n"
            + "\n".join(
                f"- {s['name']}: {s['status']}, "
                f"tools={s.get('tool_count', 0)}"
                + (f", error={s['error']}" if s.get("error") else "")
                for s in servers
            )
        )

    # 权限摘要
    if permissions:
        parts.append(
            f"Permission context: cwd={cwd}"
        )

    return "\n\n".join(parts)


async def _run_pipe_mode(cwd: str, config: RuntimeConfig) -> None:
    permissions = PermissionManager(cwd, prompt=None)
    tools = await _make_registry(cwd, config)
    model = AnthropicAdapter(tools, config)

    print(f"mini-code 0.2.0 | model: {config.model} | cwd: {cwd}")
    print(f"tools: {len(tools.list())} | skills: {len(tools.skills)} | mcp: {len(tools.mcp_servers)}\n")

    messages: MessageList = [
        {"role": "system", "content": _build_system_prompt(cwd, tools, permissions)},
    ]

    # 从 stdin 读取用户输入
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            messages.append({"role": "user", "content": raw})
    else:
        print("Enter a message (or /exit to quit):")
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not raw:
            print("Empty input.")
            return

        slash_resp = await _handle_slash(raw, config, tools)
        if slash_resp is not None:
            print(slash_resp)
            return

        messages.append({"role": "user", "content": raw})

    permissions.begin_turn()

    pipeline = create_default_pipeline()

    async for event in run_agent_turn(
        model=model,
        tools=tools,
        messages=messages,
        cwd=cwd,
        permissions=permissions,
        max_steps=25,
        model_name=config.model,
        pipeline=pipeline,
    ):
        match event.type:
            case "model_request":
                print(end="", flush=True)
            case "model_response":
                if event.kind == "progress":
                    print(f"\n[progress] {event.content}")
                else:
                    print(f"\n{event.content}")
            case "tool_calls":
                for c in event.calls:
                    print(f"\n[tool] {c['tool_name']}: {c['input']}")
            case "tool_result":
                prefix = "[error]" if event.is_error else "[result]"
                print(f"{prefix} {event.tool_name}: {event.output[:300]}...")
            case "compaction":
                print(f"\n[compaction] {event.kind}: freed ~{event.data.get('tokens_freed', 0)} tokens")
            case "turn_complete":
                pass
            case "max_steps":
                print("\n[Max steps reached]")
            case "empty_response_retry":
                print(f"\n[Retry #{event.attempt}: empty response]")
            case "thinking_recovery":
                print(f"\n[Recovery #{event.attempt}: {event.stop_reason}]")

    permissions.end_turn()
    await tools.dispose()


async def main() -> None:
    cwd = os.getcwd()
    config = await RuntimeConfig.load()
    await _run_pipe_mode(cwd, config)


if __name__ == "__main__":
    asyncio.run(main())
