"""压缩策略抽象基类。

所有压缩策略实现此接口，由 Pipeline 按优先级链式调用。

对应 TypeScript 版本中分散的 5 种压缩函数签名，
Python 版统一为 CompactionStrategy 协议。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from infra.types import ChatMessage

MessageList = list[ChatMessage]


@dataclass
class CompactionResult:
    """压缩策略的返回结果"""
    messages: list[ChatMessage]
    did_compact: bool
    tokens_before: int
    tokens_after: int
    kind: str  # "snip" | "micro" | "collapse" | "auto" | "manual"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_freed(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


class CompactionStrategy(ABC):
    """压缩策略抽象基类。

    子类需要提供:
      - name: 策略标识
      - threshold: 利用率触发阈值
      - apply(): 执行压缩逻辑
    """
    name: str = "base"
    threshold: float = 1.0  # 默认 > 100% 不触发

    def should_apply(self, utilization: float) -> bool:
        """判断当前利用率是否应该触发此策略。"""
        return utilization >= self.threshold

    @abstractmethod
    async def apply(
        self,
        messages: list[ChatMessage],
        model_name: str,
        model=None,  # ModelAdapter, 延迟类型引用
    ) -> CompactionResult:
        """执行压缩逻辑。

        Args:
            messages: 当前消息列表
            model_name: 模型名称（用于 token 计数）
            model: 可选的 ModelAdapter（LLM 策略需要）

        Returns:
            CompactionResult — did_compact 为 True 表示消息已变更
        """
        ...
