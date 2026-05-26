"""权限持久化存储 — 读写 ~/.mini-code/permissions.json。

对应 TypeScript 版本 permissions.ts 中的 PermissionStore。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.paths import MINI_CODE_DIR

_PERMISSIONS_PATH = MINI_CODE_DIR / "permissions.json"


class PermissionStore:
    """持久化权限存储。"""

    def __init__(self):
        self.allowed_dirs: set[str] = set()
        self.denied_dirs: set[str] = set()
        self.allowed_commands: set[str] = set()
        self.denied_commands: set[str] = set()
        self.allowed_edits: set[str] = set()
        self.denied_edits: set[str] = set()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionStore":
        store = cls()
        store.allowed_dirs = set(data.get("allowedDirectoryPrefixes", []))
        store.denied_dirs = set(data.get("deniedDirectoryPrefixes", []))
        store.allowed_commands = set(data.get("allowedCommandPatterns", []))
        store.denied_commands = set(data.get("deniedCommandPatterns", []))
        store.allowed_edits = set(data.get("allowedEditPatterns", []))
        store.denied_edits = set(data.get("deniedEditPatterns", []))
        return store

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowedDirectoryPrefixes": sorted(self.allowed_dirs),
            "deniedDirectoryPrefixes": sorted(self.denied_dirs),
            "allowedCommandPatterns": sorted(self.allowed_commands),
            "deniedCommandPatterns": sorted(self.denied_commands),
            "allowedEditPatterns": sorted(self.allowed_edits),
            "deniedEditPatterns": sorted(self.denied_edits),
        }


async def read_permission_store() -> PermissionStore:
    """从磁盘读取权限存储。"""
    try:
        data = json.loads(_PERMISSIONS_PATH.read_text(encoding="utf-8"))
        return PermissionStore.from_dict(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return PermissionStore()


async def write_permission_store(store: PermissionStore) -> None:
    """将权限存储写入磁盘。"""
    _PERMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PERMISSIONS_PATH.write_text(
        json.dumps(store.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
