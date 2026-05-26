"""MCP Token 管理 — 加载/缓存 Bearer Token。

对应 TypeScript 版本 mcp.ts 中的 token cache 部分。
"""

from __future__ import annotations

from config.paths import MCP_TOKENS_PATH

# 内存缓存（永不过期，401 时通过 clear_token 手动清除）
_token_cache: dict[str, str] = {}


async def load_token(server_name: str) -> str | None:
    """加载指定 MCP 服务器的 token。

    先查内存缓存，再读文件。
    """
    if server_name in _token_cache:
        return _token_cache[server_name]

    try:
        import json
        data = json.loads(MCP_TOKENS_PATH.read_text(encoding="utf-8"))
        token = data.get(server_name, "").strip()
        if token:
            _token_cache[server_name] = token
            return token
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return None


def clear_token(server_name: str) -> None:
    """从缓存中清除指定服务器的 token（401 响应后调用）。"""
    _token_cache.pop(server_name, None)
