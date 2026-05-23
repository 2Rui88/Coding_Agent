"""
精确 Token 计数器 — 使用 tiktoken 替代字符数估算。

混合策略：
  1. 从最近一条带 provider_usage 的 assistant 消息获取精确 token 数（已知部分）
  2. 尾部未知消息用 tiktoken 精确编码计数
  3. 首部 system 消息用 tiktoken 编码

相比 TypeScript 版的大幅改进：
  - 不再使用 CHARS_PER_TOKEN 启发式比率（中文误差可达 50%）
  - API 返回的 usage 直接复用，不重新估算
  - 上下文窗口配置集中管理，新增模型只需添加一行
"""

from __future__ import annotations

from typing import Any

import tiktoken

from infra.types import (
    AssistantMessage,
    AssistantProgress,
    AssistantToolCall,
    ChatMessage,
    MessageList,
)

# ---------------------------------------------------------------------------
# 模型上下文窗口规则
# ---------------------------------------------------------------------------

_MODEL_WINDOWS: dict[str, tuple[int, int]] = {
    # (context_window, output_reserve)
    "claude-opus-4-6": (200_000, 16_000),
    "claude-sonnet-4-6": (200_000, 16_000),
    "claude-haiku-4-5": (200_000, 16_000),
    "claude-opus-4-1": (200_000, 16_000),
    "claude-opus-4": (200_000, 16_000),
    "claude-sonnet-4": (200_000, 16_000),
    "claude-3-7-sonnet": (200_000, 8_192),
    "claude-3-5-sonnet": (200_000, 8_192),
    "claude-3-5-haiku": (200_000, 8_192),
    "claude-3-opus": (200_000, 4_096),
    "claude-3-haiku": (200_000, 4_096),
    "gpt-5": (128_000, 16_000),
    "gpt-5-codex": (128_000, 16_000),
    "gpt-5.4": (128_000, 16_000),
    "gpt-5.2": (128_000, 16_000),
    "gpt-5.1": (128_000, 16_000),
    "o4-mini": (200_000, 16_000),
    "o3": (200_000, 16_000),
    "o1": (200_000, 16_000),
    "gpt-4.1": (1_047_576, 16_000),
    "gpt-4.1-mini": (1_047_576, 16_000),
    "gpt-4o": (128_000, 16_384),
    "gpt-4o-mini": (128_000, 16_384),
    "gemini-2.5-pro": (1_048_576, 16_000),
    "gemini-2.5-flash": (1_048_576, 16_000),
    "deepseek-reasoner": (128_000, 16_000),
    "deepseek-chat": (128_000, 4_000),
}

_DEFAULT_WINDOW = (128_000, 8_000)

# ---------------------------------------------------------------------------
# 编码器缓存
# ---------------------------------------------------------------------------

_encoder_cache: dict[str, tiktoken.Encoding] = {}


def _get_encoder(model: str) -> tiktoken.Encoding:
    """获取模型的 tiktoken 编码器（带缓存）。

    优先使用对应模型的编码器，回退到 cl100k_base（GPT-4 编码）。
    """
    key = model.lower()
    if key not in _encoder_cache:
        try:
            _encoder_cache[key] = tiktoken.encoding_for_model(model)
        except KeyError:
            _encoder_cache[key] = tiktoken.get_encoding("cl100k_base")
    return _encoder_cache[key]


# ---------------------------------------------------------------------------
# 上下文窗口
# ---------------------------------------------------------------------------

def get_context_window(model: str) -> tuple[int, int, int]:
    """返回 (context_window, output_reserve, effective_input)。

    effective_input = context_window - output_reserve
    """
    key = model.lower()
    for pattern, (window, reserve) in _MODEL_WINDOWS.items():
        if pattern in key:
            return (window, reserve, window - reserve)
    w, r = _DEFAULT_WINDOW
    return (w, r, w - r)


# ---------------------------------------------------------------------------
# Token 计数
# ---------------------------------------------------------------------------

def _message_to_text(msg: ChatMessage) -> str | None:
    """将消息转为用于 token 计数的文本。"""
    role = msg.role
    if role in ("system", "user", "assistant", "assistant_progress"):
        return msg.content
    if role == "assistant_thinking":
        import json
        return json.dumps(msg.blocks, ensure_ascii=False)
    if role == "assistant_tool_call":
        import json
        return json.dumps(msg.input, ensure_ascii=False)
    if role in ("tool_result", "context_summary", "snip_boundary"):
        return msg.content
    return None


def count_tokens(message: ChatMessage, encoder: tiktoken.Encoding) -> int:
    """对单条消息做精确 token 计数。"""
    text = _message_to_text(message)
    if text is None:
        return 0
    return len(encoder.encode(text))


def estimate_tokens(messages: list[ChatMessage], model: str) -> int:
    """批量估算消息的 token 数（纯 tiktoken，无 provider usage 辅助）。"""
    encoder = _get_encoder(model)
    total = 0
    for msg in messages:
        total += count_tokens(msg, encoder)
    return total


# ---------------------------------------------------------------------------
# 混合计数（provider usage + tiktoken）
# ---------------------------------------------------------------------------

def _has_valid_usage(msg: ChatMessage) -> bool:
    """检查消息是否携带有效且未过期的 provider usage。"""
    if isinstance(msg, (AssistantMessage, AssistantProgress, AssistantToolCall)):
        return msg.provider_usage is not None and not msg.usage_stale
    return False


def token_count_with_estimation(
    messages: list[ChatMessage], model: str
) -> dict[str, Any]:
    """混合计数：优先使用 provider usage，尾部用 tiktoken 估算。

    从消息列表末尾向前扫描，找到最后一个携带有效 provider usage 的消息，
    其 total_tokens 作为"已知精确值"，尾部消息用 tiktoken 补齐。

    Returns:
        {
            "total_tokens": int,
            "provider_usage_tokens": int,
            "estimated_tokens": int,
            "source": "provider_usage" | "provider_usage_plus_estimate" | "estimate_only",
            "is_exact": bool,
        }
    """
    encoder = _get_encoder(model)

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if not _has_valid_usage(msg):
            continue

        usage = msg.provider_usage  # type: ignore
        assert usage is not None

        tail_messages = messages[i + 1:]
        tail_estimate = estimate_tokens(tail_messages, model)

        return {
            "total_tokens": usage.total_tokens + tail_estimate,
            "provider_usage_tokens": usage.total_tokens,
            "estimated_tokens": tail_estimate,
            "source": "provider_usage_plus_estimate" if tail_estimate > 0 else "provider_usage",
            "is_exact": tail_estimate == 0,
        }

    # 没有找到任何 provider usage，全部估算
    total = 0
    for msg in messages:
        total += count_tokens(msg, encoder)

    return {
        "total_tokens": total,
        "provider_usage_tokens": 0,
        "estimated_tokens": total,
        "source": "estimate_only",
        "is_exact": False,
    }


# ---------------------------------------------------------------------------
# 上下文统计
# ---------------------------------------------------------------------------

def compute_context_stats(
    messages: list[ChatMessage],
    model: str,
) -> dict[str, Any]:
    """计算完整的上下文统计信息。

    Returns:
        {
            "estimated_tokens": int,
            "total_tokens": int,
            "provider_usage_tokens": int,
            "context_window": int,
            "effective_input": int,
            "utilization": float,       # 0.0 ~ 1.0+
            "warning_level": str,       # normal | warning | critical | blocked
            "accounting": dict,         # 来自 token_count_with_estimation
            "output_reserve": int,
        }
    """
    context_window, output_reserve, effective_input = get_context_window(model)
    accounting = token_count_with_estimation(messages, model)
    utilization = min(
        2.0,
        accounting["total_tokens"] / effective_input if effective_input > 0 else 0.0,
    )

    if utilization >= 0.95:
        warning_level = "blocked"
    elif utilization >= 0.85:
        warning_level = "critical"
    elif utilization >= 0.50:
        warning_level = "warning"
    else:
        warning_level = "normal"

    return {
        "estimated_tokens": accounting["estimated_tokens"],
        "total_tokens": accounting["total_tokens"],
        "provider_usage_tokens": accounting["provider_usage_tokens"],
        "context_window": context_window,
        "effective_input": effective_input,
        "output_reserve": output_reserve,
        "utilization": utilization,
        "warning_level": warning_level,
        "accounting": accounting,
    }


# ---------------------------------------------------------------------------
# Provider usage 标记
# ---------------------------------------------------------------------------

def mark_provider_usage_stale(msg: ChatMessage, reason: str) -> ChatMessage:
    """标记某条消息的 provider usage 为过期。

    当上下文被压缩后，provider usage 不再准确，需要标记。
    """
    if isinstance(msg, (AssistantMessage, AssistantProgress, AssistantToolCall)):
        if msg.provider_usage is not None:
            return msg.model_copy(update={
                "usage_stale": True,
                "usage_stale_reason": reason,
            })
    return msg
