# Python 版 Coding_Agent 架构设计

## 一、整体架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                        入口层 (Entry)                        │
│  main.py — 参数解析、模式分发、信号处理                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                      交互层 (Interface)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  tty/ 模块    │  │  pipe/ 模块   │  │  http/ 模块(未来) │   │
│  │  (rich +      │  │  (readline   │  │  (FastAPI SSE)   │   │
│  │  prompt_tk)   │  │  管道模式)    │  │  Web 模式)       │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                      核心层 (Core)                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Agent Loop (agent/)                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ 调度器    │  │ 重试策略  │  │ 事件总线(AsyncGen)│   │   │
│  │  │ Scheduler │  │ Retry    │  │ EventBus         │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           上下文管理 Pipeline (context/)               │   │
│  │  SnipCompact → Microcompact → ContextCollapse        │   │
│  │       (统一 CompactionStrategy 接口)                    │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                      服务层 (Services)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 模型服务  │ │ 工具服务  │ │ 权限服务  │ │ 会话服务      │   │
│  │ model/   │ │ tools/   │ │ perm/    │ │ session/     │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ 配置服务  │ │ MCP服务  │ │ 技能服务  │                    │
│  │ config/  │ │ mcp/     │ │ skills/  │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                     基础设施层 (Infra)                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 消息模型  │ │ Token计数│ │ 日志系统  │ │ 持久化存储    │   │
│  │ types.py │ │ tokens/  │ │ log/     │ │ storage/     │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、功能模块详解

### 2.1 入口层 — `main.py`

**职责**: 应用生命周期管理，不包含业务逻辑。

```
main()
  ├── 参数解析 (argparse)
  │     --resume [id|picker]  恢复会话
  │     --fork <id>           分支会话
  │     --model <name>        指定模型
  │     --mock                使用 Mock 模型
  │     mcp <sub>...          管理命令子路由
  │     skills <sub>...       技能管理子路由
  │
  ├── 管理命令 → 直接退出 (mcp list/add/remove, skills list/add/remove)
  │
  ├── 环境探测
  │     ├── TTY 可用 → tty.App.run()
  │     ├── stdin 有内容 → pipe.App.run() (单次消息)
  │     └── TTY 不可用 → pipe.App.run() (readline 循环)
  │
  └── 优雅关闭
        ├── signal.SIGINT → 中断当前 Agent Turn
        ├── signal.SIGTERM → 保存会话并退出
        └── finally → dispose all (MCP clients, temp files)
```

**设计要点**:
- `main.py` 自身不超过 100 行
- 管理命令通过 `argparse` subparser 注册，与运行模式完全解耦

---

### 2.2 交互层 — `ui/`

#### 2.2.1 TTY 模块 — `ui/tty/`

基于 `rich` + `prompt_toolkit` 的完整终端体验。

```
ui/tty/
├── app.py          # TTY 应用主循环
├── input.py        # prompt_toolkit 输入绑定
├── render.py       # rich 渲染布局
├── transcript.py   # 对话转录滚动
├── permission.py   # 权限提示弹出层
└── theme.py        # 主题/颜色配置
```

**渲染布局 (rich.Layout)**:

```
┌─────────────────────────────────────────────┐
│  mini-code v0.2.0  model: claude-sonnet-4-6 │  ← 状态栏
├─────────────────────────────────────────────┤
│                                             │
│  🤖 我已经阅读了该文件，发现以下问题...        │  ← 转录区
│                                             │  (rich.Text
│  📄 tool: read_file(path="src/main.py")     │   + 滚动)
│  [文件内容...]                               │
│                                             │
├─────────────────────────────────────────────┤
│  > 请帮我修复这个 bug                         │  ← 输入区
│  [Ctrl+O: 斜杠菜单] [Ctrl+R: 多行模式]        │  (prompt_toolkit)
└─────────────────────────────────────────────┘
```

#### 2.2.2 管道模块 — `ui/pipe/`

非 TTY 环境下的极简交互。

```
ui/pipe/
├── app.py          # readline/管道循环
└── render.py       # 纯文本输出
```

#### 2.2.3 交互层抽象

```python
class UserInterface(Protocol):
    """交互层的抽象接口，所有模式实现此接口"""

    async def display_banner(self, status: AppStatus) -> None: ...
    async def display_assistant_message(self, content: str) -> None: ...
    async def display_progress(self, content: str) -> None: ...
    async def display_tool_call(self, name: str, input: Any) -> None: ...
    async def display_tool_result(self, name: str, output: str) -> None: ...
    async def prompt_permission(self, request: PermissionRequest) -> PermissionResult: ...
    async def read_input(self) -> str: ...
    async def on_shutdown(self) -> None: ...
```

TTY 模式和管道模式分别实现此接口，Agent Loop 只依赖接口，不感知具体交互方式。

---

### 2.3 核心层

#### 2.3.1 Agent Loop — `agent/`

```
agent/
├── loop.py         # Agent 主循环 (async generator)
├── events.py       # AgentEvent 定义
├── retry.py        # 重试策略 (空响应/thinking恢复/工具错误)
└── diagnostics.py  # 诊断信息格式化
```

**核心设计 — Async Generator Agent Loop**:

```python
async def agent_turn(
    messages: MessageList,
    model: ModelAdapter,
    tools: ToolRegistry,
    permissions: PermissionManager,
    *,
    max_steps: int = 25,
) -> AsyncGenerator[AgentEvent, None]:
    """
    一次 Agent Turn 的完整生命周期。

    Yields:
        AgentEvent 序列，UI 层可以流式消费。
    """
    for step in range(max_steps):
        # 1. 上下文管理
        context = compute_context_stats(messages, model.name)
        yield AgentEvent(type="context_stats", data=context)

        if context.utilization >= SNIP_THRESHOLD:
            result = await snip_compact(messages, context)
            if result.did_compact:
                messages = result.messages
                yield AgentEvent(type="compaction", data=result)

        # 2. 调用模型
        yield AgentEvent(type="model_request")
        response = await model.next(messages)
        yield AgentEvent(type="model_response", data=response)

        # 3. 处理响应
        match response:
            case AssistantStep(content=content, kind="final"):
                messages = append_assistant(messages, content)
                yield AgentEvent(type="turn_complete", messages=messages)
                return

            case AssistantStep(content="") if empty_retry_count < 2:
                empty_retry_count += 1
                messages = append_retry_prompt(messages, "empty_response")
                continue

            case ToolCallsStep(calls=calls):
                yield AgentEvent(type="tool_calls", calls=calls)

                for call in calls:
                    result = await tools.execute(call.name, call.input)
                    yield AgentEvent(type="tool_result", call=call, result=result)

                    if result.await_user:
                        messages = append_ask_user(messages, result.output)
                        yield AgentEvent(type="turn_complete", messages=messages)
                        return

                    messages = append_tool_result(messages, call, result)

    yield AgentEvent(type="max_steps_reached", messages=messages)
```

**事件类型**:

```python
AgentEvent = (
    ContextStatsEvent        # 上下文利用率快照
    | CompactionEvent        # 压缩结果
    | ModelRequestEvent      # 即将调用模型
    | ModelResponseEvent     # 模型响应
    | ToolCallEvent          # 开始执行工具
    | ToolResultEvent        # 工具执行结果
    | TurnCompleteEvent      # Turn 结束
    | MaxStepsEvent          # 达到最大步数
    | ErrorEvent             # 可恢复错误
)
```

**调用方 (TTY)**:

```python
async for event in agent_turn(messages, model, tools, permissions):
    match event:
        case ContextStatsEvent(data=stats):
            ui.update_status(f"Context: {stats.utilization:.0%}")
        case CompactionEvent(data=result):
            ui.show_toast(f"Compacted: -{result.tokens_freed} tokens")
        case ModelRequestEvent():
            ui.show_spinner("Thinking...")
        case ModelResponseEvent(data=response):
            ui.hide_spinner()
            ui.append_assistant(response.content)
        case ToolCallEvent(calls=calls):
            ui.show_tool_calls(calls)
        case ToolResultEvent(call=call, result=result):
            ui.show_tool_result(call.name, result.output)
        case TurnCompleteEvent(messages=messages):
            await session.save(messages)
            return
```

#### 2.3.2 上下文管理 Pipeline — `context/`

```
context/
├── pipeline.py     # Pipeline 编排器
├── strategy.py     # CompactionStrategy 抽象基类
├── snip.py         # SnipCompact 策略
├── micro.py        # Microcompact 策略
├── collapse.py     # ContextCollapse 策略
├── auto.py         # AutoCompact 策略 (LLM 全文摘要)
├── manual.py       # ManualCompact 策略
├── groups.py       # 公共消息分组逻辑
└── estimator.py    # 上下文统计计算
```

**统一策略接口**:

```python
@dataclass
class CompactionContext:
    utilization: float
    total_tokens: int
    effective_input: int
    model_name: str

@dataclass
class CompactionResult:
    messages: MessageList
    did_compact: bool
    tokens_before: int
    tokens_after: int
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

class CompactionStrategy(ABC):
    """所有压缩策略的抽象基类"""
    threshold: float = 0.0

    @abstractmethod
    async def apply(
        self,
        messages: MessageList,
        context: CompactionContext,
        model: ModelAdapter | None = None,
    ) -> CompactionResult: ...

    def should_apply(self, context: CompactionContext) -> bool:
        return context.utilization >= self.threshold
```

**Pipeline 编排**:

```python
class CompactionPipeline:
    """按优先级排列的压缩策略链"""

    def __init__(self, strategies: list[CompactionStrategy]):
        self.strategies = strategies

    async def apply(
        self,
        messages: MessageList,
        model: ModelAdapter,
    ) -> MessageList:
        context = compute_compaction_context(messages, model.name)

        for strategy in self.strategies:
            if not strategy.should_apply(context):
                continue

            result = await strategy.apply(messages, context, model)
            if result.did_compact:
                messages = result.messages
                context = compute_compaction_context(messages, model.name)

        return messages

# 默认 Pipeline
default_pipeline = CompactionPipeline([
    SnipCompactStrategy(),        # threshold=0.70, 无模型
    MicrocompactStrategy(),       # threshold=0.50, 无模型
    ContextCollapseStrategy(),    # threshold=0.75, LLM 折叠
])
```

---

### 2.4 服务层

#### 2.4.1 模型服务 — `model/`

```
model/
├── adapter.py      # ModelAdapter 协议
├── anthropic.py    # Anthropic SDK 适配器 (~50 行)
├── mock.py         # Mock 模型 (增强版)
└── retry.py        # tenacity 重试配置
```

**Adapter 协议**:

```python
class ModelAdapter(Protocol):
    name: str

    async def next(self, messages: MessageList) -> AgentStep:
        """调用模型并返回解析后的步骤"""
        ...

    async def summarize(
        self, messages: MessageList, prompt: str
    ) -> str | None:
        """请求模型生成摘要 (用于 compact/collapse)"""
        ...
```

**Anthropic 适配器**:

```python
class AnthropicAdapter:
    def __init__(self, config: RuntimeConfig):
        self.name = config.model
        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=0,  # 由 tenacity 统一管理重试
        )

    @retry(
        stop=stop_after_attempt(get_retry_limit()),
        wait=wait_exponential(multiplier=0.5, max=8),
        retry=retry_if_result(lambda r: _should_retry(r)),
    )
    async def next(self, messages: MessageList) -> AgentStep:
        system, api_messages = to_anthropic_format(messages)
        response = await self.client.messages.create(
            model=self.name,
            system=system,
            messages=api_messages,
            tools=self.tools.to_anthropic_format(),
            max_tokens=self.max_tokens,
        )
        return parse_anthropic_response(response)

    async def summarize(self, messages: MessageList, prompt: str) -> str | None:
        response = await self.client.messages.create(
            model=self.name,
            system="You are a precise assistant that summarizes conversations.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        return parse_summary(response.content[0].text)
```

#### 2.4.2 工具服务 — `tools/`

```
tools/
├── registry.py     # ToolRegistry (注册/查找/执行/释放)
├── definition.py   # ToolDefinition Pydantic 模型
├── builtin/        # 内置工具
│   ├── __init__.py
│   ├── ask_user.py
│   ├── edit_file.py
│   ├── grep_files.py
│   ├── list_files.py
│   ├── load_skill.py
│   ├── modify_file.py
│   ├── patch_file.py
│   ├── read_file.py
│   ├── run_command.py
│   ├── web_fetch.py
│   └── web_search.py
└── mcp_proxy.py    # MCP 工具代理注册
```

**工具定义**:

```python
class ToolDefinition(BaseModel, Generic[T]):
    name: str
    description: str
    input_schema: dict[str, Any]
    input_model: type[T]  # Pydantic 模型 — 替代 Zod schema

    async def run(self, input: T, context: ToolContext) -> ToolResult:
        """子类实现具体逻辑"""
        raise NotImplementedError

    def to_anthropic_format(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

# 具体工具 — 声明式定义
class ReadFileInput(BaseModel):
    path: str
    offset: int = 0
    limit: int | None = None

async def read_file(input: ReadFileInput, ctx: ToolContext) -> ToolResult:
    target = ctx.resolve_path(input.path)
    await ctx.permissions.ensure_path_access(target, "read")
    content = await read_file_content(target, input.offset, input.limit)
    return ToolResult(ok=True, output=content)

read_file_tool = ToolDefinition(
    name="read_file",
    description="Read a file from the filesystem.",
    input_schema=ReadFileInput.model_json_schema(),
    input_model=ReadFileInput,
    run=read_file,
)
```

**ToolRegistry**:

```python
class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition] | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        self._disposers: list[Callable[[], Awaitable[None]]] = []
        self._skills: list[SkillSummary] = []
        self._mcp_servers: list[McpServerSummary] = []
        for tool in (tools or []):
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name not in self._tools:
            self._tools[tool.name] = tool

    async def execute(
        self, name: str, input: Any, context: ToolContext
    ) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(ok=False, output=f"Unknown tool: {name}")
        try:
            parsed = tool.input_model.model_validate(input)
            return await tool.run(parsed, context)
        except ValidationError as e:
            return ToolResult(ok=False, output=str(e))
        except Exception as e:
            return ToolResult(ok=False, output=str(e))

    def to_anthropic_format(self) -> list[dict]:
        return [t.to_anthropic_format() for t in self._tools.values()]

    async def dispose(self) -> None:
        await asyncio.gather(*(d() for d in self._disposers))
```

#### 2.4.3 权限服务 — `perm/`

```
perm/
├── manager.py      # PermissionManager
├── chain.py        # 决策链处理器
├── handlers/       # 处理器实现
│   ├── workspace.py    # 工作区内自动通过
│   ├── session_deny.py # Session 拒绝列表
│   ├── session_allow.py# Session 允许列表
│   ├── persist_deny.py # 持久化拒绝
│   ├── persist_allow.py# 持久化允许
│   ├── danger.py       # 危险命令识别
│   └── prompt.py       # 用户交互提示
├── classifier.py   # 命令危险等级分类
└── store.py         # 权限持久化
```

**决策链模式**:

```python
class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    PASS = "pass"  # 无法决策，传递给下一个处理器

@dataclass
class PermissionResult:
    decision: Decision
    reason: str | None = None
    feedback: str | None = None

class PermissionHandler(ABC):
    @abstractmethod
    async def handle(
        self, request: PermissionRequest, store: PermissionStore
    ) -> PermissionResult | None:
        """返回 PermissionResult 表示决策完成，返回 None 表示无法处理"""
        ...

class PermissionChain:
    def __init__(self, handlers: list[PermissionHandler]):
        self.handlers = handlers

    async def evaluate(
        self, request: PermissionRequest, store: PermissionStore
    ) -> PermissionResult:
        for handler in self.handlers:
            result = await handler.handle(request, store)
            if result is not None:
                return result
        return PermissionResult(decision=Decision.DENY, reason="no_handler")

# 配置决策链
path_chain = PermissionChain([
    WorkspaceHandler(),        # 工作区内自动通过
    SessionDenyHandler(),      # 本次会话已拒绝
    PersistentDenyHandler(),   # 持久化拒绝
    SessionAllowHandler(),     # 本次会话已允许
    PersistentAllowHandler(),  # 持久化允许
    PromptHandler(),           # 弹出用户提示
])
```

#### 2.4.4 会话服务 — `session/`

```
session/
├── manager.py      # SessionManager (CRUD)
├── store.py        # JSONL 追加存储
├── events.py       # SessionEvent 模型
├── transcript.py   # 转录导出
└── migration.py    # JSONL 格式迁移
```

**设计要点**:
- JSONL 的每一行是自包含的 `SessionEvent` (Pydantic 模型)
- `save()` 幂等：通过 `existing_ids` set 去重
- `load()` 从最后一个 `compact_boundary` 之后开始读取
- `transcript()` 导出为人类可读格式

```python
class SessionEvent(BaseModel):
    type: SessionEventType
    message: ChatMessage | None = None
    uuid: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    session_id: str
    cwd: str
    parent_uuid: str | None = None
    logical_parent_uuid: str | None = None
    compact_metadata: CompactMetadata | None = None
    snip_metadata: SnipMetadata | None = None
    collapse_span: CollapseSpan | None = None

class SessionManager:
    def __init__(self, cwd: str):
        self.cwd = cwd
        self.project_dir = _project_dir(cwd)

    async def save(self, session_id: str, messages: MessageList, saved_count: int = 0) -> None:
        ...

    async def load(self, session_id: str) -> MessageList | None:
        ...

    async def list(self) -> list[SessionMeta]:
        ...

    async def fork(self, session_id: str) -> str | None:
        ...

    async def rename(self, session_id: str, title: str) -> bool:
        ...

    async def clear(self, session_id: str) -> None:
        ...

    async def cleanup_expired(self, max_age: timedelta) -> int:
        ...
```

#### 2.4.5 配置服务 — `config/`

```
config/
├── settings.py     # pydantic-settings RuntimeConfig
├── merge.py        # 多层配置合并逻辑
├── paths.py        # 配置路径常量
└── store.py        # JSON 读写
```

**声明式配置**:

```python
class RuntimeConfig(BaseSettings):
    model: str
    base_url: str = "https://api.anthropic.com"
    api_key: SecretStr | None = None
    auth_token: SecretStr | None = None
    max_output_tokens: int | None = None
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_prefix="MINI_CODE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @classmethod
    async def load(cls) -> "RuntimeConfig":
        """按优先级合并多层配置"""
        env_config = cls()  # 自动从环境变量加载
        claude_config = await _load_claude_settings()
        mini_code_config = await _load_mini_code_settings()
        mcp_global = await _load_mcp_config(scope="user")
        mcp_project = await _load_mcp_config(scope="project")

        return cls(
            model=(
                mini_code_config.get("model")
                or claude_config.get("model")
                or env_config.model
            ),
            base_url=env_config.base_url,
            api_key=env_config.api_key or mini_code_config.get("api_key"),
            mcp_servers={
                **mcp_global,
                **mcp_project,
                **(mini_code_config.get("mcp_servers") or {}),
            },
        )
```

#### 2.4.6 MCP 服务 — `mcp/`

```
mcp/
├── client.py       # McpClient 抽象
├── stdio.py        # StdioMcpClient (~100行，使用官方SDK)
├── http_client.py  # StreamableHttpMcpClient (~80行，使用官方SDK)
├── proxy.py        # 工具代理 (MCP tool → ToolDefinition)
└── auth.py         # Token 管理 (含 TTL 缓存)
```

#### 2.4.7 技能服务 — `skills/`

```
skills/
├── discover.py     # 技能发现 (扫描多个目录)
├── loader.py       # SKILL.md 加载
└── installer.py    # 技能安装/卸载
```

---

### 2.5 基础设施层 — `infra/`

```
infra/
├── types.py        # ChatMessage Pydantic 模型 (discriminated union)
├── tokens/
│   ├── estimator.py    # tiktoken 精确计数
│   └── context.py      # 上下文窗口 + max_output_tokens 配置
├── storage/
│   ├── files.py        # 大工具结果持久化
│   └── budget.py       # 工具结果预算控制
├── errors.py       # 自定义异常层级
└── logging.py      # 结构化日志
```

**消息模型 (Pydantic discriminated union)**:

```python
from pydantic import BaseModel, Field
from typing import Literal, Annotated, Any

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
    id: str = Field(default_factory=lambda: str(uuid4()))

class AssistantToolCall(BaseModel):
    role: Literal["assistant_tool_call"]
    tool_use_id: str
    tool_name: str
    input: Any
    provider_usage: ProviderUsage | None = None
    id: str = Field(default_factory=lambda: str(uuid4()))

class ToolResultMessage(BaseModel):
    role: Literal["tool_result"]
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False
    id: str = Field(default_factory=lambda: str(uuid4()))

# ... 其他消息类型

ChatMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage |
    AssistantThinking | AssistantProgress | AssistantToolCall |
    ToolResultMessage | ContextSummary | SnipBoundary,
    Field(discriminator="role"),
]

MessageList = list[ChatMessage]
```

**自定义异常层级**:

```python
class MiniCodeError(Exception):
    """所有 mini-code 异常的基类"""

class ConfigError(MiniCodeError):
    """配置相关错误"""

class ModelError(MiniCodeError):
    """模型调用相关错误"""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

class ToolError(MiniCodeError):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: str):
        super().__init__(message)
        self.tool_name = tool_name

class PermissionError(MiniCodeError):
    """权限拒绝错误"""

class CompactionError(MiniCodeError):
    """压缩/折叠失败（非致命）"""
```

---

## 三、设计亮点

### 亮点 1：Async Generator Agent Loop — 流式事件总线

**方案**: Agent Loop 改为 async generator，每个关键步骤 `yield` 一个类型化事件。UI 层通过 `async for` 消费事件流。

```python
# 以前：回调地狱
await runAgentTurn({
    model, tools, messages, cwd,
    onToolStart: lambda name, input: ui.show_tool(name),
    onToolResult: lambda name, output: ui.show_result(output),
    onAssistantMessage: lambda content: ui.show_message(content),
    onProgressMessage: lambda content: ui.show_progress(content),
    onAutoCompact: lambda result: ui.show_toast(f"Compacted: {result.tokensAfter}"),
    onContextCollapse: lambda result: ui.update_collapse_state(),
})

# 现在：流式消费
async for event in agent_turn(messages, model, tools, permissions):
    match event:
        case ToolCallEvent(calls=calls):
            ui.show_tools(calls)
        case ToolResultEvent(result=result):
            ui.show_result(result)
        case CompactionEvent(data=data):
            ui.show_toast(f"Compacted: -{data.tokens_freed} tokens")
```

**收益**:
- Agent Loop 零 UI 依赖，纯函数可测试
- 新增事件类型不影响已有消费者
- 支持中间件模式（在 generator 外包装日志、超时、指标收集）
- UI 可以选择性消费事件（如管道模式忽略 compaction 事件）

### 亮点 2：统一压缩策略 Pipeline

**方案**: 抽象 `CompactionStrategy` 基类，Pipeline 按优先级链式执行。

```python
# 配置即策略
pipeline = CompactionPipeline([
    SnipCompactStrategy(threshold=0.70),
    MicrocompactStrategy(threshold=0.50),
    ContextCollapseStrategy(threshold=0.75),
])

# Agent Loop 中一行调用
messages = await pipeline.apply(messages, model)
```

**收益**:
- 新增策略只需实现 `CompactionStrategy`，不改 Agent Loop
- 策略可以独立测试，注入 mock ModelAdapter
- 阈值可以通过配置调整，不需要改代码
- 策略顺序可配置（如禁用 snipCompact）

### 亮点 3：Pydantic 消息模型 — 类型安全的数据管道

**方案**: 所有消息类型用 Pydantic discriminated union 建模，序列化/反序列化/校验自动完成。

```python
# 反序列化 — 自动根据 role 字段分发
msg = ChatMessage.model_validate({"role": "user", "content": "hello"})
assert isinstance(msg, UserMessage)

# 序列化 — 一行代码
json_str = msg.model_dump_json()

# JSONL 持久化 — 零序列化代码
async def save_session(path: str, messages: MessageList):
    lines = [m.model_dump_json() for m in messages]
    await append_lines(path, lines)

# 消息转换 — 访问者模式
def to_anthropic_format(msg: ChatMessage) -> dict:
    match msg:
        case UserMessage(content=c):
            return {"role": "user", "content": c}
        case ToolResultMessage(tool_use_id=tid, content=c, is_error=e):
            return {"type": "tool_result", "tool_use_id": tid, "content": c, "is_error": e}
        # ...
```

### 亮点 4：决策链权限系统

**方案**: 权限检查抽象为处理器责任链，每个处理器负责一个决策维度。

```python
path_chain = PermissionChain([
    WorkspaceHandler(),        # 优先级最高：工作区内直接放行
    SessionDenyHandler(),      # 已被拒绝 → 快速拒绝
    PersistentDenyHandler(),   # 持久化拒绝
    SessionAllowHandler(),     # 已被允许 → 快速通过
    PersistentAllowHandler(),  # 持久化允许
    PromptHandler(),           # 兜底：弹出交互提示
])
```

**收益**:
- 每个处理器职责单一，可独立测试
- 处理器顺序即优先级，一目了然
- 新增权限维度（如时间窗口限制）只需添加一个处理器

### 亮点 5：交互层抽象 — 模式无关的 UI 协议

**方案**: 定义 `UserInterface` 协议，TTY 和管道模式各自实现。

```python
class UserInterface(Protocol):
    async def display_banner(self, status: AppStatus) -> None: ...
    async def display_assistant_message(self, content: str) -> None: ...
    async def display_tool_call(self, name: str, input: Any) -> None: ...
    async def display_tool_result(self, name: str, output: str) -> None: ...
    async def prompt_permission(self, request: PermissionRequest) -> PermissionResult: ...
    async def read_input(self) -> str: ...

# main.py 中根据环境选择实现
def create_ui() -> UserInterface:
    if sys.stdout.isatty():
        return TtyUI()
    return PipeUI()

# Agent Loop 依赖接口，不感知具体实现
async def main():
    ui = create_ui()
    async for event in agent_turn(messages, model, tools, permissions):
        await dispatch_event(ui, event)
```

### 亮点 6：斜杠命令插件系统

**方案**: 装饰器注册 + 自动发现。

```python
# 定义命令
@register_slash("/model", "/model [name]", "Show or set the current model")
async def cmd_model(args: str, ctx: CommandContext) -> str:
    if args.strip():
        await ctx.config.save_model(args.strip())
        return f"Model set to {args}"
    return f"Current: {ctx.config.model}"

# 自动补全 — 从注册表生成
async def complete_slash(text: str) -> list[str]:
    return [
        cmd.usage for cmd in registry.values()
        if cmd.usage.startswith(text)
    ]

# 帮助菜单 — 从注册表生成
def format_help() -> str:
    return "\n".join(
        f"{cmd.usage:30s} {cmd.description}"
        for cmd in registry.values()
    )
```

### 亮点 7：Python 原生异步 — 无回调的并发

```python
# 并行 MCP 服务器连接
results = await asyncio.gather(
    *(connect_mcp_server(name, cfg) for name, cfg in servers.items()),
    return_exceptions=True,
)

# 并行工具结果持久化
await asyncio.gather(
    *(persist_large_result(r) for r in tool_results if r.is_large()),
)

# 优雅关闭 — 信号 + asyncio.CancelledError
async def main():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: shutdown_event.set())

    try:
        await run_app()
    except asyncio.CancelledError:
        await cleanup()
```

### 亮点 8：tenacity 统一重试策略

**方案**: `tenacity` 装饰器统一所有重试。

```python
# API 重试
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.5, max=8),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
)
async def call_model(messages): ...

# Compact 重试（带失败计数和自动禁用）
class AutoCompactDisabled(Exception):
    pass

def after_failed_compact(retry_state: RetryCallState):
    if retry_state.attempt_number >= 3:
        raise AutoCompactDisabled()

@retry(
    stop=stop_after_attempt(3),
    after=after_failed_compact,
)
async def auto_compact(messages, model): ...
```

### 亮点 9：结构化日志

```python
# 按模块区分的 logger
logger = structlog.get_logger(__name__)

# 在 Agent Loop 中
logger.info("agent_turn_started", step=step, utilization=context.utilization)
logger.info("model_called", model=model.name, tokens=response.usage.input_tokens)
logger.info("tool_executed", tool=tool_name, ok=result.ok, duration_ms=duration)
logger.warning("compaction_skipped", reason="below_threshold", utilization=context.utilization)

# 通过环境变量控制日志级别和格式
# MINI_CODE_LOG_LEVEL=debug
# MINI_CODE_LOG_FORMAT=json  # 或 console
```

### 亮点 10：精确 Token 计数

**方案**:
- 已知消息：使用 Anthropic API 返回的精确 `usage.input_tokens`
- 未知消息（新工具结果）：使用 `tiktoken` 精确计数
- 不再需要角色级别的 `CHARS_PER_TOKEN` 近似值

```python
class TokenCounter:
    def __init__(self, model: str):
        self.encoding = tiktoken.encoding_for_model(model)

    def count_known(self, messages: MessageList) -> TokenAccounting:
        """从最近的 API usage 回填精确值"""
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.provider_usage and not msg.usage_stale:
                precise = msg.provider_usage.total_tokens
                unknown_tail = sum(self.count_unknown(m) for m in messages[idx+1:])
                return TokenAccounting(
                    total=precise + unknown_tail,
                    precise=precise,
                    estimated=unknown_tail,
                )
        return TokenAccounting(total=sum(self.count_unknown(m) for m in messages))

    def count_unknown(self, message: ChatMessage) -> int:
        """对单条消息做精确 tiktoken 计数"""
        match message:
            case SystemMessage(content=c) | UserMessage(content=c) | AssistantMessage(content=c):
                return len(self.encoding.encode(c))
            case AssistantToolCall(input=i):
                return len(self.encoding.encode(json.dumps(i)))
            case ToolResultMessage(content=c):
                return len(self.encoding.encode(c))
            # ...
```

---

## 四、目录结构总览

```
mini-code/
├── main.py                    # 入口 (~80 行)
│
├── agent/                     # Agent 核心
│   ├── loop.py                #   async generator Agent Loop
│   ├── events.py              #   AgentEvent 定义
│   ├── retry.py               #   重试策略
│   └── diagnostics.py         #   诊断信息
│
├── context/                   # 上下文管理
│   ├── pipeline.py            #   压缩 Pipeline
│   ├── strategy.py            #   CompactionStrategy 基类
│   ├── snip.py                #   SnipCompact
│   ├── micro.py               #   Microcompact
│   ├── collapse.py            #   ContextCollapse
│   ├── auto.py                #   AutoCompact
│   ├── manual.py              #   ManualCompact
│   ├── groups.py              #   消息分组
│   └── estimator.py           #   上下文统计
│
├── model/                     # 模型服务
│   ├── adapter.py             #   ModelAdapter 协议
│   ├── anthropic.py           #   Anthropic 适配器
│   ├── mock.py                #   Mock 模型
│   └── retry.py               #   tenacity 配置
│
├── tools/                     # 工具服务
│   ├── registry.py            #   ToolRegistry
│   ├── definition.py          #   ToolDefinition
│   ├── mcp_proxy.py           #   MCP 工具代理
│   └── builtin/               #   12 个内置工具
│       ├── ask_user.py
│       ├── edit_file.py
│       ├── grep_files.py
│       ├── list_files.py
│       ├── load_skill.py
│       ├── modify_file.py
│       ├── patch_file.py
│       ├── read_file.py
│       ├── run_command.py
│       ├── web_fetch.py
│       └── web_search.py
│
├── perm/                      # 权限服务
│   ├── manager.py             #   PermissionManager
│   ├── chain.py               #   决策链
│   ├── classifier.py          #   命令危险分类
│   ├── store.py               #   持久化存储
│   └── handlers/              #   处理器
│       ├── workspace.py
│       ├── session_deny.py
│       ├── session_allow.py
│       ├── persist_deny.py
│       ├── persist_allow.py
│       ├── danger.py
│       └── prompt.py
│
├── session/                   # 会话服务
│   ├── manager.py             #   SessionManager
│   ├── store.py               #   JSONL 存储
│   ├── events.py              #   SessionEvent 模型
│   ├── transcript.py          #   转录导出
│   └── migration.py           #   格式迁移
│
├── config/                    # 配置服务
│   ├── settings.py            #   pydantic-settings
│   ├── merge.py               #   多层合并
│   ├── paths.py               #   路径常量
│   └── store.py               #   JSON 读写
│
├── mcp/                       # MCP 服务
│   ├── client.py              #   McpClient 抽象
│   ├── stdio.py               #   Stdio 客户端
│   ├── http_client.py         #   HTTP 客户端
│   ├── proxy.py               #   工具代理
│   └── auth.py                #   Token 管理
│
├── skills/                    # 技能服务
│   ├── discover.py            #   技能发现
│   ├── loader.py              #   SKILL.md 加载
│   └── installer.py           #   安装/卸载
│
├── ui/                        # 交互层
│   ├── protocol.py            #   UserInterface 接口
│   ├── tty/                   #   TTY 模式
│   │   ├── app.py
│   │   ├── input.py
│   │   ├── render.py
│   │   ├── transcript.py
│   │   ├── permission.py
│   │   └── theme.py
│   └── pipe/                  #   管道模式
│       ├── app.py
│       └── render.py
│
├── commands/                  # 斜杠命令
│   ├── registry.py            #   命令注册表
│   ├── builtin/               #   内置命令
│   │   ├── help.py
│   │   ├── model.py
│   │   ├── status.py
│   │   ├── tools.py
│   │   ├── mcp.py
│   │   ├── skills.py
│   │   ├── resume.py
│   │   ├── fork.py
│   │   ├── compact.py
│   │   └── collapse.py
│   └── local_tools.py         #   本地工具快捷方式
│
├── infra/                     # 基础设施
│   ├── types.py               #   ChatMessage 模型
│   ├── tokens/
│   │   ├── counter.py         #   Token 精确计数
│   │   └── context_window.py  #   上下文窗口配置
│   ├── storage/
│   │   ├── large_results.py   #   大结果持久化
│   │   └── budget.py          #   结果预算
│   ├── errors.py              #   异常层级
│   └── logging.py             #   结构化日志
│
├── pyproject.toml             # 项目配置
└── tests/                     # 测试
    ├── agent/
    ├── context/
    ├── model/
    ├── tools/
    ├── perm/
    ├── session/
    └── ui/
```

---

## 五、设计原则总结

| 原则 | 体现 |
|------|------|
| **关注点分离** | 7 个服务层各自独立，通过接口通信 |
| **依赖倒置** | Agent Loop 依赖 `ModelAdapter`/`UserInterface` 协议，不依赖具体实现 |
| **开闭原则** | 压缩策略、权限处理器、斜杠命令均可插拔扩展 |
| **单一职责** | 每个模块 < 300 行，每个类 < 150 行 |
| **可测试性** | 所有核心逻辑接受依赖注入，async generator 可逐个 yield 验证 |
| **渐进增强** | 管道模式 → TTY 模式逐步增强，共享核心逻辑 |
| **Python 惯用** | async/await、context manager、Pydantic、match/case 充分使用 |
| **生态优先** | 能用官方 SDK 或成熟库的，绝不手写 |
