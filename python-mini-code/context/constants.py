"""压缩策略阈值与限制常量。

对应 TypeScript 版本的 compact/constants.ts。
"""

# ---- 各策略触发阈值 ----
SNIP_COMPACT_THRESHOLD = 0.70      # SnipCompact: 利用率 > 70% 触发
MICROCOMPACT_THRESHOLD = 0.50      # Microcompact: 利用率 > 50% 触发
CONTEXT_COLLAPSE_THRESHOLD = 0.75  # ContextCollapse: 利用率 > 75% 触发
AUTOCOMPACT_THRESHOLD = 0.85       # AutoCompact: 利用率 > 85% 触发

# ---- SnipCompact ----
SNIP_TARGET_USAGE = 0.60
SNIP_MIN_MESSAGES_TO_REMOVE = 6
SNIP_KEEP_RECENT_MESSAGES = 12
SNIP_MIN_TOKENS_TO_FREE = 2_000

# ---- Microcompact ----
KEEP_RECENT_TOOL_RESULTS = 3

# ---- ContextCollapse ----
COLLAPSE_TARGET_USAGE = 0.65
COLLAPSE_KEEP_RECENT_MESSAGES = 12
COLLAPSE_MIN_TOKENS_TO_SAVE = 2_000
COLLAPSE_MAX_SPANS_PER_PASS = 2
COLLAPSE_MAX_FAILURES = 3

# ---- 保留策略 ----
MIN_KEEP_MESSAGES = 6
MIN_KEEP_TOKENS = 10_000
MAX_KEEP_TOKENS = 40_000

# ---- 降级限制 ----
MAX_COMPACTION_FAILURES = 3     # 连续失败超过此次数后禁用该策略
SUMMARY_MAX_OUTPUT_TOKENS = 4096
MIN_EFFECTIVE_INPUT_FOR_AUTOCOMPACT = 20_000

# ---- 可压缩工具（Microcompact 目标）----
COMPACTABLE_TOOLS = frozenset({
    "read_file",
    "run_command",
    "grep_files",
    "list_files",
    "web_fetch",
})

# ---- 受保护的工具（SnipCompact 不可删除其附近消息）----
PROTECTED_TOOL_PATTERNS = frozenset({
    "edit_file",
    "modify_file",
    "patch_file",
    "write_file",
    "apply_patch",
})

# ---- 占位标记 ----
CLEAR_MARKER = "[Output cleared for context space]"
