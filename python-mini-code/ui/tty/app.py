"""TTY 模式 — 全屏终端交互主循环。

基于 rich + prompt_toolkit 实现:
  - 顶部状态栏（模型名 / cwd / session / 工具数）
  - 中部转录区（对话历史滚动）
  - 底部输入区（prompt_toolkit 多行 + 斜杠补全）
  - 权限审批弹窗

对应 TypeScript 版本 tty-app.ts 的核心循环逻辑。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from agent.events import *
from agent.loop import run_agent_turn
from commands.registry import CommandContext, registry
from context.pipeline import create_default_pipeline
from infra.types import MessageList
from model.anthropic import AnthropicAdapter
from perm.handlers.base import Decision, PermissionResult
from perm.manager import PermissionManager
from tools.definition import ToolRegistry
from ui.protocol import UserInterface
from ui.tty.input_handler import create_session, read_input
from ui.tty.render import (
    console,
    make_layout,
    render_header,
    render_permission_prompt,
    render_status,
    render_transcript_entry,
)
from ui.tty.transcript import Transcript


class TtyUI(UserInterface):
    """TTY 全屏交互界面。"""

    def __init__(
        self,
        model: AnthropicAdapter,
        tools: ToolRegistry,
        config: Any,
        permissions: PermissionManager,
        session_id: str = "",
        cwd: str = ".",
    ):
        self.model = model
        self.tools = tools
        self.config = config
        self.permissions = permissions
        self.session_id = session_id
        self.cwd = cwd
        self.transcript = Transcript()
        self._step = 0
        self._layout = make_layout()
        self._prompt_session = create_session()

    # ---- UserInterface 实现 ----

    async def display_banner(self, status: dict[str, Any]) -> None:
        header = render_header(
            model=status.get("model", "?"),
            cwd=status.get("cwd", "."),
            session_id=self.session_id,
            tools_count=status.get("tools_count", 0),
            skills_count=status.get("skills_count", 0),
            mcp_count=status.get("mcp_count", 0),
            mcp_connected=status.get("mcp_connected", 0),
        )
        console.print(header)

    async def display_assistant(self, content: str, kind: str = "final") -> None:
        self.transcript.add_assistant(content, kind)
        entry = render_transcript_entry("assistant", content, kind=kind)
        console.print(entry)

    async def display_tool_call(self, tool_name: str, tool_input: Any) -> None:
        self.transcript.add_tool_call(tool_name)
        entry = render_transcript_entry("tool_call", "", tool_name=tool_name)
        console.print(entry)

    async def display_tool_result(
        self, tool_name: str, output: str, is_error: bool = False,
    ) -> None:
        self.transcript.add_tool_result(tool_name, output, is_error)
        entry = render_transcript_entry(
            "tool_result", output, tool_name=tool_name, is_error=is_error,
        )
        console.print(entry)

    async def display_compaction(self, kind: str, tokens_freed: int) -> None:
        self.transcript.add_compaction(kind, tokens_freed)
        entry = render_transcript_entry("compaction", str(tokens_freed), kind=kind)
        console.print(entry)

    async def display_retry(self, reason: str, attempt: int) -> None:
        self.transcript.add_retry(f"{reason} #{attempt}")
        entry = render_transcript_entry("retry", f"{reason} #{attempt}")
        console.print(entry)

    async def read_input(self) -> str:
        console.print(render_status(self._step))
        return await read_input(self._prompt_session)

    async def prompt_permission(self, request: Any) -> Any:
        """显示权限审批弹窗，等待用户选择。"""
        details = getattr(request, "details", {}) or {}
        detail_lines = []
        if isinstance(details, dict):
            for k, v in details.items():
                detail_lines.append(f"{k}: {v}")

        prompt_text = render_permission_prompt(
            kind=getattr(request, "kind", "?"),
            target=getattr(request, "target", "?"),
            details=detail_lines,
        )
        console.print(prompt_text)

        # 等待用户输入
        try:
            choice = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Choice: ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            return PermissionResult(decision=Decision.DENY, reason="cancelled")

        if choice in ("y", "yes"):
            return PermissionResult(decision=Decision.ALLOW, reason="allow_once")
        if choice in ("a", "always"):
            return PermissionResult(decision=Decision.ALLOW, reason="allow_always")
        if choice in ("t", "turn"):
            return PermissionResult(decision=Decision.ALLOW, reason="allow_turn")
        return PermissionResult(decision=Decision.DENY, reason="user_denied")

    async def on_shutdown(self) -> None:
        console.print("\n[dim]Goodbye.[/dim]")

    # ---- 主循环 ----

    async def run(
        self,
        messages: MessageList,
        max_steps: int = 25,
    ) -> MessageList:
        """运行 TTY 交互模式。

        主循环：读取输入 → 处理命令 → Agent Loop → 渲染输出
        """
        pipeline = create_default_pipeline()
        current_messages = list(messages)

        # 显示启动信息
        mcp_servers = self.tools.mcp_servers
        mcp_connected = sum(
            1 for s in mcp_servers if s.get("status") == "connected"
        )
        await self.display_banner({
            "model": self.config.model,
            "cwd": self.cwd,
            "tools_count": len(self.tools.list()),
            "skills_count": len(self.tools.skills),
            "mcp_count": len(mcp_servers),
            "mcp_connected": mcp_connected,
        })

        while True:
            # 读取用户输入
            user_input = await self.read_input()
            if not user_input:
                continue

            # 斜杠命令拦截
            if user_input.startswith("/"):
                ctx = CommandContext(
                    cwd=self.cwd,
                    config=self.config,
                    tools=self.tools,
                    permissions=self.permissions,
                )
                cmd_name = user_input.split()[0] if " " in user_input else user_input
                cmd = registry.get(cmd_name)
                if cmd is not None:
                    args = user_input[len(cmd_name):].strip()
                    try:
                        result = await cmd.handler(args, ctx)
                        console.print(f"\n{result}\n")
                    except SystemExit:
                        await self.on_shutdown()
                        return current_messages
                    continue
                else:
                    console.print(f"\nUnknown command: {cmd_name}. Type /help.\n")
                    continue

            # 追加到转录
            self.transcript.add_user(user_input)
            entry = render_transcript_entry("user", user_input)
            console.print(entry)

            # 追加到消息
            current_messages.append({"role": "user", "content": user_input})

            # 刷新 System Prompt（Skill/MCP 可能已变更）
            if current_messages[0]["role"] == "system":
                current_messages[0]["content"] = _build_system_prompt(
                    self.cwd, self.tools, self.permissions,
                )

            self.permissions.begin_turn()

            # Agent Loop
            self._step = 0
            async for event in run_agent_turn(
                model=self.model,
                tools=self.tools,
                messages=current_messages,
                cwd=self.cwd,
                permissions=self.permissions,
                max_steps=max_steps,
                model_name=self.config.model,
                pipeline=pipeline,
            ):
                match event.type:
                    case "turn_start":
                        self._step = event.step
                    case "model_response":
                        await self.display_assistant(
                            event.content,
                            kind=getattr(event, "kind", "final"),
                        )
                    case "tool_calls":
                        for c in event.calls:
                            await self.display_tool_call(
                                c.get("tool_name", "?"), c.get("input", {}),
                            )
                    case "tool_result":
                        await self.display_tool_result(
                            event.tool_name, event.output, event.is_error,
                        )
                        if event.await_user:
                            self.transcript.add_assistant(event.output)
                    case "compaction":
                        await self.display_compaction(
                            event.kind, event.data.get("tokens_freed", 0),
                        )
                    case "empty_response_retry":
                        await self.display_retry(
                            "empty_response", event.attempt,
                        )
                    case "thinking_recovery":
                        await self.display_retry(
                            event.stop_reason, event.attempt,
                        )
                    case "turn_complete":
                        current_messages = event.messages
                    case "max_steps":
                        current_messages = event.messages
                        console.print("\n[yellow]Max steps reached.[/yellow]")

            self.permissions.end_turn()


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
    return "\n\n".join(parts)
