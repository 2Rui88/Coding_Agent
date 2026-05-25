"""Agent 事件类型 — Async Generator 产出的事件定义。

每个 yield 对应一个可观察的 Agent 内部状态变化。
UI 层通过 async for 消费事件流，不感知 Agent 内部细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.types import ChatMessage, ProviderUsage


@dataclass
class AgentEvent:
    """Agent 事件的基类型。type 字段用于消费方的 match 分发。"""
    type: str
    data: Any = None


@dataclass
class TurnStart(AgentEvent):
    type: str = "turn_start"
    step: int = 0


@dataclass
class ModelRequest(AgentEvent):
    type: str = "model_request"


@dataclass
class ModelResponse(AgentEvent):
    type: str = "model_response"
    content: str = ""
    kind: str = "final"  # final | progress
    thinking_blocks: list[dict] = field(default_factory=list)
    diagnostics: dict | None = None
    usage: ProviderUsage | None = None


@dataclass
class ToolCallEvent(AgentEvent):
    type: str = "tool_calls"
    calls: list[dict] = field(default_factory=list)


@dataclass
class ToolResultEvent(AgentEvent):
    type: str = "tool_result"
    call_id: str = ""
    tool_name: str = ""
    output: str = ""
    is_error: bool = False
    await_user: bool = False


@dataclass
class TurnComplete(AgentEvent):
    type: str = "turn_complete"
    messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class MaxStepsReached(AgentEvent):
    type: str = "max_steps"
    messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class EmptyResponseRetry(AgentEvent):
    type: str = "empty_response_retry"
    attempt: int = 0


@dataclass
class ThinkingRecovery(AgentEvent):
    type: str = "thinking_recovery"
    stop_reason: str = ""
    attempt: int = 0


@dataclass
class CompactionEvent(AgentEvent):
    type: str = "compaction"
    kind: str = ""  # "snip" | "micro" | "collapse" | "auto"
    data: dict = field(default_factory=dict)
