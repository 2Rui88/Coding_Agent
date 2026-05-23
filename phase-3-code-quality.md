# 第三阶段：代码质量与架构分析

## 高优先级

### 1. 单文件过大 — `tty-app.ts` (~2100行)

**位置**: [tty-app.ts](src/tty-app.ts)

**问题**: TTY 主循环混合了 UI 渲染、事件处理、会话管理、权限提示、转录导航等多种职责。

**建议**: 拆分为多个模块：
- `tty-app-state.ts` — 状态管理
- `tty-permission-handler.ts` — 权限提示渲染与处理
- `tty-transcript-controller.ts` — 转录滚动、选择、复制
- `tty-input-handler.ts` — 输入事件分发

### 2. 无测试覆盖

**位置**: 全局

**问题**: 项目中未见任何测试文件（`*.test.ts`, `*.spec.ts`）。核心逻辑如 `agent-loop`、`compact/*`、`permissions` 均无单元测试。

**影响**: 重构风险极高，修改行为无法自动验证。

**建议**: 优先为以下模块添加测试：
1. `agent-loop.ts` — 核心循环
2. `compact/snipCompact.ts` — 删除逻辑
3. `compact/context-collapse.ts` — 折叠逻辑
4. `permissions.ts` — 安全决策
5. `anthropic-adapter.ts` — 消息转换

### 3. Token 估算是纯启发式

**位置**: [utils/token-estimator.ts](src/utils/token-estimator.ts)

**问题**: 使用字符数/固定比率估算 token（`CHARS_PER_TOKEN`），对中文等多字节字符误差极大。无 tiktoken 或 API 返回的精确 use 信息充分利用。

**当前方法**:
```
const CHARS_PER_TOKEN = { system: 3.5, user: 3.0, assistant: 3.5, ... }
tokens = ceil(content.length / ratio)
```

**影响**: 所有压缩决策（SnipCompact、Microcompact、ContextCollapse、AutoCompact）都依赖此估算，不准确可能导致过早/过晚压缩。

**建议**: 引入 `@anthropic-ai/tokenizer` 或 `tiktoken` 进行精确计数，同时利用 API 返回的 `usage.input_tokens` 对已知部分做精确计算。

### 4. 消息分组逻辑重复

**位置**: [compact/snipCompact.ts](src/compact/snipCompact.ts) 和 [compact/context-collapse.ts](src/compact/context-collapse.ts)

**问题**: 两个文件各自实现 `buildMessageGroups()`，逻辑相似但不完全相同：

| 差异点 | snipCompact | context-collapse |
|--------|------------|------------------|
| 分组粒度 | `tool_call + tool_result`（成对） | `thinking + all tool_calls + all tool_results` |
| 保护判断 | 文件编辑/错误附近 | tool组是否闭合 + 边界消息 |
| 额外逻辑 | `protectNearbyGroups` | `committedCollapsedMessageIds` |

**影响**: 修改分组逻辑需要在两处同步，容易遗漏。

**建议**: 提取公共的 `buildMessageGroups()` 到 `compact/groups.ts`，各策略仅注入各自的 `isProtected` 判断函数。

### 5. MCP Token 无过期机制

**位置**: [mcp.ts:342-355](src/mcp.ts)

**问题**: `mcpTokenCache` 是内存 `Map`，永不过期。若 token 被服务端撤销，不重启进程无法刷新。

**建议**: 添加 TTL 缓存，或至少支持 401 响应时清除缓存并重新加载。

---

## 中优先级

### 6. 权限提示同步阻塞 Agent Loop

**位置**: [tty-app.ts](src/tty-app.ts) 内的 `pendingApproval` 机制

**问题**: TTY 模式中权限提示通过 Promise + 事件循环异步实现，但 Agent 循环在 `await` 权限结果时完全阻塞。在权限提示期间无法处理任何其他事件。

**影响**: 如果用户在权限提示时按 Ctrl+C，整个流程可能卡住。

**建议**: 考虑超时自动拒绝机制，或使用 AbortController 支持取消挂起的权限请求。

### 7. 模型上下文窗口配置硬编码

**位置**: [utils/model-context.ts](src/utils/model-context.ts)

**问题**: 每种模型的 `contextWindow` 手动维护列表，新增模型需改代码。部分配置值存疑：

| 模型 | contextWindow | 合理性 |
|------|--------------|--------|
| gpt-4.1-mini/nano | 1,047,576 | 这个数值看起来像是 1,048,576 (1M) 的笔误 |
| gemini-2.5-pro/flash | 1,048,576 | 实际 Gemini 2.5 Pro 的上下文窗口为 1M tokens |

**建议**: 考虑将模型配置外部化到 JSON 文件，或在启动时从 API 获取模型能力信息。

### 8. 工具结果持久化并发安全

**位置**: [utils/tool-result-storage.ts](src/utils/tool-result-storage.ts)

**问题**: 使用 `writeFile(f, content, { flag: 'wx' })` 防覆盖。在并发场景下两个相同 `toolUseId` 的写入会导致一个失败。

**现状**: 当前架构是同步 Agent Loop（单步串行），实际无并发问题。但如果未来引入并行工具执行，此处会成为竞态条件。

### 9. Anthropic Adapter 无请求超时

**位置**: [anthropic-adapter.ts:344](src/anthropic-adapter.ts)

**问题**: `fetch` 调用无 `AbortController` 超时控制。只有 `StreamableHttpMcpClient` 中有超时。

**影响**: 如果 API 响应极慢，程序可能无限等待。

**建议**: 添加可配置的请求超时（默认 60-120 秒）。

### 10. MockModelAdapter 与生产逻辑脱节

**位置**: [mock-model.ts](src/mock-model.ts)

**问题**: Mock 只模拟了基本的文本解析，未模拟：
- 工具调用后的 Agent 循环（返回 tool_calls 后无后续处理）
- 压缩流程
- 权限系统交互
- 错误/空响应重试

**建议**: 增强 Mock 使其能进行完整的多轮工具调用循环，用于端到端测试。

---

## 低优先级

### 11. Compact 模块导出风格不一致

**位置**: [compact/](src/compact/)

| 模块 | 导出风格 |
|------|---------|
| snipCompact.ts | 导出独立函数 `snipCompactConversation()` |
| microcompact.ts | 导出独立函数 `microcompact()` |
| auto-compact.ts | 导出独立函数 `autoCompact()` |
| context-collapse.ts | 导出函数 + 类 `createContextCollapseState()` + `applyContextCollapseIfNeeded()` |
| compact.ts | 导出独立函数 `compactConversation()` |

**建议**: 统一为 `compact(input, options) => result` 接口。

### 12. 无结构化日志

**位置**: 各处 `process.env.MINI_CODE_DEBUG_*`

**问题**: 调试依赖环境变量 + `console.error`，无日志级别、格式化、文件输出。

**建议**: 引入轻量级日志库或至少统一 `createLogger(module)` 工厂函数。

### 13. `reconstructSnippedEvents` 的性能问题

**位置**: [session.ts:124-167](src/session.ts#L124-L167)

**问题**: 对每个 event 遍历全部 `snipEvents`，构造 `removedIdToSnips` Map 并进行二次遍历。时间复杂度 O(n × m)，长会话可能变慢。

**建议**: 使用 `Map<messageId, snipEvent>` 替代数组遍历。

### 14. 后台任务无法获取输出

**位置**: [background-tasks.ts](src/background-tasks.ts)

**问题**: `registerBackgroundShellTask` 只记录 `pid` 和 `status`。后台命令的 stdout/stderr 被丢弃（`stdio: 'ignore'`）。

**影响**: 无法排查后台任务失败原因。

**建议**: 将 stdout/stderr 写入临时文件，在 `getBackgroundTask` 时可选返回。

### 15. `projectDirName` 路径哈希过于简单

**位置**: [session.ts:49-51](src/session.ts#L49-L51)

**问题**: `cwd.replace(/[/\\:]+/g, '-')` 可能为不同路径产生相同目录名：
- `C:\projects\a\b` → `C--projects-a-b`
- `C:\projects\a-b` → `C--projects-a-b`（相同！）

**建议**: 对完整路径做 SHA256 摘要，或使用更安全的编码方式。

---

## 问题优先级汇总

| 优先级 | 问题数 | 关键词 |
|--------|--------|--------|
| 高 | 5 | tty-app单文件、无测试、token估算、逻辑重复、token缓存 |
| 中 | 5 | 同步阻塞、配置硬编码、并发安全、无超时、mock脱节 |
| 低 | 5 | 导出风格、无日志、O(n²)、后台输出、路径哈希 |
