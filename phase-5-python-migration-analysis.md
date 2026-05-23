# 第五阶段：Python 迁移可行性分析

## 可行性结论：完全可行，且迁移后代码量可减少 40-60%

项目核心约 **8000 行 TypeScript**，迁移到 Python 后预计 **4000-5000 行**，主要原因是有成熟的 Python 生态可以直接替代大量手写代码。

---

## 一、各模块迁移对应关系

| TypeScript 模块 | 行数 | Python 替代方案 | 预计行数 | 节省 |
|---|---|---|---|---|
| `anthropic-adapter.ts` | 438 | `anthropic` 官方 SDK | ~50 | **-88%** |
| `mcp.ts` | 1277 | `mcp` 官方 Python SDK | ~200 | **-84%** |
| `tui/markdown.ts` | ~150 | `rich.Markdown` | 0（直接用） | **-100%** |
| `tui/input.ts` + `input-parser.ts` | ~400 | `prompt_toolkit` | ~80 | **-80%** |
| `tui/screen.ts` | ~150 | `rich.Console` | 0（直接用） | **-100%** |
| `utils/token-estimator.ts` | 208 | `tiktoken` | ~30 | **-85%** |
| `utils/errors.ts` | 26 | Python 内置异常 | ~10 | **-60%** |
| 自定义重试逻辑 | ~60 | `tenacity` | ~10 | **-83%** |
| Zod schema 定义 | 分散在各工具 | Pydantic `BaseModel` | 减少 ~30% | - |
| 手动 HTTP fetch | 分散 | `httpx` + SDK | 大幅减少 | - |

---

## 二、可以省略/替代的部分

### 2.1 `anthropic-adapter.ts` (438行) — 用官方 SDK 替代

这是最大的改进点。当前手写了：
- 消息格式转换（`toAnthropicMessages`，7 种消息角色逐个处理）
- HTTP 请求 + 重试（指数退避 + jitter + Retry-After 解析）
- 响应解析（text/thinking/tool_use 分块）
- 错误消息提取（`extractErrorMessage`，4 层回退）
- `<final>` / `<progress>` 标记解析（`parseAssistantText`）

Python 的 `anthropic` SDK 已内置上述大部分功能，只需一个薄适配层：

```python
import anthropic
from tenacity import retry, wait_exponential, stop_after_attempt

class AnthropicAdapter:
    def __init__(self, tools: ToolRegistry, config: RuntimeConfig):
        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.tools = tools

    @retry(wait=wait_exponential(multiplier=0.5), stop=stop_after_attempt(4))
    async def next(self, messages: list[ChatMessage]) -> AgentStep:
        response = await self.client.messages.create(
            model=self.model,
            system=build_system(messages),
            messages=to_anthropic_format(messages),
            tools=self.tools.to_anthropic_format(),
            max_tokens=self.max_tokens,
        )
        return parse_response(response)
```

**可省略的代码：**

| 函数 | 当前行数 | 替代方案 |
|------|---------|---------|
| `sleep()` | 4 | `asyncio.sleep()` — 内置 |
| `getRetryLimit()` | 5 | `tenacity.stop_after_attempt` |
| `shouldRetryStatus()` | 3 | `tenacity.retry_if_exception_type` |
| `parseRetryAfterMs()` | 12 | `tenacity.wait_exponential` |
| `getRetryDelayMs()` | 8 | `tenacity.wait_exponential` |
| `readJsonBody()` | 8 | SDK 内置 |
| `extractErrorMessage()` | 22 | SDK 内置 |
| `normalizeAnthropicUsage()` | 12 | SDK 响应直接包含 |
| `toAnthropicMessages()` | 68 | Pydantic 模型 `to_dict()` |
| `pushAnthropicMessage()` | 10 | Pydantic 分组逻辑 |

### 2.2 `mcp.ts` (1277行) — 用官方 `mcp` Python SDK 替代

官方 `mcp` Python 包已提供：
- JSON-RPC 2.0 客户端（请求/通知/响应）
- stdio transport（含 content-length 帧解析 + newline-json 帧解析）
- streamable-http transport（含鉴权、错误处理）
- 工具发现与代理
- 协议协商（auto 探测 + 缓存）

当前手写的内容：

| 组件 | 行数 | 可省略原因 |
|------|------|-----------|
| `StdioMcpClient` 类 | 386 | `mcp.client.stdio` 替代 |
| `StreamableHttpMcpClient` 类 | 189 | `mcp.client.streamable_http` 替代 |
| `handleStdoutChunk` (帧解析) | 40 | SDK 内置 |
| `handleStdoutChunkAsLines` (行解析) | 15 | SDK 内置 |
| 协议缓存逻辑 | 30 | SDK 内置 |
| `formatToolCallResult` / `formatReadResourceResult` / `formatPromptResult` | 70 | 可简化 |

### 2.3 `tui/` 整个目录 (~800行) — 用 `rich` + `prompt_toolkit` 替代

| 当前文件 | 行数 | 替代方案 |
|---------|------|---------|
| `tui/markdown.ts` | ~150 | `rich.Markdown` — 原生支持 Markdown 渲染 |
| `tui/screen.ts` | ~150 | `rich.Console` / `rich.Live` — 原生支持交替屏幕 |
| `tui/input.ts` | ~200 | `prompt_toolkit.shortcuts.PromptSession` — 原生支持 |
| `tui/input-parser.ts` | ~200 | `prompt_toolkit.key_binding` — 原生支持键盘绑定 |
| `tui/chrome.ts` | ~100 | `rich.Panel` / `rich.Layout` — 原生支持边框布局 |
| `tui/transcript.ts` | ~100 | `rich.text.Text` + 自定义渲染 |

`prompt_toolkit` 还自带了：
- **历史管理** → 替代 `history.ts` (80行)
- **自动补全** → 替代 `completeSlashCommand` (cli-commands.ts 中的部分逻辑)
- **多行编辑** → 替代当前手写的多行模式
- **剪贴板支持** → 替代 `tui/input-parser.ts` 中的剪贴板处理

### 2.4 `utils/token-estimator.ts` (208行) — 用 `tiktoken` 替代

当前用字符数/硬编码比率估算：

```typescript
// 当前实现
const CHARS_PER_TOKEN: Record<string, number> = {
    system: 3.5,
    user: 3.0,
    assistant: 3.5,
    assistant_thinking: 3.0,
    assistant_progress: 3.5,
    assistant_tool_call: 2.5,
    tool_result: 2.0,
    context_summary: 3.5,
    snip_boundary: 3.5,
}
function estimateMessageTokens(message: ChatMessage): number {
    const ratio = CHARS_PER_TOKEN[message.role] ?? 3.0
    const length = messageContentLength(message)
    return Math.ceil(length / ratio)
}
```

Python 可直接使用 `tiktoken` 获得精确计数：

```python
import tiktoken

enc = tiktoken.encoding_for_model("claude-sonnet-4-6")
tokens = len(enc.encode(content))
```

**关键改进**: Anthropic Python SDK 的响应中已包含精确的 `usage.input_tokens`。可以实现"精确已知部分 + 估算未知部分"的混合计数，准确性大幅高于纯估算。

### 2.5 重试逻辑 (分散多处) — 用 `tenacity` 统一

当前项目中有多处独立的 retry 逻辑：
- `anthropic-adapter.ts` — API 请求重试
- `mcp.ts` — MCP 协议协商重试
- `compact/auto-compact.ts` — compact 失败重试
- `compact/context-collapse.ts` — collapse 失败计数

Python 用 `tenacity` 统一：

```python
from tenacity import retry, stop_after_attempt, wait_exponential

# API 请求重试
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.5, max=8),
    retry=retry_if_result(lambda r: r.status_code in {429, 500, 502, 503})
)
async def call_model(messages): ...

# Compact 重试（带失败计数）
@retry(stop=stop_after_attempt(3), after=_disable_on_failure)
async def auto_compact(messages): ...
```

---

## 三、架构层面可以优化的设计

### 3.1 使用 Pydantic 定义所有消息类型（替代 TypeScript discriminated union）

当前 `types.ts` 的 `ChatMessage` 是 discriminated union，手写了大量类型守卫和转换逻辑。

Python 用 Pydantic 的 discriminated union：

```python
from pydantic import BaseModel, Field
from typing import Literal, Annotated, Any

class ProviderUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str = "anthropic"

class SystemMessage(BaseModel):
    role: Literal["system"]
    content: str

class UserMessage(BaseModel):
    role: Literal["user"]
    content: str

class AssistantMessage(BaseModel):
    role: Literal["assistant"]
    content: str
    provider_usage: ProviderUsage | None = None
    usage_stale: bool = False

class AssistantThinking(BaseModel):
    role: Literal["assistant_thinking"]
    blocks: list[dict[str, Any]]

class AssistantProgress(BaseModel):
    role: Literal["assistant_progress"]
    content: str
    provider_usage: ProviderUsage | None = None

class AssistantToolCall(BaseModel):
    role: Literal["assistant_tool_call"]
    tool_use_id: str
    tool_name: str
    input: Any
    provider_usage: ProviderUsage | None = None

class ToolResult(BaseModel):
    role: Literal["tool_result"]
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False

class ContextSummary(BaseModel):
    role: Literal["context_summary"]
    content: str
    compressed_count: int
    timestamp: int

class SnipBoundary(BaseModel):
    role: Literal["snip_boundary"]
    content: str
    removed_message_ids: list[str]
    removed_count: int
    tokens_freed: int
    timestamp: int

ChatMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage |
    AssistantThinking | AssistantProgress | AssistantToolCall |
    ToolResult | ContextSummary | SnipBoundary,
    Field(discriminator="role"),
]
```

**好处:**
- 自动 JSON 序列化/反序列化 → JSONL 持久化零代码
- 自动校验 → 替代 Zod schema 的手动解析
- IDE 类型提示 → 与 TypeScript 体验一致
- `model_dump()` / `model_validate()` → 替代手写的消息转换函数

### 3.2 用 `pydantic-settings` 管理配置（替代 config.ts 的手动合并）

当前 `config.ts` 手动实现了 4 层配置合并：

```
claude settings → global mcp → project mcp → mini-code settings → process.env
```

Python 用 `pydantic-settings` 声明式实现：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class McpServerConfig(BaseModel):
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}
    cwd: str | None = None
    enabled: bool = True
    protocol: Literal["auto", "content-length", "newline-json", "streamable-http"] = "auto"

class RuntimeConfig(BaseSettings):
    model: str
    base_url: str = "https://api.anthropic.com"
    api_key: str | None = None
    auth_token: str | None = None
    max_output_tokens: int | None = None

    model_config = SettingsConfigDict(
        env_prefix="MINI_CODE_",
        env_nested_delimiter="__",
        cli_parse_args=False,
    )

    @classmethod
    def load(cls) -> "RuntimeConfig":
        """合并多层配置：settings.json → .claude/settings.json → env"""
        settings = cls()
        claude = load_claude_settings()
        mini_code = load_mini_code_settings()
        return cls(
            model=mini_code.get("model") or claude.get("model") or settings.model,
            api_key=settings.api_key or mini_code.get("api_key"),
            # ...
        )
```

**可省略的代码:**
- `mergeSettings()` — 用 `|` 合并 dict
- `loadEffectiveSettings()` — 用 pydantic-settings 的 source priority
- 环境变量手动解析 → 自动绑定

### 3.3 Agent Loop 可用 async generator 简化

当前 `runAgentTurn()` (462行) 是一个大的 async 函数，内部有复杂的循环、状态管理和多个回调。Python 可以用 async generator 将其拆分为可测试的步骤：

```python
from typing import AsyncGenerator
from dataclasses import dataclass

@dataclass
class AgentEvent:
    type: Literal["compaction", "model_request", "model_response",
                  "tool_call", "tool_result", "turn_complete",
                  "max_steps", "empty_response", "error"]
    data: Any = None

async def agent_turn(
    messages: list[ChatMessage],
    model: ModelAdapter,
    tools: ToolRegistry,
    *,
    max_steps: int = 25,
) -> AsyncGenerator[AgentEvent, None]:
    """每个 yield 代表一个可观察的事件，调用方可流式消费"""
    for step in range(max_steps):
        # 压缩检查
        stats = compute_context_stats(messages, model.model_name)
        if stats.needs_compaction:
            messages = await apply_compression_pipeline(messages, model)
            yield AgentEvent(type="compaction", data=stats)

        # 调用模型
        yield AgentEvent(type="model_request")
        response = await model.next(messages)
        yield AgentEvent(type="model_response", data=response)

        # 处理文本响应
        if response.type == "assistant":
            if is_empty(response.content):
                yield AgentEvent(type="empty_response")
                if retry_count < max_empty_retries:
                    messages = append_retry_prompt(messages)
                    continue
            yield AgentEvent(type="turn_complete", data=response.content)
            return

        # 执行工具调用
        for call in response.calls:
            yield AgentEvent(type="tool_call", data=call)
            result = await tools.execute(call.name, call.input)
            yield AgentEvent(type="tool_result", data=result)

            if result.await_user:
                yield AgentEvent(type="turn_complete", data=result.output)
                return

            messages = append_tool_result(messages, call, result)

    yield AgentEvent(type="max_steps")
```

**好处:**
- 调用方可以流式消费事件（UI 实时更新）
- 更易于测试（逐个 yield 断言，不需要 mock 整个函数）
- 更易于添加中间件（在 generator 外包装：日志、监控、超时控制）
- 回调地狱消除（原来有 6 个 `on*` 回调参数）

### 3.4 压缩策略可抽象为统一的 Pipeline 接口

当前 5 种压缩策略各用不同的函数签名、不同的返回值类型：

| 策略 | 函数签名 | 返回值类型 |
|------|---------|-----------|
| snipCompact | `async (messages, contextStats, modelCtxWindow, logger?)` | `SnipCompactResult` |
| microcompact | `sync (messages, model)` | `ChatMessage[]` |
| contextCollapse | `async (messages, model, adapter, state, options?)` | `ContextCollapseResult` |
| autoCompact | `async (messages, model, adapter)` | `CompressionResult \| null` |
| manualCompact | `async (messages, adapter)` | `CompressionResult \| null` |

可以统一为：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class CompactionContext:
    utilization: float
    total_tokens: int
    effective_input: int
    model_name: str

@dataclass
class CompactionResult:
    messages: list[ChatMessage]
    did_compact: bool
    tokens_before: int
    tokens_after: int
    kind: str  # "snip" | "micro" | "collapse" | "auto" | "manual"

class CompactionStrategy(ABC):
    threshold: float = 0.0

    @abstractmethod
    async def apply(
        self,
        messages: list[ChatMessage],
        context: CompactionContext,
    ) -> CompactionResult: ...

    def should_apply(self, context: CompactionContext) -> bool:
        return context.utilization >= self.threshold


class SnipCompactStrategy(CompactionStrategy):
    threshold = 0.70

    async def apply(self, messages, context) -> CompactionResult:
        # snipCompactConversation 的完整逻辑
        ...

class MicrocompactStrategy(CompactionStrategy):
    threshold = 0.50

    async def apply(self, messages, context) -> CompactionResult:
        # microcompact 的完整逻辑
        ...

class ContextCollapseStrategy(CompactionStrategy):
    threshold = 0.75

    async def apply(self, messages, context) -> CompactionResult:
        # applyContextCollapseIfNeeded 的完整逻辑
        ...


# Pipeline 编排
PIPELINE: list[CompactionStrategy] = [
    SnipCompactStrategy(),
    MicrocompactStrategy(),
    ContextCollapseStrategy(),
]

async def apply_compression_pipeline(
    messages: list[ChatMessage],
    model: ModelAdapter,
    context: CompactionContext,
) -> list[ChatMessage]:
    for strategy in PIPELINE:
        if strategy.should_apply(context):
            result = await strategy.apply(messages, context)
            if result.did_compact:
                messages = result.messages
                context = compute_context_stats(messages, context.model_name)
    return messages
```

**好处:**
- 新增压缩策略只需实现接口，不需要修改 agent-loop
- 顺序可以通过配置调整
- 每个策略可以独立测试
- 可以按需启用/禁用特定策略

### 3.5 权限系统可引入决策链模式

当前 `permissions.ts` 的 `ensurePathAccess`/`ensureCommand`/`ensureEdit` 各自由 if-else 链实现，逻辑相似但分散。

可以抽象为责任链：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PermissionRequest:
    kind: Literal["path", "command", "edit"]
    target: str
    details: dict[str, Any]

@dataclass
class PermissionResult:
    allowed: bool
    reason: str | None = None
    feedback: str | None = None

class PermissionHandler(ABC):
    @abstractmethod
    async def handle(self, request: PermissionRequest) -> PermissionResult | None:
        """返回 None 表示无法处理，交给下一个 handler"""
        ...

class WorkspaceHandler(PermissionHandler):
    """workspace 内的路径自动通过"""
    async def handle(self, request: PermissionRequest) -> PermissionResult | None:
        if request.kind == "path" and is_within_workspace(request.target):
            return PermissionResult(allowed=True)
        return None

class SessionDenyHandler(PermissionHandler):
    """session 级拒绝列表"""
    async def handle(self, request: PermissionRequest) -> PermissionResult | None:
        if request.target in self.session_denied:
            return PermissionResult(allowed=False, reason="session_denied")
        return None

class PromptHandler(PermissionHandler):
    """弹出用户提示"""
    async def handle(self, request: PermissionRequest) -> PermissionResult | None:
        choice = await self.ui.prompt(build_prompt(request))
        return PermissionResult(
            allowed=choice in ("allow_once", "allow_always"),
            feedback=choice == "deny_with_feedback" and feedback or None,
        )

class PermissionManager:
    def __init__(self, workspace: str):
        self.chain: list[PermissionHandler] = [
            WorkspaceHandler(workspace),
            SessionDenyHandler(),
            PersistentDenyHandler(),
            SessionAllowHandler(),
            PersistentAllowHandler(),
            PromptHandler(),
        ]

    async def check(self, request: PermissionRequest) -> PermissionResult:
        for handler in self.chain:
            result = await handler.handle(request)
            if result is not None:
                return result
        return PermissionResult(allowed=False, reason="no_handler")
```

---

## 四、可以简化的部分（不改变功能）

### 4.1 消息格式转换可大幅简化

当前 `toAnthropicMessages()` (68行) 用 switch-case 逐个处理 7 种消息角色。Python 可以用 Pydantic + dispatch dict：

```python
# 每种角色对应一个转换函数，注册到 dispatch 表中
ROLE_TO_ANTHROPIC: dict[str, Callable] = {
    "system": lambda m: None,  # 单独提取为 system prompt
    "user": lambda m: {"role": "user", "content": m.content},
    "assistant": lambda m: {"role": "assistant", "content": m.content},
    "assistant_progress": lambda m: {
        "role": "assistant",
        "content": f"<progress>\n{m.content}\n</progress>",
    },
    "assistant_tool_call": lambda m: {
        "type": "tool_use",
        "id": m.tool_use_id,
        "name": m.tool_name,
        "input": m.input,
    },
    "tool_result": lambda m: {
        "type": "tool_result",
        "tool_use_id": m.tool_use_id,
        "content": m.content,
        "is_error": m.is_error,
    },
    "context_summary": lambda m: {
        "role": "user",
        "content": f"[Context Summary from earlier conversation]\n{m.content}",
    },
    "snip_boundary": lambda m: {
        "role": "user",
        "content": build_snip_boundary_text(),
    },
}

def to_anthropic_messages(messages: list[ChatMessage]) -> dict:
    system_parts = []
    api_messages = []
    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
            continue
        converter = ROLE_TO_ANTHROPIC.get(msg.role)
        if converter:
            converted = converter(msg)
            if converted:
                api_messages.append(converted)
    return {"system": "\n\n".join(system_parts), "messages": api_messages}
```

### 4.2 `file-review.ts` (51行) 可合并到 tools 中

当前 `applyReviewedFileChange` 只是一个 diff 展示 + 权限检查 + 写入的包装。在 Python 中 `rich.Syntax` 可以原生展示带高亮的 diff，不需要单独模块。

```python
from rich.syntax import Syntax
from rich.console import Console

async def apply_reviewed_change(path: str, original: str, modified: str) -> str:
    diff = generate_diff(original, modified)
    console.print(Syntax(diff, "diff", theme="monokai"))
    await permissions.ensure_edit(path, diff)
    await write_file(path, modified)
    return f"Applied changes to {path}"
```

### 4.3 `background-tasks.ts` (71行) 可简化

Python 的 `asyncio` 可以天然管理后台进程：

```python
async def run_background_command(command: str, cwd: str) -> BackgroundTask:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    task_id = f"shell_{int(time.time())}_{random_hex(6)}"
    return BackgroundTask(
        task_id=task_id,
        command=command,
        pid=process.pid,
        process=process,  # 保留引用以获取输出
    )
```

不需要手动维护 PID Map + `process.kill(pid, 0)` 探活。

### 4.4 斜杠命令可改为插件注册模式

当前 `tryHandleLocalCommand()` 是一个大的 if-else 链（18 个分支）：

```typescript
if (input === '/help') return formatSlashCommands()
if (input === '/config-paths') return [...] 
if (input === '/permissions') return ...
if (input === '/skills') return ...
if (input === '/mcp') return ...
if (input === '/status') return ...
if (input === '/model') return ...
if (input.startsWith('/model ')) return ...
return null
```

Python 可以用装饰器注册：

```python
slash_commands: dict[str, SlashCommand] = {}

@dataclass
class SlashCommand:
    name: str
    usage: str
    description: str
    handler: Callable

def register_slash(name: str, usage: str, description: str):
    def decorator(func):
        slash_commands[name] = SlashCommand(
            name=name, usage=usage,
            description=description, handler=func,
        )
        return func
    return decorator

@register_slash("/help", "/help", "Show available slash commands")
async def cmd_help(args: str, ctx: CommandContext) -> str:
    return format_help()

@register_slash("/model", "/model [name]", "Show or set the current model")
async def cmd_model(args: str, ctx: CommandContext) -> str:
    if args.strip():
        await save_model_config(args.strip())
        return f"Model set to {args}"
    return f"Current model: {ctx.config.model}"

@register_slash("/mcp", "/mcp", "Show MCP server status")
async def cmd_mcp(args: str, ctx: CommandContext) -> str:
    servers = ctx.tools.get_mcp_servers()
    return format_mcp_status(servers)

async def handle_slash_command(input: str, ctx: CommandContext) -> str | None:
    parts = input.split(maxsplit=1)
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    command = slash_commands.get(name)
    if command:
        return await command.handler(args, ctx)
    return None
```

**好处:**
- 新命令只需写一个函数 + 装饰器，不修改分发逻辑
- 命令帮助自动生成
- 每个命令可独立测试

---

## 五、推荐的 Python 技术栈

| 类别 | 推荐库 | 替代当前 |
|------|--------|---------|
| LLM 调用 | `anthropic` (官方 SDK) | `anthropic-adapter.ts` |
| MCP 协议 | `mcp` (官方 Python SDK) | `mcp.ts` |
| 终端 UI | `rich` | `tui/` + `ui.ts` |
| 终端输入 | `prompt_toolkit` | `tui/input*` + `history.ts` |
| 数据模型 | `pydantic` | `types.ts` + Zod schema |
| 配置管理 | `pydantic-settings` | `config.ts` |
| Token 计数 | `tiktoken` | `utils/token-estimator.ts` |
| 重试 | `tenacity` | 分散的重试逻辑 |
| HTTP (如需要) | `httpx` | 手动 fetch |
| 进程管理 | `asyncio.subprocess` | `child_process` |
| 异步 | `asyncio` (内置) | Promise-based |
| 测试 | `pytest` + `pytest-asyncio` | 当前无测试 |

---

## 六、迁移风险与注意事项

### 6.1 高风险项

| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| TTY raw mode 行为差异 | Windows Python 的 termios 兼容性不如 Node.js | 优先在 Unix 环境开发，Windows 用 `prompt_toolkit` 的跨平台支持 |
| asyncio 子进程语义差异 | `asyncio.subprocess` 与 `child_process` 的 API 设计哲学不同 | MCP stdio 客户端需要重新设计流处理 |
| Anthropic SDK 响应格式不同 | Python SDK 的响应对象结构与当前手写解析不同 | 提取 `parse_response()` 为独立函数，可切换解析逻辑 |

### 6.2 中风险项

| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| `prompt_toolkit` 的自定义程度 | 当前 TTY UI 高度定制，`prompt_toolkit` 可能需要大量配置 | 先做 TTY 最小原型验证可行性 |
| 性能差异 | Python asyncio 在高并发 I/O 场景下可能不如 Node.js | 当前是单 Agent Loop，无高并发需求，影响不大 |
| 包依赖管理 | Python 依赖管理不如 npm 统一（pip/poetry/uv） | 推荐使用 `uv` 管理依赖 |

### 6.3 低风险项

- JSON/JSONL 文件格式：Python 的 `json` 模块直接兼容
- 正则表达式：语法 99% 兼容
- 环境变量：`os.environ` 等价 `process.env`
- 文件路径：`pathlib` 比 `path` 模块更强大

---

## 七、推荐迁移里程碑

### 里程碑 1：最小可行 Agent Loop（~300 行 Python）

**目标**: 验证 "LLM 推理 → 工具调用 → 结果反馈" 闭环

**包含**:
- Pydantic 消息模型
- Anthropic SDK 适配器（薄封装）
- ToolRegistry（只含 `read_file` + `run_command` 两个工具）
- 简单的命令行输入循环（无 TTY）

**不含**: 压缩、MCP、权限、会话、TTY

### 里程碑 2：完整功能迁移（~2500 行 Python）

**新增**:
- 全部 12 个内置工具
- 权限系统（决策链模式）
- 会话持久化
- 压缩 Pipeline（含全部 5 种策略）
- MCP 集成（用官方 SDK）

### 里程碑 3：TTY 体验迁移（~1500 行 Python）

**新增**:
- `rich` + `prompt_toolkit` TTY 界面
- 斜杠命令插件系统
- 转录渲染
- 权限提示 UI

### 里程碑 4：打磨与优化

- 测试覆盖
- 结构化日志
- 性能优化
- 文档

---

## 八、总结

| 维度 | 评估 |
|------|------|
| **可行性** | 完全可行，无硬阻塞 |
| **代码量预估** | 8000行 TS → 4000-5000行 Python（**-40%~-60%**） |
| **最大收益来源** | 官方 Anthropic SDK + MCP SDK + rich + prompt_toolkit |
| **节省最多** | `anthropic-adapter.ts` (-88%)、`mcp.ts` (-84%)、`tui/` (-75%)、`token-estimator` (-85%) |
| **架构收益** | Pydantic 类型系统、统一压缩管道、async generator、插件化命令、责任链权限 |
| **核心风险** | TTY 跨平台兼容性、asyncio 子进程语义差异 |
| **建议策略** | 4 个里程碑渐进迁移，先在 Unix 环境做 PoC |
