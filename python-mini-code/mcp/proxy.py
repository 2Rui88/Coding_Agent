"""MCP 工具代理 — 将 MCP 工具包装为内部 ToolDefinition。

同时注册 list_mcp_resources / read_mcp_resource / list_mcp_prompts / get_mcp_prompt。

对应 TypeScript 版本 mcp.ts 中的 createMcpBackedTools() 函数。
"""

from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel
from typing import Any

from config.settings import McpServerConfig, RuntimeConfig
from infra.types import ToolResult
from mcp.client import McpClient
from mcp.http_client import StreamableHttpMcpClient
from mcp.stdio import StdioMcpClient


def _sanitize(segment: str) -> str:
    """将字符串转为安全的工具名片段。"""
    s = "".join(c if c.isalnum() or c in "_-" else "_" for c in segment.lower())
    return s.strip("_") or "tool"


def _summarize_endpoint(cfg: McpServerConfig) -> str:
    if cfg.url and cfg.url.strip():
        return cfg.url.strip()
    return f"{cfg.command or ''} {' '.join(cfg.args or [])}".strip()


def _normalize_schema(schema: dict | None) -> dict:
    if schema and isinstance(schema, dict) and not isinstance(schema, list):
        return schema
    return {"type": "object", "additionalProperties": True}


async def create_mcp_backed_tools(
    cwd: str,
    mcp_servers: dict[str, McpServerConfig],
) -> dict:
    """连接所有 MCP 服务器并返回工具代理。

    每个服务器的工具以 mcp__<server>__<tool> 格式注册。
    单个服务器连接失败不影响整体启动。

    Returns:
        {
            "tools": list[ToolDefinition],
            "servers": list[dict],       # McpServerSummary
            "dispose": Callable[[], None],
        }
    """
    from tools.definition import ToolDefinition

    clients: list[McpClient] = []
    tools: list[ToolDefinition] = []
    servers: list[dict] = []
    has_resources = False
    has_prompts = False

    for server_name, config in mcp_servers.items():
        if getattr(config, "enabled", True) is False:
            servers.append({
                "name": server_name,
                "command": _summarize_endpoint(config),
                "status": "disabled",
                "tool_count": 0,
            })
            continue

        # 选择客户端类型
        client: McpClient
        if config.url and config.url.strip():
            client = StreamableHttpMcpClient(server_name, config)
        else:
            client = StdioMcpClient(server_name, config, cwd)

        try:
            await client.start()
            descriptors = await client.list_tools()

            # 尝试获取 resources 和 prompts
            try:
                resources = await asyncio.wait_for(
                    _list_resources_safe(client), timeout=3.0,
                )
            except Exception:
                resources = None
            try:
                prompts = await asyncio.wait_for(
                    _list_prompts_safe(client), timeout=3.0,
                )
            except Exception:
                prompts = None

            if resources:
                has_resources = True
            if prompts:
                has_prompts = True

            clients.append(client)

            # 注册工具
            for desc in descriptors:
                wrapped_name = f"mcp__{_sanitize(server_name)}__{_sanitize(desc.get('name', 'tool'))}"
                input_schema = _normalize_schema(desc.get("inputSchema"))
                tool_desc = desc.get("description", "").strip() or f"Call MCP tool {desc.get('name', '?')} from {server_name}."

                def _make_runner(c: McpClient, d: dict):
                    async def _run(inp, ctx):
                        result = await c.call_tool(d.get("name", ""), inp.model_dump() if hasattr(inp, "model_dump") else {})
                        return ToolResult(ok=result.get("ok", True), output=result.get("output", ""))
                    return _run

                tools.append(ToolDefinition(
                    name=wrapped_name,
                    description=tool_desc,
                    input_schema=input_schema,
                    input_model=dict,  # type: ignore
                    run=_make_runner(client, desc),
                ))

            servers.append({
                "name": server_name,
                "command": _summarize_endpoint(config),
                "status": "connected",
                "tool_count": len(descriptors),
                "resource_count": len(resources) if resources else None,
                "prompt_count": len(prompts) if prompts else None,
                "protocol": client.protocol,
            })

        except Exception as e:
            await client.close()
            servers.append({
                "name": server_name,
                "command": _summarize_endpoint(config),
                "status": "error",
                "tool_count": 0,
                "error": str(e),
            })

    # 注册 resources/prompts 工具（如果有服务器发布了这些功能）
    if clients and has_resources:
        tools.extend(_make_resource_tools(clients))
    if clients and has_prompts:
        tools.extend(_make_prompt_tools(clients))

    def _dispose() -> None:
        for client in clients:
            try:
                asyncio.get_event_loop().run_until_complete(client.close())
            except Exception:
                pass

    return {
        "tools": tools,
        "servers": servers,
        "dispose": _dispose,
    }


async def _list_resources_safe(client: McpClient) -> list:
    """尝试获取 resources 列表（非标准方法，可能不支持）。"""
    if isinstance(client, StdioMcpClient):
        result = await client._request("resources/list", {}, 3.0)  # type: ignore
        return result.get("resources", [])
    return []


async def _list_prompts_safe(client: McpClient) -> list:
    """尝试获取 prompts 列表（非标准方法，可能不支持）。"""
    if isinstance(client, StdioMcpClient):
        result = await client._request("prompts/list", {}, 3.0)  # type: ignore
        return result.get("prompts", [])
    return []


def _make_resource_tools(clients: list[McpClient]) -> list:
    """生成 list_mcp_resources 和 read_mcp_resource 工具。"""
    from tools.definition import ToolDefinition

    # list_mcp_resources
    async def _list_res(inp, ctx):
        inp_dict = inp if isinstance(inp, dict) else inp.model_dump()
        target_name = inp_dict.get("server", "") if isinstance(inp_dict, dict) else ""
        targets = [
            c for c in clients
            if not target_name or c.server_name == target_name
        ]
        lines = []
        for c in targets:
            try:
                resources = await _list_resources_safe(c)
                for r in resources:
                    lines.append(f"{c.server_name}: {r.get('uri', '?')} ({r.get('name', '?')})")
            except Exception as e:
                lines.append(f"{c.server_name}: failed ({e})")
        return ToolResult(ok=True, output="\n".join(lines) or "No resources published.")

    list_res_tool = ToolDefinition(
        name="list_mcp_resources",
        description="List MCP resources exposed by connected servers.",
        input_schema={"type": "object", "properties": {"server": {"type": "string"}}},
        input_model=dict,
        run=_list_res,
    )

    # read_mcp_resource
    async def _read_res(inp, ctx):
        inp_dict = inp if isinstance(inp, dict) else inp.model_dump()
        server = inp_dict.get("server", "") if isinstance(inp_dict, dict) else ""
        uri = inp_dict.get("uri", "") if isinstance(inp_dict, dict) else ""
        for c in clients:
            if c.server_name == server:
                if isinstance(c, StdioMcpClient):
                    result = await c._request("resources/read", {"uri": uri}, 5.0)  # type: ignore
                    contents = result.get("contents", [])
                    text_parts = []
                    for item in contents:
                        text_parts.append(f"URI: {item.get('uri', '?')}")
                        if item.get("text"):
                            text_parts.append(item["text"])
                        elif item.get("blob"):
                            text_parts.append(f"BLOB: {item['blob']}")
                    return ToolResult(ok=True, output="\n".join(text_parts))
                return ToolResult(ok=False, output="Resource reading only supported via stdio")
        return ToolResult(ok=False, output=f"Unknown server: {server}")

    read_res_tool = ToolDefinition(
        name="read_mcp_resource",
        description="Read a specific MCP resource by server and URI.",
        input_schema={
            "type": "object",
            "properties": {"server": {"type": "string"}, "uri": {"type": "string"}},
            "required": ["server", "uri"],
        },
        input_model=dict,
        run=_read_res,
    )

    return [list_res_tool, read_res_tool]


def _make_prompt_tools(clients: list[McpClient]) -> list:
    """生成 list_mcp_prompts 和 get_mcp_prompt 工具。"""
    from tools.definition import ToolDefinition

    async def _list_prompts_fn(inp, ctx):
        inp_dict = inp if isinstance(inp, dict) else inp.model_dump()
        target_name = inp_dict.get("server", "") if isinstance(inp_dict, dict) else ""
        targets = [
            c for c in clients
            if not target_name or c.server_name == target_name
        ]
        lines = []
        for c in targets:
            try:
                prompts = await _list_prompts_safe(c)
                for p in prompts:
                    args_summary = ", ".join(
                        f"{a.get('name','?')}{'*' if a.get('required') else ''}"
                        for a in p.get("arguments", [])
                    )
                    lines.append(f"{c.server_name}: {p.get('name','?')} args=[{args_summary}] - {p.get('description','')}")
            except Exception as e:
                lines.append(f"{c.server_name}: failed ({e})")
        return ToolResult(ok=True, output="\n".join(lines) or "No prompts published.")

    list_prompts_tool = ToolDefinition(
        name="list_mcp_prompts",
        description="List MCP prompts exposed by connected servers.",
        input_schema={"type": "object", "properties": {"server": {"type": "string"}}},
        input_model=dict,
        run=_list_prompts_fn,
    )

    async def _get_prompt_fn(inp, ctx):
        inp_dict = inp if isinstance(inp, dict) else inp.model_dump()
        server = inp_dict.get("server", "") if isinstance(inp_dict, dict) else ""
        name = inp_dict.get("name", "") if isinstance(inp_dict, dict) else ""
        for c in clients:
            if c.server_name == server:
                if isinstance(c, StdioMcpClient):
                    result = await c._request("prompts/get", {  # type: ignore
                        "name": name,
                        "arguments": inp_dict.get("arguments", {}) if isinstance(inp_dict, dict) else {},
                    }, 5.0)
                    messages = result.get("messages", [])
                    text_parts = []
                    for m in messages:
                        role = m.get("role", "?")
                        content = m.get("content", "")
                        if isinstance(content, list):
                            content = "\n".join(
                                str(block.get("text", block))
                                if isinstance(block, dict) else str(block)
                                for block in content
                            )
                        text_parts.append(f"[{role}]\n{content}")
                    return ToolResult(ok=True, output="\n\n".join(text_parts))
                return ToolResult(ok=False, output="Prompt fetching only supported via stdio")
        return ToolResult(ok=False, output=f"Unknown server: {server}")

    get_prompt_tool = ToolDefinition(
        name="get_mcp_prompt",
        description="Fetch a rendered MCP prompt by server, name, and arguments.",
        input_schema={
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "name": {"type": "string"},
                "arguments": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["server", "name"],
        },
        input_model=dict,
        run=_get_prompt_fn,
    )

    return [list_prompts_tool, get_prompt_tool]
