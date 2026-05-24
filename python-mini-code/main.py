"""mini-code — AI 终端编程助手。

入口文件，负责参数解析、组件初始化、模式分发。

模式:
  - TTY 交互模式 (isatty) → 待 M4 实现
  - 管道模式 (stdin 重定向) → 单次请求
  - 管理命令 (mcp/skills) → 待 M3 实现
"""

from __future__ import annotations

import asyncio
import sys

from agent.loop import run_agent_turn
from config.settings import RuntimeConfig
from infra.types import MessageList
from model.anthropic import AnthropicAdapter
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


def _list_tools(registry: ToolRegistry) -> str:
    """格式化工具列表。"""
    lines = []
    for tool in registry.list():
        lines.append(f"  {tool.name}: {tool.description}")
    return "\n".join(lines)


async def _handle_slash(line: str, config: RuntimeConfig) -> str | None:
    """处理斜杠命令，返回 response 或 None（交给模型）。"""
    cmd = line.strip()
    if cmd == "/exit":
        print("Bye.")
        sys.exit(0)
    if cmd == "/help":
        return "Commands: /help /tools /status /model /exit"
    if cmd == "/tools":
        registry = _make_registry()
        return _list_tools(registry)
    if cmd == "/status":
        return f"model: {config.model}\nbase_url: {config.base_url}"
    if cmd.startswith("/model "):
        new_model = cmd[len("/model "):].strip()
        return f"Model override requested: {new_model} (restart to apply)"
    if cmd == "/model":
        return f"Current model: {config.model}"
    return None


def _make_registry() -> ToolRegistry:
    """创建默认工具注册中心。"""
    return ToolRegistry([
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


def _build_system_prompt(cwd: str) -> str:
    """构建 System Prompt。"""
    return "\n\n".join([
        "You are mini-code, a terminal coding assistant.",
        "Default behavior: inspect the repository, use tools, make code changes when appropriate, and explain results clearly.",
        "Prefer reading files, searching code, editing files, and running verification commands over giving purely theoretical advice.",
        f"Current cwd: {cwd}",
        "When making code changes, keep them minimal, practical, and working-oriented.",
        "If you need user clarification, call the ask_user tool.",
        "Structured response protocol:",
        "- When still working, start with <progress>.",
        "- Only when the task is complete, start with <final>.",
        "- After <progress>, continue with the next concrete tool call.",
    ])


async def _run_pipe_mode(cwd: str, config: RuntimeConfig) -> None:
    """管道模式：从 stdin 读取一批消息并执行。"""
    tools = _make_registry()
    model = AnthropicAdapter(tools, config)

    print(f"mini-code 0.1.0 | model: {config.model} | cwd: {cwd}\n")

    messages: MessageList = [
        {"role": "system", "content": _build_system_prompt(cwd)},
    ]

    # 从 stdin 读取用户输入
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            messages.append({"role": "user", "content": raw})
    else:
        # 交互读行
        print("Enter a message (or /exit to quit):")
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not raw:
            print("Empty input.")
            return

        # 斜杠命令
        slash_resp = await _handle_slash(raw, config)
        if slash_resp is not None:
            print(slash_resp)
            return

        messages.append({"role": "user", "content": raw})

    # Agent Loop
    async for event in run_agent_turn(
        model=model,
        tools=tools,
        messages=messages,
        cwd=cwd,
        max_steps=25,
        model_name=config.model,
    ):
        match event.type:
            case "model_request":
                print(end="", flush=True)  # 思考中不输出
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
            case "turn_complete":
                pass
            case "max_steps":
                print("\n[Max steps reached]")
            case "empty_response_retry":
                print(f"\n[Retry #{event.attempt}: empty response]")
            case "thinking_recovery":
                print(f"\n[Recovery #{event.attempt}: {event.stop_reason}]")


async def main() -> None:
    cwd = "."  # 或 os.getcwd()
    config = await RuntimeConfig.load()

    await _run_pipe_mode(cwd, config)


if __name__ == "__main__":
    asyncio.run(main())
