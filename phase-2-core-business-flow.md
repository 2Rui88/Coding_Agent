# 第二阶段：核心业务链路分析

## 2.1 用户请求流程

```
用户输入 (键盘/管道)
  │
  ▼
tty-app.ts / index.ts (管道模式)
  ├── 斜杠命令? → cli-commands.ts (本地处理，不调 LLM)
  ├── 本地工具快捷方式? → local-tool-shortcuts.ts
  └── 发送给 AI? → runAgentTurn()
       │
       ▼
     agent-loop.ts ────────────────────────────────┐
       │                                           │
       ├── 1. Context Stats 计算                    │
       ├── 2. SnipCompact (无模型删除)              │
       ├── 3. Microcompact (清除旧工具结果)          │  上下文
       ├── 4. ContextCollapse (LLM折叠)             │  管理层
       ├── 5. AutoCompact (LLM摘要压缩, 仅首步)       │
       │                                           │
       ├── 6. ModelAdapter.next() ─────────────┐   │
       │     │                                 │   │
       │     ▼                                 │   │
       │  anthropic-adapter.ts                │   │
       │     ├── toAnthropicMessages()        │   │
       │     ├── POST /v1/messages            │   │
       │     ├── 重试逻辑 (429/5xx)           │   │
       │     └── 解析响应 → AgentStep         │   │
       │                                      │   │
       ├── 7. 响应分派                          │   │
       │     ├── assistant → 检查空响应/进度       │   │
       │     ├── tool_calls → 执行工具           │   │
       │     └── thinking → 记录                │   │
       │                                      │   │
       ├── 8. 工具执行                          │   │
       │     ├── ToolRegistry.execute()        │   │
       │     ├── 权限检查 (PermissionManager)    │   │
       │     ├── 大结果替换 (ContentReplacement) │   │
       │     └── 结果预算 (ToolResultBudget)    │   │
       │                                      │   │
       └── 回到步骤 1 (循环) ─────────────────┘   │
```

## 2.2 工具调用链

```
runAgentTurn()
  → model.next()        ← 调用 LLM
  → 收到 tool_calls[]   ← LLM 返回工具调用
  → tools.execute()     ← ToolRegistry 统一入口
      ├── schema.safeParse(input)    ← Zod 校验
      ├── tool.run(parsed, context)  ← 具体工具执行
      │     ├── resolveToolPath()   ← 工作区路径解析
      │     ├── permissions.ensurePathAccess()  ← 路径权限
      │     ├── permissions.ensureCommand()     ← 命令权限
      │     ├── permissions.ensureEdit()        ← 编辑权限
      │     └── 返回 ToolResult { ok, output }
      └── 错误包裹 (catch → ok: false)
  → replaceLargeToolResult()  ← 大结果持久化到磁盘
  → applyToolResultBudget()   ← 批量结果预算控制
  → 追加 assistant_tool_call + tool_result 消息
  → 继续循环
```

## 2.3 消息类型系统

项目定义了丰富的消息角色（`ChatMessage` discriminated union）：

| 角色 | 用途 |
|------|------|
| `system` | 系统提示词 |
| `user` | 用户输入 |
| `assistant` | 模型最终回复 |
| `assistant_progress` | 模型进度更新 |
| `assistant_thinking` | 模型推理块 |
| `assistant_tool_call` | 工具调用请求 |
| `tool_result` | 工具执行结果 |
| `context_summary` | 压缩摘要 |
| `snip_boundary` | 快照删除边界 |

## 2.4 上下文压缩决策树（5层防护）

```
runAgentTurn() 每步开始:
  │
  ├── 1. SnipCompact (阈值: 70% utilization)
  │     策略: 从消息中间移除安全段（不调 LLM）
  │     保护: 文件编辑附近、错误附近、边界消息
  │     每个 turn 只执行一次
  │
  ├── 2. Microcompact (阈值: 50% utilization)
  │     策略: 清除旧的 read_file/run_command 等工具结果
  │     保留最近 3 个工具结果
  │
  ├── 3. ContextCollapse (阈值: 75% utilization)
  │     策略: LLM 摘要折叠旧消息段
  │     每个 pass 最多 2 个 span，最多 3 次连续失败后禁用
  │
  └── 4. AutoCompact (阈值: 85% utilization, 仅首步)
        策略: LLM 全文摘要压缩
        最多 3 次连续失败后禁用
```

### 各压缩策略对比

| 策略 | 触发时机 | 调用LLM | 可逆性 | 损耗 |
|------|---------|---------|--------|------|
| SnipCompact | 每一步 | 否 | 否（消息删除） | 永久丢失被删除消息 |
| Microcompact | 每一步 | 否 | 是（仅清除内容） | 旧工具结果丢失 |
| ContextCollapse | 每一步 | 是 | 是（原始保留） | 折叠区不可见 |
| AutoCompact | 仅第一步 | 是 | 否（全文摘要） | 永久压缩 |

## 2.5 权限系统

三级权限控制：

```
PermissionManager
  ├── ensurePathAccess(targetPath, intent)
  │     ├── workspace内 → 自动通过
  │     ├── sessionDenied → 拒绝
  │     ├── sessionAllowed → 通过
  │     ├── deniedDirectoryPrefixes → 拒绝
  │     ├── allowedDirectoryPrefixes → 通过
  │     └── 否则 → 弹出权限提示
  │
  ├── ensureCommand(command, args, cwd)
  │     ├── 检查 cwd 权限
  │     ├── 非危险命令 → 自动通过
  │     ├── sessionDenied → 拒绝
  │     ├── sessionAllowed → 通过
  │     └── 否则 → 弹出权限提示
  │
  └── ensureEdit(targetPath, diffPreview)
        ├── sessionDenied → 拒绝
        ├── sessionAllowed / turnAllowed / allowAllTurn → 通过
        └── 否则 → 弹出权限提示（7种选择）
```

权限持久化到 `~/.mini-code/permissions.json`，支持跨会话记忆。

## 2.6 MCP 集成架构

```
mcp.ts
  ├── McpClientLike (接口)
  │     ├── StdioMcpClient    ← 本地进程通信
  │     │     ├── content-length 帧协议
  │     │     └── newline-json 帧协议
  │     └── StreamableHttpMcpClient  ← 远程 HTTP
  │
  └── createMcpBackedTools()
        ├── 遍历 mcpServers 配置
        ├── 启动客户端 → 获取工具列表
        ├── 工具名格式化: mcp__<server>__<tool>
        ├── 额外工具: list_mcp_resources, read_mcp_resource
        ├── 额外工具: list_mcp_prompts, get_mcp_prompt
        └── 返回 { tools, servers, dispose }
```

协议协商：
- 默认：先尝试 `content-length`（快速探测 1.2s），失败后用完整超时重试，再回退到 `newline-json`
- 远程 URL：自动使用 `streamable-http`
- 协商结果缓存到 `~/.mini-code/mcp-protocol-cache.json`

## 2.7 核心模块职责总结

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口 | `index.ts` | 参数解析、初始化、模式分发 |
| TTY | `tty-app.ts` | 交互主循环、UI渲染、权限提示 |
| Agent循环 | `agent-loop.ts` | 工具调度、重试、上下文压缩编排 |
| API适配 | `anthropic-adapter.ts` | 消息转换、HTTP调用、重试、响应解析 |
| 工具注册 | `tool.ts` | ToolRegistry：注册、查找、执行、释放 |
| 工具集 | `tools/*.ts` | 12个内置工具实现 |
| MCP | `mcp.ts` | MCP协议客户端、工具代理 |
| 权限 | `permissions.ts` | 路径/命令/编辑三级沙箱 |
| 配置 | `config.ts` | 多层配置加载与合并 |
| 会话 | `session.ts` | JSONL持久化、恢复、fork、转录 |
| 提示词 | `prompt.ts` | System prompt构建 |
| 技能 | `skills.ts` | SKILL.md发现与加载 |
| 压缩 | `compact/*.ts` | 5种上下文压缩策略 |

## 2.8 模块依赖关系图

```
index.ts
  ├── config.ts ───────────────────────────── (独立)
  ├── manage-cli.ts ──→ config.ts, skills.ts
  ├── prompt.ts ──→ mcp.ts, skills.ts
  ├── tools/index.ts ──→ mcp.ts, skills.ts, tool.ts
  │     └── tools/*.ts ──→ workspace.ts, file-review.ts, permissions.ts
  ├── permissions.ts ────────────────────────── (独立)
  ├── session.ts ──→ config.ts, compact/context-collapse.ts
  ├── agent-loop.ts ──→ compact/*, utils/*, types.ts, tool.ts
  ├── anthropic-adapter.ts ──→ tool.ts, types.ts, utils/context.ts
  ├── tty-app.ts ──→ agent-loop, session, cli-commands, ui, ...
  └── types.ts ──────────────────────────────── (所有模块依赖)
```

### 耦合度评估

- **types.ts** 被所有模块依赖，修改时影响面最大
- **config.ts**、**permissions.ts**、**tool.ts** 为基础设施层，相对独立
- **agent-loop.ts** 与 **compact/*** 模块强耦合
- **tty-app.ts** 是耦合度最高的模块，几乎依赖所有其他模块
- **compact/*** 内部存在逻辑重复（snipCompact 和 context-collapse）
