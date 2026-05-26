"""权限处理器抽象基类。

每个处理器负责一个维度的权限决策。
返回 PermissionResult 表示决策完成，返回 None 表示交给下一个处理器。

对应 TypeScript 版 permissions.ts 中 if-else 链的每个 if 分支。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PermissionRequest:
    kind: str  # "path" | "command" | "edit"
    target: str
    intent: str = "read"  # "read" | "write" | "list" | "search"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionResult:
    decision: Decision
    reason: str | None = None
    feedback: str | None = None


class PermissionHandler(ABC):
    """权限处理器抽象基类。

    handle() 返回 PermissionResult 表示决策完成，
    返回 None 表示无法决策，交给链中的下一个处理器。
    """

    @abstractmethod
    async def handle(
        self,
        request: PermissionRequest,
        store: "PermissionStore",  # type: ignore
    ) -> PermissionResult | None:
        ...
