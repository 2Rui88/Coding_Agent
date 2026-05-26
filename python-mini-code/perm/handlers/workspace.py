"""Workspace 豁免处理器 — workspace 内的路径自动放行。"""

from pathlib import Path

from perm.handlers.base import Decision, PermissionHandler, PermissionRequest, PermissionResult


class WorkspaceHandler(PermissionHandler):
    """工作区内的操作自动通过，无需用户审批。"""

    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root).resolve()

    async def handle(self, request, store) -> PermissionResult | None:
        if request.kind != "path":
            return None

        target = Path(request.target).resolve()
        try:
            target.relative_to(self.root)
            return PermissionResult(decision=Decision.ALLOW, reason="within_workspace")
        except ValueError:
            return None
