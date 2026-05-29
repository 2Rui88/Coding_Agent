"""TTY 渲染 — 基于 rich 的终端 UI 展示。

对应 TypeScript 版本 ui.ts 中的 renderBanner / renderFooterBar / renderStatusLine 等函数。
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

console = Console()


# ---- 布局 ----

def make_layout() -> Layout:
    """创建 TTY 主布局。

    ┌──────────────────────┐
    │       Header         │
    ├──────────────────────┤
    │                      │
    │     Transcript       │
    │                      │
    ├──────────────────────┤
    │     Status Bar       │
    ├──────────────────────┤
    │     Input Area       │
    └──────────────────────┘
    """
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="transcript"),
        Layout(name="status", size=1),
        Layout(name="input", size=3),
    )
    return layout


# ---- 头部 ----

def render_header(
    model: str,
    cwd: str,
    session_id: str = "",
    tools_count: int = 0,
    skills_count: int = 0,
    mcp_count: int = 0,
    mcp_connected: int = 0,
) -> Panel:
    """渲染顶部状态栏。"""
    parts = [
        ("bold cyan", "mini-code"),
        ("", " 0.3.0  "),
        ("dim", f"model: {model}  "),
        ("dim", f"cwd: {cwd}  "),
    ]
    text = Text.assemble(*parts)
    text.append(f"\ntools: {tools_count}  skills: {skills_count}  ")
    text.append(
        f"mcp: {mcp_connected}/{mcp_count}" if mcp_count > 0 else "mcp: 0",
        style="green" if mcp_connected == mcp_count else "yellow",
    )
    return Panel(text, title=f"Session: {session_id}" if session_id else None)


# ---- 转录区 ----

def render_transcript_entry(
    role: str, content: str, tool_name: str = "",
    is_error: bool = False, is_compaction: bool = False,
    kind: str = "",
) -> Text:
    """渲染单条转录条目。"""
    if role == "user":
        return Text.assemble(("bold", "\n> "), ("", content))
    if role == "assistant":
        prefix = "[progress] " if kind == "progress" else ""
        return Text.from_markup(f"\n{prefix}{content}")
    if role == "tool_call":
        return Text.from_markup(f"\n[dim]→ {tool_name}:[/dim]")
    if role == "tool_result":
        style = "red" if is_error else "dim"
        preview = content[:200] + "..." if len(content) > 200 else content
        return Text.from_markup(f"[{style}]{preview}[/{style}]")
    if role == "compaction":
        return Text.from_markup(f"\n[dim italic]compacted: freed ~{content} tokens[/dim italic]")
    if role == "retry":
        return Text.from_markup(f"\n[yellow]retry: {content}[/yellow]")
    return Text(content)


# ---- 底部状态 ----

def render_status(step: int, utilization: float = 0.0, tokens: int = 0) -> Text:
    """渲染底部状态栏。"""
    color = "green"
    if utilization > 0.85:
        color = "red"
    elif utilization > 0.50:
        color = "yellow"
    return Text.from_markup(
        f" step:{step}  ctx:[{color}]{utilization:.0%}[/{color}]  tokens:{tokens}"
    )


# ---- 审批弹窗 ----

def render_permission_prompt(
    kind: str, target: str, details: list[str],
) -> str:
    """渲染权限审批提示（简化版，使用 input 交互）。

    完整的 TTY 版本会在 prompt_toolkit 中实现富文本交互。
    """
    lines = [
        f"\n{'='*60}",
        f"  Permission Required: {kind}",
        f"  Target: {target}",
    ]
    for d in details:
        lines.append(f"  {d}")
    lines.append(f"{'='*60}")
    lines.append("  [y] allow once  [a] allow always  [n] deny")
    return "\n".join(lines)
