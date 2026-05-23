"""配置加载 — pydantic-settings 实现多层配置合并。

合并优先级（从低到高）:
  1. ~/.claude/settings.json (兼容 Claude Code 配置)
  2. ~/.mini-code/settings.json (用户级)
  3. .mcp.json (项目级 MCP)
  4. ~/.mini-code/mcp.json (全局 MCP)
  5. 环境变量 (MINI_CODE_*)
"""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.paths import (
    CLAUDE_SETTINGS_PATH,
    MCP_PATH,
    MINI_CODE_HOME,
    PROJECT_MCP_PATH,
    SETTINGS_PATH,
)


class McpServerConfig(BaseSettings):
    """单个 MCP 服务器配置"""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True
    protocol: Literal["auto", "content-length", "newline-json", "streamable-http"] = "auto"


class RuntimeConfig(BaseSettings):
    """运行时配置，从多层来源合并。

    来源优先级（从低到高）:
      claude settings < global mcp < project mcp < mini-code settings < env
    """
    model: str = ""
    base_url: str = "https://api.anthropic.com"
    api_key: str | None = None
    auth_token: str | None = None
    max_output_tokens: int | None = None
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_prefix="MINI_CODE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _apply_fallback_env(self) -> "RuntimeConfig":
        """从 ANTHROPIC_* 环境变量补全缺失字段。"""
        if not self.model:
            self.model = os.environ.get("ANTHROPIC_MODEL", "").strip()
        if not self.base_url or self.base_url == "https://api.anthropic.com":
            env_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
            if env_url:
                self.base_url = env_url
        if not self.api_key and not self.auth_token:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
            self.auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip() or None
        return self

    @classmethod
    async def load(cls) -> "RuntimeConfig":
        """加载并合并所有配置源。"""
        # 1. 从环境变量初始化（pydantic-settings 自动完成）
        config = cls()

        # 2. 读取各层配置文件
        claude_settings = _read_json(CLAUDE_SETTINGS_PATH).get("model", "")
        mini_code_settings = _read_json(SETTINGS_PATH)
        global_mcp = _read_mcp(MCP_PATH)
        project_mcp = _read_mcp(PROJECT_MCP_PATH)

        # 3. 合并 model
        if not config.model:
            config.model = (
                mini_code_settings.get("model", "")
                or claude_settings
            )

        # 4. 合并 api_key / auth_token
        if not config.api_key and not config.auth_token:
            config.api_key = (
                mini_code_settings.get("apiKey")
                or mini_code_settings.get("api_key")
            )

        # 5. 合并 max_output_tokens
        if config.max_output_tokens is None:
            raw = mini_code_settings.get("maxOutputTokens")
            if isinstance(raw, (int, float)) and raw > 0:
                config.max_output_tokens = int(raw)

        # 6. 合并 MCP（global → project → settings 中的覆盖）
        merged_mcp = {**global_mcp, **project_mcp}
        settings_mcp = mini_code_settings.get("mcpServers", {})
        if isinstance(settings_mcp, dict):
            for name, server in settings_mcp.items():
                if name in merged_mcp:
                    merged_mcp[name] = {**merged_mcp[name], **server}
                else:
                    merged_mcp[name] = server

        config.mcp_servers = {
            name: McpServerConfig(**cfg) if isinstance(cfg, dict) else cfg
            for name, cfg in merged_mcp.items()
        }

        # 7. 校验
        if not config.model:
            raise ValueError(
                "No model configured. "
                "Set MINI_CODE_MODEL or ANTHROPIC_MODEL env, "
                "or add model to ~/.mini-code/settings.json."
            )
        if not config.api_key and not config.auth_token:
            raise ValueError(
                "No auth configured. "
                "Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN."
            )

        return config


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _read_mcp(path: Path) -> dict:
    raw = _read_json(path)
    return raw.get("mcpServers", {})
