"""Session 级允许处理器 — 当前会话中已被用户允许的操作。"""

from perm.handlers.base import Decision, PermissionHandler, PermissionRequest, PermissionResult


class SessionAllowHandler(PermissionHandler):
    """Session 级别的允许列表，避免重复审批。"""

    def __init__(self):
        self.allowed_paths: set[str] = set()
        self.allowed_commands: set[str] = set()
        self.allowed_edits: set[str] = set()
        self.turn_allowed_edits: set[str] = set()
        self.turn_allow_all_edits: bool = False

    def begin_turn(self) -> None:
        """每个回合开始时重置 turn 级编辑权限。"""
        self.turn_allowed_edits.clear()
        self.turn_allow_all_edits = False

    def add_allow(self, kind: str, target: str) -> None:
        if kind == "path":
            self.allowed_paths.add(target)
        elif kind == "command":
            self.allowed_commands.add(target)
        elif kind == "edit":
            self.allowed_edits.add(target)

    def add_turn_allow(self, target: str) -> None:
        self.turn_allowed_edits.add(target)

    async def handle(self, request, store) -> PermissionResult | None:
        if request.kind == "edit":
            if self.turn_allow_all_edits:
                return PermissionResult(decision=Decision.ALLOW, reason="turn_allow_all")
            if request.target in self.turn_allowed_edits:
                return PermissionResult(decision=Decision.ALLOW, reason="turn_allowed")
            if request.target in self.allowed_edits:
                return PermissionResult(decision=Decision.ALLOW, reason="session_allowed")
            return None

        if request.kind == "path" and request.target in self.allowed_paths:
            return PermissionResult(decision=Decision.ALLOW, reason="session_allowed")
        if request.kind == "command" and request.target in self.allowed_commands:
            return PermissionResult(decision=Decision.ALLOW, reason="session_allowed")
        return None
