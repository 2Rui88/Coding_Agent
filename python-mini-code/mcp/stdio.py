"""StdioMcpClient — 通过子进程 stdio 连接 MCP 服务器。

支持两种帧协议:
  - content-length: 以 Content-Length: N\r\n\r\n 为头
  - newline-json: 每行一个 JSON 消息

协议探测: 先尝试 content-length（快速探测 1.2s），失败后用完整超时重试，
再回退到 newline-json。协商结果写入缓存文件。

对应 TypeScript 版本 mcp.ts 中的 StdioMcpClient 类。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from config.settings import McpServerConfig
from mcp.auth import load_token
from mcp.client import McpClient

INIT_TIMEOUT = 10.0       # 完整超时
PROBE_TIMEOUT = 1.2       # 快速探测超时
CALL_TIMEOUT = 5.0        # 工具调用超时


class StdioMcpClient(McpClient):
    """Stdio JSON-RPC 2.0 客户端。"""

    def __init__(
        self,
        server_name: str,
        config: McpServerConfig,
        cwd: str,
    ):
        self._name = server_name
        self._config = config
        self._cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._buffer = b""
        self._line_buffer = ""
        self._protocol: str | None = None
        self._stderr_lines: list[str] = []

    @property
    def server_name(self) -> str:
        return self._name

    @property
    def protocol(self) -> str | None:
        return self._protocol

    # ---- 启动 ----

    async def start(self) -> None:
        if self._process is not None:
            return

        protocols = self._get_candidates()
        last_error: Exception | None = None

        for proto in protocols:
            is_probe = proto == "content-length"
            timeout = PROBE_TIMEOUT if is_probe else INIT_TIMEOUT
            try:
                await self._init_with_protocol(proto, timeout)
                return
            except asyncio.TimeoutError:
                if is_probe:
                    await self._cleanup()
                    try:
                        await self._init_with_protocol(proto, INIT_TIMEOUT)
                        return
                    except Exception as e:
                        last_error = e
                        await self._cleanup()
                        continue
                last_error = asyncio.TimeoutError(f"Init timed out for {proto}")
            except Exception as e:
                last_error = e
            await self._cleanup()

        raise last_error or RuntimeError(f"Failed to connect MCP server: {self._name}")

    def _get_candidates(self) -> list[str]:
        """获取协议探测候选列表。"""
        cfg_proto = self._config.protocol
        if cfg_proto == "content-length":
            return ["content-length"]
        if cfg_proto == "newline-json":
            return ["newline-json"]
        return ["content-length", "newline-json"]

    async def _init_with_protocol(self, protocol: str, timeout: float) -> None:
        await self._spawn()
        self._protocol = protocol
        await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mini-code", "version": "0.1.0"},
        }, timeout)
        self._notify("notifications/initialized", {})

    async def _spawn(self) -> None:
        cmd = self._config.command.strip()
        if not cmd:
            raise ValueError(f"MCP server '{self._name}' has no command.")

        self._buffer = b""
        self._line_buffer = ""
        self._stderr_lines.clear()
        self._pending.clear()

        cwd = self._cwd
        if self._config.cwd:
            cwd = str(Path(self._cwd).resolve() / self._config.cwd)

        env = os.environ.copy()
        for k, v in (self._config.env or {}).items():
            env[k] = str(v)

        self._process = await asyncio.create_subprocess_exec(
            cmd, *(self._config.args or []),
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 启动 stderr 读取任务
        asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                self._stderr_lines.append(line.decode(errors="replace").strip())
                self._stderr_lines = self._stderr_lines[-8:]
        except Exception:
            pass

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
        await self._cleanup()

    async def _cleanup(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("MCP connection closed"))
        self._pending.clear()

        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        self._protocol = None

    # ---- JSON-RPC ----

    def _notify(self, method: str, params: dict) -> None:
        self._send_raw({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(
        self, method: str, params: dict, timeout: float
    ) -> dict:
        request_id = self._next_id
        self._next_id += 1

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        self._send_raw({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    def _send_raw(self, message: dict) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError(f"MCP server '{self._name}' is not running.")

        body = json.dumps(message, ensure_ascii=False).encode("utf-8")

        if self._protocol == "newline-json":
            self._process.stdin.write(body + b"\n")
            return

        # content-length 帧协议
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self._process.stdin.write(header + body)

    # ---- 响应处理 ----

    async def _read_loop(self) -> None:
        """在后台持续读取 stdout 并分发响应。"""
        if not self._process or not self._process.stdout:
            return
        try:
            if self._protocol == "newline-json":
                await self._read_lines()
            else:
                await self._read_framed()
        except Exception:
            pass

    async def _read_lines(self) -> None:
        assert self._process and self._process.stdout
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
                self._handle_message(msg)
            except json.JSONDecodeError:
                pass

    async def _read_framed(self) -> None:
        assert self._process and self._process.stdout
        buf = b""
        while True:
            chunk = await self._process.stdout.read(4096)
            if not chunk:
                break
            buf += chunk

            while True:
                sep = buf.find(b"\r\n\r\n")
                if sep == -1:
                    break
                header_text = buf[:sep].decode(errors="replace")
                headers = header_text.split("\r\n")
                content_length = 0
                for h in headers:
                    if h.lower().startswith("content-length:"):
                        content_length = int(h.split(":", 1)[1].strip())
                        break
                if content_length == 0:
                    buf = buf[sep + 4:]
                    continue

                body_start = sep + 4
                body_end = body_start + content_length
                if len(buf) < body_end:
                    break

                payload = buf[body_start:body_end].decode(errors="replace")
                buf = buf[body_end:]
                try:
                    msg = json.loads(payload)
                    self._handle_message(msg)
                except json.JSONDecodeError:
                    pass

    def _handle_message(self, msg: dict) -> None:
        msg_id = msg.get("id")
        if not isinstance(msg_id, int):
            return

        fut = self._pending.get(msg_id)
        if fut is None or fut.done():
            return

        if "error" in msg:
            err = msg["error"]
            fut.set_exception(RuntimeError(
                f"MCP {self._name}: {err.get('message', 'unknown error')}"
            ))
            return

        fut.set_result(msg.get("result", {}))


# ---- 结果格式化 ----

def _format_tool_result(result: dict) -> dict:
    """将 MCP 工具调用结果格式化为 {ok, output}。"""
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
