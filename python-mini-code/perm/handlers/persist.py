"""持久化拒绝/允许处理器 — 跨会话记忆的权限决策。"""

from pathlib import Path

from perm.handlers.base import Decision, PermissionHandler, PermissionRequest, PermissionResult


def _is_within_directory(root: str, target: str) -> bool:
    """检查 target 是否在 root 目录内。"""
    try:
        Path(target).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


class PersistDenyHandler(PermissionHandler):
    """持久化拒绝列表 — 跨会话生效。"""

    async def handle(self, request, store) -> PermissionResult | None:
        if request.kind == "path":
            for d in store.denied_dirs:
                if _is_within_directory(d, request.target):
                    return PermissionResult(decision=Decision.DENY, reason="persist_denied_dir")
            if request.target in store.denied_edits:
                return PermissionResult(decision=Decision.DENY, reason="persist_denied")
        if request.kind == "command" and request.target in store.denied_commands:
            return PermissionResult(decision=Decision.DENY, reason="persist_denied")
        if request.kind == "edit" and request.target in store.denied_edits:
            return PermissionResult(decision=Decision.DENY, reason="persist_denied")
        return None


class PersistAllowHandler(PermissionHandler):
    """持久化允许列表 — 跨会话生效。"""

    async def handle(self, request, store) -> PermissionResult | None:
        if request.kind == "path":
            for d in store.allowed_dirs:
                if _is_within_directory(d, request.target):
                    return PermissionResult(decision=Decision.ALLOW, reason="persist_allowed_dir")
            if request.target in store.allowed_edits:
                return PermissionResult(decision=Decision.ALLOW, reason="persist_allowed")
        if request.kind == "command" and request.target in store.allowed_commands:
            return PermissionResult(decision=Decision.ALLOW, reason="persist_allowed")
        if request.kind == "edit" and request.target in store.allowed_edits:
            return PermissionResult(decision=Decision.ALLOW, reason="persist_allowed")
        return None
