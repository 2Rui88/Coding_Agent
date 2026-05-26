"""Session 级拒绝处理器 — 当前会话中已被用户拒绝的操作。"""

from perm.handlers.base import Decision, PermissionHandler, PermissionRequest, PermissionResult


class SessionDenyHandler(PermissionHandler):
    """Session 级别的拒绝列表优先检查。"""

    def __init__(self):
        self.denied_paths: set[str] = set()
        self.denied_commands: set[str] = set()
        self.denied_edits: set[str] = set()

    def add_deny(self, kind: str, target: str) -> None:
        if kind == "path":
            self.denied_paths.add(target)
        elif kind == "command":
            self.denied_commands.add(target)
        elif kind == "edit":
            self.denied_edits.add(target)

    async def handle(self, request, store) -> PermissionResult | None:
        if request.kind == "path" and request.target in self.denied_paths:
            return PermissionResult(decision=Decision.DENY, reason="session_denied")
        if request.kind == "command" and request.target in self.denied_commands:
            return PermissionResult(decision=Decision.DENY, reason="session_denied")
        if request.kind == "edit" and request.target in self.denied_edits:
            return PermissionResult(decision=Decision.DENY, reason="session_denied")
        return None
