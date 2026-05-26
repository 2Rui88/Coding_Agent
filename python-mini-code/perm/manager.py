"""PermissionManager — 权限系统的公共 API。

将权限检查统一为三个入口:
  - ensure_path_access(target, intent)
  - ensure_command(command, args, cwd)
  - ensure_edit(target_path, diff_preview)

内部使用决策链模式串联各处理器。

对应 TypeScript 版本 permissions.ts 的 PermissionManager 类。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Awaitable

from perm.chain import PermissionChain
from perm.classifier import classify_dangerous
from perm.handlers.base import (
    Decision,
    PermissionHandler,
    PermissionRequest,
    PermissionResult,
)
from perm.handlers.persist import PersistAllowHandler, PersistDenyHandler
from perm.handlers.session_allow import SessionAllowHandler
from perm.handlers.session_deny import SessionDenyHandler
from perm.handlers.workspace import WorkspaceHandler
from perm.store import (
    PermissionStore,
    read_permission_store,
    write_permission_store,
)

# 回调类型：UI 层实现此函数以弹出审批交互
PromptCallback = Callable[
    [PermissionRequest], Awaitable[PermissionResult]
]


class PermissionManager:
    """权限管理器 — 路径/命令/编辑三级安全沙箱。

    仓库根路径内的操作自动通过，超出范围的触发决策链审批。
    """

    def __init__(
        self,
        workspace_root: str,
        prompt: PromptCallback | None = None,
    ):
        self.workspace_root = str(Path(workspace_root).resolve())
        self.prompt = prompt

        # Session 级处理器（每次会话重置）
        self._session_deny = SessionDenyHandler()
        self._session_allow = SessionAllowHandler()

        # 决策链（按优先级排列）
        self._chain = PermissionChain([
            WorkspaceHandler(self.workspace_root),
            self._session_deny,
            PersistDenyHandler(),
            self._session_allow,
            PersistAllowHandler(),
        ])

        self._store: PermissionStore | None = None
        self._ready = False

    async def _init(self) -> None:
        if self._ready:
            return
        self._store = await read_permission_store()
        self._ready = True

    # ---- Turn 生命周期 ----

    def begin_turn(self) -> None:
        self._session_allow.begin_turn()

    def end_turn(self) -> None:
        pass

    # ---- 路径权限 ----

    async def ensure_path_access(self, target: str, intent: str = "read") -> None:
        """确保有权限访问指定路径。

        Raises:
            PermissionError: 权限被拒绝
        """
        await self._init()

        normalized = str(Path(target).resolve())

        # workspace 内直接放行
        try:
            Path(normalized).relative_to(Path(self.workspace_root))
            return
        except ValueError:
            pass

        # 决策链评估
        request = PermissionRequest(
            kind="path",
            target=normalized,
            intent=intent,
            details={"workspace": self.workspace_root},
        )
        result = await self._chain.evaluate(request, self._store)

        if result.decision == Decision.ALLOW:
            self._session_allow.add_allow("path", normalized)
            return

        # 需要用户审批
        if self.prompt is not None:
            user_result = await self.prompt(request)
            if user_result.decision == Decision.ALLOW:
                self._apply_user_allow(request, user_result)
                return
            self._apply_user_deny(request, user_result)

        raise PermissionError(
            f"Access denied for path outside cwd: {target}"
        )

    # ---- 命令权限 ----

    async def ensure_command(
        self, command: str, args: list[str], command_cwd: str
    ) -> None:
        """确保有权限执行指定命令。

        非危险命令直接放行，危险命令触发审批。

        Raises:
            PermissionError: 权限被拒绝
        """
        await self._init()

        # 先确保 cwd 可访问
        await self.ensure_path_access(command_cwd, "search")

        signature = " ".join([command] + args).strip()
        danger_reason = classify_dangerous(command, args)

        if danger_reason is None:
            return  # 非危险命令直接放行

        # 决策链评估
        request = PermissionRequest(
            kind="command",
            target=signature,
            details={"command": command, "args": args, "reason": danger_reason, "cwd": command_cwd},
        )
        result = await self._chain.evaluate(request, self._store)

        if result.decision == Decision.ALLOW:
            self._session_allow.add_allow("command", signature)
            return

        if self.prompt is not None:
            user_result = await self.prompt(request)
            if user_result.decision == Decision.ALLOW:
                self._apply_user_allow(request, user_result)
                return
            self._apply_user_deny(request, user_result)

        raise PermissionError(f"Command denied: {signature}")

    # ---- 编辑权限 ----

    async def ensure_edit(self, target_path: str, diff_preview: str) -> None:
        """确保有权限修改指定文件。

        Raises:
            PermissionError: 权限被拒绝
        """
        await self._init()

        normalized = str(Path(target_path).resolve())

        request = PermissionRequest(
            kind="edit",
            target=normalized,
            details={"diff": diff_preview},
        )
        result = await self._chain.evaluate(request, self._store)

        if result.decision == Decision.ALLOW:
            self._session_allow.add_allow("edit", normalized)
            return

        if self.prompt is not None:
            user_result = await self.prompt(request)
            if user_result.decision == Decision.ALLOW:
                self._apply_user_allow(request, user_result)
                return
            self._apply_user_deny(request, user_result)

        raise PermissionError(f"Edit denied: {target_path}")

    # ---- 持久化 ----

    async def _apply_user_allow(
        self, request: PermissionRequest, result: PermissionResult
    ) -> None:
        """用户批准后更新状态。"""
        if request.kind == "path":
            self._session_allow.add_allow("path", request.target)
        elif request.kind == "command":
            self._session_allow.add_allow("command", request.target)
        elif request.kind == "edit":
            if result.reason == "allow_turn":
                self._session_allow.add_turn_allow(request.target)
            elif result.reason == "allow_all_turn":
                self._session_allow.turn_allow_all_edits = True
            elif result.reason == "allow_always":
                self._session_allow.add_allow("edit", request.target)
                assert self._store is not None
                self._store.allowed_edits.add(request.target)
                await write_permission_store(self._store)
            else:
                self._session_allow.add_allow("edit", request.target)

    async def _apply_user_deny(
        self, request: PermissionRequest, result: PermissionResult
    ) -> None:
        """用户拒绝后更新状态。"""
        if request.kind == "path":
            self._session_deny.add_deny("path", request.target)
        elif request.kind == "command":
            self._session_deny.add_deny("command", request.target)
        elif request.kind == "edit":
            self._session_deny.add_deny("edit", request.target)
            if result.reason == "deny_always":
                assert self._store is not None
                self._store.denied_edits.add(request.target)
                await write_permission_store(self._store)


class PermissionError(Exception):
    """权限拒绝异常。"""
    pass
