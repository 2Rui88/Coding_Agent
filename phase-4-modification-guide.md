# 第四阶段：修改前准备

## 4.1 项目整体架构总结

这是一个**单体 CLI 应用**，采用**事件驱动的 Agent Loop 模式**。

- **核心流程**: 用户输入 → Agent Loop（LLM 推理 → 工具调用 → 结果反馈 → 下一推理步骤）→ 输出
- **分层方式**: 没有传统后端分层（Router/Service/DAO），所有逻辑通过函数调用串联
- **最复杂子系统**: 上下文管理，有 **5层渐进式压缩策略**（snip → microcompact → context collapse → auto compact），按利用率阈值逐级触发
- **持久化**: JSONL 追加写入模式，幂等去重
- **安全模型**: 三级权限沙箱（路径/命令/编辑），支持跨会话持久化

## 4.2 核心数据流

```
配置加载 (settings.json × 4 + env)
     │
     ▼
SystemPrompt (CLAUDE.md × 2 + permissions + skills + MCP)
     │
     ▼
ChatMessage[] (消息数组，不可变追加模式)
     │
     ▼
Agent Loop (model.next → response → tool.execute → repeat)
     │
     ▼
Session Persistence (JSONL 追加到 ~/.mini-code/projects/<cwd>/<sessionId>.jsonl)
```

## 4.3 核心模块说明

### agent-loop.ts (462行)

Agent 的核心循环逻辑。职责：
- 编排 4 层上下文压缩
- 调用模型并处理响应
- 执行工具调用
- 处理空响应/进度消息/thinking 恢复/工具错误

### anthropic-adapter.ts (438行)

LLM API 适配层。职责：
- 将内部 `ChatMessage[]` 转换为 Anthropic Messages API 格式
- HTTP 请求与重试（指数退避 + jitter）
- 响应解析（文本/工具调用/thinking 块）
- `<final>` / `<progress>` 标记解析

### tty-app.ts (~2100行)

交互式 TTY 主循环。职责：
- TTY raw mode 管理
- 输入事件处理（键盘/鼠标/剪贴板）
- 对话转录渲染
- 权限提示 UI
- 斜杠菜单
- 会话恢复/fork

### compact/context-collapse.ts (701行)

最复杂的压缩策略。职责：
- 将旧消息段落提交给 LLM 生成摘要
- 将摘要注入到模型可见的消息视图中
- 原始消息保留在会话记录中
- 支持多个 collapse span 的非重叠投影

### compact/snipCompact.ts (499行)

无模型删除策略。职责：
- 从消息中间识别"安全区间"
- 保护文件编辑/错误/边界附近的消息
- 删除区间并用 `snip_boundary` 占位
- 比较多个 safe run 的 token 释放效果

### mcp.ts (1277行)

MCP 协议集成。职责：
- JSON-RPC 2.0 通信
- 两种传输：stdio（content-length/newline-json 帧）和 streamable-http
- 工具代理：将 MCP 工具包装为 `ToolDefinition`
- 协议协商与缓存

### permissions.ts (501行)

安全沙箱。职责：
- 路径访问控制（workspace 内自动通过）
- 命令执行控制（危险命令分类）
- 文件编辑控制（7 种审批选项）
- 跨会话持久化

## 4.4 修改代码时的风险点

### 1. 消息数组不可变性

`agent-loop.ts` 中 messages 每次通过 `[...messages, newMsg]` 创建新数组。不要尝试直接修改数组元素。

```typescript
// 正确模式
messages = [...messages, newMessage]

// 错误模式（会导致状态不一致）
messages.push(newMessage)
```

### 2. 上下文压缩的顺序依赖

压缩策略的执行顺序是固定的，不可调换：

```
SnipCompact → Microcompact → ContextCollapse → Model.next()
```

- SnipCompact 必须在 Microcompact 之前（snip 会影响 microcompact 的索引）
- ContextCollapse 在以上两者之后（需要基于清理后的消息计算利用率）
- 改变顺序会破坏 token 估算和消息索引

### 3. 权限系统的 Promise 阻塞

TTY 模式中，权限检查通过 `pendingApproval` 阻塞 Agent Loop：

```typescript
// tty-app.ts 中的模式
const result = await new Promise<PermissionPromptResult>((resolve) => {
  pendingApproval = { request, resolve, ... }
  renderPermissionPrompt()
})
// Agent Loop 在此处完全阻塞，直到用户做出选择
```

添加新工具时，确保正确处理权限调用，避免在非 TTY 模式下触发未处理的权限请求。

### 4. MCP 初始化的容错设计

MCP 连接在 `hydrateMcpTools().catch(() => {})` 中静默失败：

```typescript
const mcpHydration = hydrateMcpTools({ cwd, runtime, tools }).catch(() => {
  // Keep startup resilient even if some MCP servers fail.
})
```

修改 MCP 模块时需保持这种启动弹性——单个 MCP 服务器失败不应阻止整个应用启动。

### 5. Token 估算的不准确性

所有压缩阈值依赖 `estimateMessagesTokens`，而它使用字符数/固定比率估算。修改压缩逻辑时：
- 阈值调优需要考虑估算误差（可能 ±30%）
- 中文/日文/韩文等多字节字符的估算误差尤其大
- 利用 API 返回的 `usage.input_tokens` 对已有消息做精确计算，仅预留部分使用估算

### 6. Session 持久化的幂等写入

`saveSession` 通过 `existingIds` Set 去重，防止重复写入：

```typescript
const existingIds = await readExistingEventUuids(filePath)
const toSave = nonSystemMessages.filter((message, index) => {
  if (message.id && existingIds.has(message.id)) return false
  // ...
})
```

修改消息持久化逻辑时，确保：
- 每条消息有唯一的 `id`（由 `ensureMessageId` 生成）
- 不要破坏 `saveSession` 的幂等性（重复调用不会产生重复行）

### 7. 管道模式的降级行为

`index.ts` 中管道模式（非 TTY）有独立的消息循环：

```typescript
// 管道模式：简单 readline 循环
for await (const rawInput of rl) {
  // ...
  messages = await runAgentTurn({ ... })
  // 输出最后一条 assistant 消息
}
```

管道模式下权限检查会抛出错误（无 UI 显示权限提示），而非阻塞等待。修改权限相关逻辑时注意两种模式的差异。

### 8. Compact 失败后的降级

所有压缩策略都有失败保护：

| 策略 | 失败行为 |
|------|---------|
| SnipCompact | 返回原始消息（`didSnip: false`） |
| Microcompact | 返回原始消息 |
| ContextCollapse | 3 次连续失败后禁用 |
| AutoCompact | 3 次连续失败后禁用 |

修改压缩逻辑时，保持安全降级——压缩失败永远不应阻塞 Agent Loop。

## 4.5 最推荐的开发切入点

按价值/风险排序：

| 优先级 | 切入点 | 价值 | 风险 | 说明 |
|--------|--------|------|------|------|
| 1 | 为核心模块添加单元测试 | 极高 | 低 | 从 `agent-loop.ts`、`compact/`、`permissions.ts` 开始 |
| 2 | 拆分 `tty-app.ts` | 高 | 中 | 分离 UI 渲染、事件处理、权限提示 |
| 3 | 统一 compact 的消息分组逻辑 | 中 | 低 | 提取 `buildMessageGroups()` 到共享模块 |
| 4 | 引入精确 Token 计数 | 高 | 中 | tiktoken 或 API usage 回填 |
| 5 | 添加 Anthropic Adapter 请求超时 | 中 | 低 | AbortController + 可配置超时 |
| 6 | 模型配置外部化 | 低 | 低 | JSON/YAML 替代硬编码 |
| 7 | 增强 MockModelAdapter | 中 | 低 | 支持多轮工具调用循环 |
| 8 | 添加结构化日志 | 低 | 低 | 统一 Logger 工厂 |
| 9 | 后台任务输出采集 | 中 | 低 | 写入临时文件 |
| 10 | `projectDirName` 路径编码修复 | 低 | 低 | SHA256 或安全编码 |

### 建议的开发顺序

1. **Phase 1: 测试基础设施** — 搭建 vitest/jest，为核心模块编写测试
2. **Phase 2: 低风险重构** — 统一 compact 分组逻辑、添加超时、修复路径编码
3. **Phase 3: tty-app 拆分** — 将大文件拆分为可测试的模块
4. **Phase 4: 性能优化** — Token 精确计数、session 加载优化

---

## 附录：常用命令

```bash
# 管理命令
minicode mcp list [--project]
minicode mcp add <name> [--project] [--url <url>] [-- <command>]
minicode mcp login <name> --token <token>
minicode mcp remove <name> [--project]

minicode skills list
minicode skills add <path> [--name <name>] [--project]
minicode skills remove <name> [--project]

# 交互命令（TTY/管道模式内）
/help          # 查看帮助
/model <name>  # 切换模型
/status        # 查看当前状态
/tools         # 列出可用工具
/mcp           # 查看 MCP 服务器状态
/skills        # 列出发现的技能
/resume [id]   # 恢复会话
/fork          # 分支会话
/compact       # 手动压缩上下文
/collapse      # 手动折叠上下文
/snip          # 手动快照删除
/exit          # 退出
```

## 附录：环境变量

| 变量 | 用途 |
|------|------|
| `ANTHROPIC_MODEL` | 模型名称 |
| `ANTHROPIC_BASE_URL` | API 基础 URL |
| `ANTHROPIC_AUTH_TOKEN` | Bearer Token 鉴权 |
| `ANTHROPIC_API_KEY` | x-api-key 鉴权 |
| `MINI_CODE_HOME` | 配置目录（默认 `~/.mini-code`） |
| `MINI_CODE_MODEL` | 覆盖模型 |
| `MINI_CODE_MAX_OUTPUT_TOKENS` | 覆盖最大输出 tokens |
| `MINI_CODE_MODEL_MODE` | 设置为 `mock` 使用 Mock 模型 |
| `MINI_CODE_MAX_RETRIES` | API 最大重试次数 |
| `MINI_CODE_DEBUG_AUTOCOMPACT` | 调试自动压缩日志 |
