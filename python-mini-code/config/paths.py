"""配置路径常量 — 统一管理所有持久化文件路径。"""

import os
from pathlib import Path

MINI_CODE_HOME = os.environ.get("MINI_CODE_HOME", str(Path.home() / ".mini-code"))
MINI_CODE_DIR = Path(MINI_CODE_HOME)

SETTINGS_PATH = MINI_CODE_DIR / "settings.json"
HISTORY_PATH = MINI_CODE_DIR / "history.jsonl"
PERMISSIONS_PATH = MINI_CODE_DIR / "permissions.json"
MCP_PATH = MINI_CODE_DIR / "mcp.json"
MCP_TOKENS_PATH = MINI_CODE_DIR / "mcp-tokens.json"
MCP_PROTOCOL_CACHE_PATH = MINI_CODE_DIR / "mcp-protocol-cache.json"
PROJECTS_DIR = MINI_CODE_DIR / "projects"

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
PROJECT_MCP_PATH = Path.cwd() / ".mcp.json"
