"""
Pydantic 消息模型 — 使用 discriminated union 替代 TypeScript 的 union 类型。
每种消息角色对应一个模型，通过 role 字段自动分发。
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 辅助类型
# ---------------------------------------------------------------------------

class ProviderUsage(BaseModel):
    """API 返回的 token 使用量"""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str = "anthropic"


# ---------------------------------------------------------------------------
# 消息角色
# ---------------------------------------------------------------------------

class SystemMessage(BaseModel):
    role: Literal["system"]
    content: str
    id: str = Field(default_factory=lambda: str(uuid4()))


class UserMessage(BaseModel):
    role: Literal["user"]
    content: str
    id: str = Field(default_factory=lambda: str(uuid4()))


class AssistantMessage(BaseModel):
    role: Literal["assistant"]
    content: str
    provider_usage: ProviderUsage | None = None
    usage_stale: bool = False
    usage_stale_reason: str | None = None
    id: str = Field(default_factory=lambda: str(uuid4()))


class AssistantThinking(BaseModel):
    role: Literal["assistant_thinking"]
    blocks: list[dict[str, Any]]
    id: str = Field(default_factory=lambda: str(uuid4()))


class AssistantProgress(BaseModel):
    role: Literal["assistant_progress"]
    content: str
    provider_usage: ProviderUsage | None = None
    id: str = Field(default_factory=lambda: str(uuid4()))


class AssistantToolCall(BaseModel):
    role: Literal["assistant_tool_call"]
    tool_use_id: str
    tool_name: str
    input: Any
    provider_usage: ProviderUsage | None = None
    usage_stale: bool = False
    usage_stale_reason: str | None = None
    id: str = Field(default_factory=lambda: str(uuid4()))


class ToolResultMessage(BaseModel):
    role: Literal["tool_result"]
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False
    id: str = Field(default_factory=lambda: str(uuid4()))


class ContextSummary(BaseModel):
    role: Literal["context_summary"]
    content: str
    compressed_count: int
    timestamp: int  # epoch ms
    id: str = Field(default_factory=lambda: str(uuid4()))


class SnipBoundary(BaseModel):
    role: Literal["snip_boundary"]
    content: str
    removed_message_ids: list[str]
    removed_count: int
    tokens_freed: int
    timestamp: int  # epoch ms
    id: str = Field(default_factory=lambda: str(uuid4()))


# ---------------------------------------------------------------------------
# Discriminated Union
# ---------------------------------------------------------------------------

ChatMessage = Annotated[
    SystemMessage
    | UserMessage
    | AssistantMessage
    | AssistantThinking
    | AssistantProgress
    | AssistantToolCall
    | ToolResultMessage
    | ContextSummary
    | SnipBoundary,
    Field(discriminator="role"),
]

MessageList = list[ChatMessage]

# ---------------------------------------------------------------------------
# Agent 相关类型
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    id: str
    tool_name: str
    input: Any


class StepDiagnostics(BaseModel):
    stop_reason: str | None = None
    block_types: list[str] = Field(default_factory=list)
    ignored_block_types: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    """模型返回的一次推理结果"""
    type: Literal["assistant", "tool_calls"]
    content: str = ""
    kind: Literal["final", "progress"] | None = None
    calls: list[ToolCall] = Field(default_factory=list)
    thinking_blocks: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: StepDiagnostics | None = None
    usage: ProviderUsage | None = None


class ToolResult(BaseModel):
    """工具执行结果"""
    ok: bool
    output: str
    await_user: bool = False


class ToolContext(BaseModel):
    """工具执行上下文"""
    cwd: str
    permissions: Any = None  # PermissionManager, 延迟导入避免循环依赖

    model_config = {"arbitrary_types_allowed": True}
