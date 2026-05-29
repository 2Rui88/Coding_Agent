"""内置斜杠命令 — /help /tools /status /model /exit 等。

对应 TypeScript 版本 cli-commands.ts 中的 tryHandleLocalCommand()。
"""

from __future__ import annotations

import sys

from commands.registry import CommandContext, register_slash, registry


@register_slash("/help", "/help", "Show available slash commands")
async def cmd_help(args: str, ctx: CommandContext) -> str:
    return registry.format_help()


@register_slash("/tools", "/tools", "List available tools and tool shortcuts")
async def cmd_tools(args: str, ctx: CommandContext) -> str:
    lines = []
    for tool in ctx.tools.list():
        lines.append(f"  {tool.name}: {tool.description}")
    return "\n".join(lines) if lines else "No tools registered."


@register_slash("/status", "/status", "Show current model and config source")
async def cmd_status(args: str, ctx: CommandContext) -> str:
    config = ctx.config
    lines = [
        f"model: {config.model}",
        f"base_url: {config.base_url}",
        f"auth: {'api_key' if config.api_key else 'auth_token' if config.auth_token else 'none'}",
        f"mcp servers: {len(config.mcp_servers)}",
    ]
    return "\n".join(lines)


@register_slash("/model", "/model [name]", "Show or set the current model")
async def cmd_model(args: str, ctx: CommandContext) -> str:
    args = args.strip()
    if args:
        return f"Model override: {args} (restart to apply)"
    return f"Current model: {ctx.config.model}"


@register_slash("/skills", "/skills", "List discovered SKILL.md workflows")
async def cmd_skills(args: str, ctx: CommandContext) -> str:
    skills = ctx.tools.skills
    if not skills:
        return "No skills discovered."
    return "\n".join(
        f"  {s['name']}: {s['description']} [{s.get('source', '?')}]"
        for s in skills
    )


@register_slash("/mcp", "/mcp", "Show configured MCP servers and connection state")
async def cmd_mcp(args: str, ctx: CommandContext) -> str:
    servers = ctx.tools.mcp_servers
    if not servers:
        return "No MCP servers configured."
    return "\n".join(
        f"  {s['name']}: status={s['status']} tools={s.get('tool_count', 0)}"
        + (f" protocol={s.get('protocol', '')}" if s.get('protocol') else "")
        + (f"\n    error={s.get('error', '')}" if s.get('error') else "")
        for s in servers
    )


@register_slash("/exit", "/exit", "Exit mini-code")
async def cmd_exit(args: str, ctx: CommandContext) -> str:
    print("Bye.")
    sys.exit(0)
