"""决策链 — 将多个 PermissionHandler 串联为责任链。

对应 TypeScript 版本中 PermissionManager 的各个 ensure* 方法，
Python 版将其解耦为独立的处理器链。
"""

from __future__ import annotations

from perm.handlers.base import (
    Decision,
    PermissionHandler,
    PermissionRequest,
    PermissionResult,
)


class PermissionChain:
    """权限决策链。

    处理器按顺序执行，第一个返回非 None 的处理器即为最终决策。
    如果所有处理器都返回 None，则默认拒绝。
    """

    def __init__(self, handlers: list[PermissionHandler] | None = None):
        self.handlers: list[PermissionHandler] = handlers or []

    def add(self, handler: PermissionHandler) -> None:
        self.handlers.append(handler)

    async def evaluate(
        self,
        request: PermissionRequest,
        store,
    ) -> PermissionResult:
        """按顺序执行处理器链。

        Args:
            request: 权限请求
            store: 权限持久化存储

        Returns:
            第一个非 None 的处理结果，或默认拒绝
        """
        for handler in self.handlers:
            try:
                result = await handler.handle(request, store)
                if result is not None:
                    return result
            except Exception:
                continue

        return PermissionResult(
            decision=Decision.DENY,
            reason="No handler matched the request",
        )
