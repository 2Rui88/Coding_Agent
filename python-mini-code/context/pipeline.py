"""压缩 Pipeline — 按优先级链式执行压缩策略。

编排规则：
  1. 按注册顺序依次检查各策略是否触发
  2. 触发则执行，执行后重新计算利用率
  3. 每个策略独立失败，不中断后续策略
  4. 所有策略执行完成后返回最终消息列表
"""

from __future__ import annotations

from context.strategy import CompactionResult, CompactionStrategy
from infra.tokens.counter import compute_context_stats
from infra.types import ChatMessage


class CompactionPipeline:
    """压缩策略链。

    用法:
        pipeline = CompactionPipeline([
            SnipCompactStrategy(),
            MicrocompactStrategy(),
            ContextCollapseStrategy(),
        ])
        messages = await pipeline.apply(messages, model, model_name)
    """

    def __init__(self, strategies: list[CompactionStrategy] | None = None):
        self.strategies: list[CompactionStrategy] = strategies or []

    def add(self, strategy: CompactionStrategy) -> None:
        self.strategies.append(strategy)

    async def apply(
        self,
        messages: list[ChatMessage],
        model_name: str,
        model=None,
    ) -> list[ChatMessage]:
        """按优先级链式执行压缩。

        Args:
            messages: 当前消息列表
            model_name: 模型名称
            model: 可选的 ModelAdapter（LLM 策略需要）

        Returns:
            压缩后的消息列表
        """
        current = messages

        for strategy in self.strategies:
            stats = compute_context_stats(current, model_name)
            utilization = stats["utilization"]

            if not strategy.should_apply(utilization):
                continue

            try:
                result = await strategy.apply(current, model_name, model)
                if result.did_compact:
                    current = result.messages
            except Exception:
                # 单个策略失败不影响后续
                continue

        return current


def create_default_pipeline() -> CompactionPipeline:
    """创建默认的 4 层压缩 Pipeline。

    顺序: SnipCompact → Microcompact → ContextCollapse → AutoCompact
    """
    from context.auto import AutoCompactStrategy
    from context.collapse import ContextCollapseStrategy
    from context.micro import MicrocompactStrategy
    from context.snip import SnipCompactStrategy

    return CompactionPipeline([
        SnipCompactStrategy(),
        MicrocompactStrategy(),
        ContextCollapseStrategy(),
        AutoCompactStrategy(),
    ])
