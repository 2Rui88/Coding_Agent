"""StreamableHttpMcpClient — 通过 HTTP POST 连接远程 MCP 服务器。

对应 TypeScript 版本 mcp.ts 中的 StreamableHttpMcpClient 类。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from config.settings import McpServerConfig
from mcp.auth import clear_token, load_token
from mcp.client import McpClient

INIT_TIMEOUT = 10.0
CALL_TIMEOUT = 5.0


class StreamableHttpMcpClient(McpClient):
    """Streamable HTTP JSON-RPC 2.0 客户端。"""

    def __init__(self, server_name: str, config: McpServerConfig):
        self._name = server_name
        self._config = config
        self._next_id = 1
        self._bearer_token: str | None = None

    @property
    def server_name(self) -> str:
        return self._name

    @property
    def protocol(self) -> str | None:
        return "streamable-http"

    # ---- 启动 ----

    async def start(self) -> None:
        url = self._config.url or ""
        if not url.strip():
            raise ValueError(f"MCP server '{self._name}' has no URL configured.")

        self._bearer_token = await load_token(self._name)

        await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mini-code", "version": "0.1.0"},
        }, INIT_TIMEOUT)
        await self._notify("notifications/initialized", {})

    # ---- 工具操作 ----

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {}, CALL_TIMEOUT)
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        try:
            result = await self._request("tools/call", {
                "name": name,
                "arguments": arguments,
            }, CALL_TIMEOUT)
            return _format_tool_result(result)
        except Exception as e:
            return {"ok": False, "output": str(e)}

    # ---- 关闭 ----

    async def close(self) -> None:
        return

    # ---- HTTP 通信 ----

    async def _notify(self, method: str, params: dict) -> None:
        try:
            await self._post({"jsonrpc": "2.0", "method": method, "params": params}, 2.0)
        except Exception:
            pass

    async def _request(self, method: str, params: dict, timeout: float) -> dict:
        request_id = self._next_id
        self._next_id += 1
        result = await self._post({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }, timeout)

        if isinstance(result, dict) and "error" in result:
            err = result["error"]
            raise RuntimeError(
                f"MCP {self._name}: {err.get('message', 'unknown error')}"
            )
        return result.get("result", {}) if isinstance(result, dict) else {}

    async def _post(self, payload: dict, timeout: float) -> Any:
        url = self._config.url or ""
        if not url.strip():
            raise RuntimeError(f"MCP server '{self._name}' has no URL configured.")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # 添加服务端配置的自定义 headers
        for k, v in (self._config.headers or {}).items():
            headers[k] = str(v)
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=payload,
                headers=headers,
            )

            if resp.status_code == 401:
                clear_token(self._name)
                raise RuntimeError(f"MCP {self._name}: authentication required")

            if resp.status_code != 200:
                raise RuntimeError(
                    f"MCP {self._name}: HTTP {resp.status_code} {resp.text[:300]}"
                )

            text = resp.text.strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"MCP {self._name}: expected JSON but received non-JSON payload"
                )


def _format_tool_result(result: dict) -> dict:
    content = result.get("content", [])
    is_error = result.get("isError", False)
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
    return {
        "ok": not is_error,
        "output": "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False),
    }
