# 第一阶段：项目整体扫描

## 1.1 项目类型

**AI 终端编程助手（CLI Agent）** — 功能等同于 Claude Code 的自研替代品。纯 TypeScript CLI 应用，运行在 Node.js 上，通过 Anthropic Messages API（及其他兼容 LLM）驱动 AI agent 在终端中执行编程任务。

## 1.2 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | TypeScript (Node.js) |
| Web 框架 | **无** — 纯 CLI |
| ORM / 数据库 | **无** — JSON 文件持久化 |
| 缓存 | **无外部缓存** — 内存 Map + 文件缓存（MCP 协议缓存、token 缓存） |
| 消息队列 | **无** — 同步循环 |
| LLM 调用 | 原生 `fetch` 调用 Anthropic Messages API（兼容 OpenAI/DeepSeek/Gemini 等） |
| Schema 验证 | Zod |
| 进程管理 | `child_process` (spawn/execFile) |
| 终端 UI | 自定义 TTY raw mode 渲染 |
| 容器化 | **无 Dockerfile** |

## 1.3 目录结构

```
src/
├── index.ts            ← 入口 main()
├── tty-app.ts          ← TTY 交互模式（主 UI 循环）
├── agent-loop.ts       ← Agent 核心循环（工具调用/重试/上下文管理）
├── anthropic-adapter.ts ← Anthropic API 适配器
├── mock-model.ts       ← Mock 模型（测试模式）
├── config.ts           ← 配置加载/合并（多层 settings 合并）
├── tool.ts             ← ToolRegistry（工具注册/执行/生命周期）
├── permissions.ts      ← 权限管理器（路径/命令/编辑 沙箱）
├── session.ts          ← 会话持久化（JSONL 追加写入）
├── prompt.ts           ← System Prompt 构建器
├── skills.ts           ← SKILL.md 发现与加载
├── mcp.ts              ← MCP 协议客户端（stdio/streamable-http）
├── manage-cli.ts       ← CLI 管理命令（mcp/skills 增删查）
├── cli-commands.ts     ← 交互斜杠命令（/help /model /status 等）
├── background-tasks.ts ← 后台任务注册/轮询
├── workspace.ts        ← 工作区路径解析
├── history.ts          ← 命令历史
├── file-review.ts      ← 文件修改审查
├── install.ts          ← 安装引导
├── types.ts            ← 核心类型定义
├── mcp-status.ts       ← MCP 状态摘要
├── local-tool-shortcuts.ts ← 本地工具快捷方式
├── ui.ts               ← 终端渲染函数
├── compact/            ← 上下文压缩子系统（5种策略）
│   ├── auto-compact.ts   ← LLM 摘要压缩
│   ├── compact.ts        ← 压缩核心逻辑
│   ├── constants.ts      ← 所有阈值常量
│   ├── context-collapse.ts ← 上下文折叠（最复杂的策略）
│   ├── manual-compact.ts ← 手动压缩
│   ├── microcompact.ts   ← 微压缩（清除旧工具输出）
│   ├── prompt.ts         ← 压缩提示词
│   └── snipCompact.ts    ← 无模型快照删除
├── tools/              ← 内置工具集（12个工具）
│   ├── index.ts          ← 工具注册入口
│   ├── ask-user.ts       ← 向用户提问
│   ├── edit-file.ts      ← 精确文本替换
│   ├── grep-files.ts     ← ripgrep 搜索
│   ├── list-files.ts     ← 目录列表
│   ├── load-skill.ts     ← 加载 SKILL.md
│   ├── modify-file.ts    ← 全文替换（含 diff 审查）
│   ├── patch-file.ts     ← 多补丁应用
│   ├── read-file.ts      ← 文件读取
│   ├── run-command.ts    ← 命令执行（含后台任务）
│   ├── web-fetch.ts      ← 网页抓取
│   └── web-search.ts     ← 网页搜索
├── tui/                ← 终端 UI 组件
│   ├── index.ts
│   ├── chrome.ts         ← UI 边框/装饰
│   ├── input.ts          ← 输入处理
│   ├── input-parser.ts   ← 输入解析（剪贴板/特殊键）
│   ├── markdown.ts       ← Markdown 渲染
│   ├── screen.ts         ← 屏幕管理
│   ├── transcript.ts     ← 对话记录渲染
│   └── types.ts
└── utils/              ← 工具函数
    ├── context.ts        ← 模型 max_output_tokens 解析
    ├── errors.ts         ← 错误类型检测
    ├── model-context.ts  ← 模型上下文窗口配置
    ├── token-estimator.ts ← Token 估计算法
    ├── tool-result-storage.ts ← 大工具结果持久化
    └── web.ts
```

## 1.4 启动链路

```
main()
  ├── parseArgs (--resume, --fork)
  ├── maybeHandleManagementCommand()  ← 管理子命令（minicode mcp/skills）
  │     → 直接退出
  ├── loadRuntimeConfig()            ← 配置合并链
  │     ~/.mini-code/settings.json
  │     > ~/.claude/settings.json
  │     > .mcp.json (project)
  │     > ~/.mini-code/mcp.json
  │     > process.env
  ├── createDefaultToolRegistry()    ← 12个内置工具 + skills 发现
  ├── hydrateMcpTools()             ← MCP 服务器连接（异步非阻塞）
  ├── new PermissionManager(cwd)    ← 加载权限持久化
  ├── new AnthropicModelAdapter()   ← 模型适配器初始化
  ├── buildSystemPrompt()           ← 构建系统提示词
  │
  ├── [交互模式] → runTtyApp()
  │     ├── TTY raw mode
  │     ├── resume session / fork session
  │     ├── 事件循环（键盘输入 → agent turn → 渲染）
  │     └── 持续运行直到 /exit
  │
  └── [管道模式] → readline 循环
        ├── /exit 退出
        ├── /collapse 手动折叠
        ├── 斜杠命令处理
        └── runAgentTurn() 每轮
```

## 1.5 模块划分

### 入口/编排层
- `index.ts` — 主入口，参数解析，模式分发
- `tty-app.ts` — TTY 交互主循环

### Agent 核心层
- `agent-loop.ts` — Agent 循环核心
- `anthropic-adapter.ts` — LLM 适配器
- `mock-model.ts` — 测试用 Mock 模型

### 工具系统层
- `tool.ts` — ToolRegistry
- `tools/*.ts` — 12 个内置工具

### MCP 集成层
- `mcp.ts` — MCP 协议客户端（stdio/streamable-http）

### 上下文管理层
- `compact/*.ts` — 5 种压缩策略

### 会话与持久化层
- `session.ts` — JSONL 会话持久化
- `history.ts` — 命令历史

### 安全层
- `permissions.ts` — 路径/命令/编辑沙箱

### 配置层
- `config.ts` — 多层配置合并

### TUI 层
- `tui/*.ts`, `ui.ts` — 终端渲染

### 工具函数层
- `utils/*.ts` — token 估算、上下文窗口、大结果存储等
