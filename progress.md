# Coding_Agent 项目进度

## 概述

Coding_Agent 是一个 AI 终端编程助手，支持多模型适配、上下文压缩、MCP 扩展、权限沙箱与终端全屏交互。


---



### Python 迁移 — M1 基础设施 ✅

- [x] 项目脚手架：目录结构、`pyproject.toml`
- [x] `infra/types.py` — Pydantic 消息模型（discriminated union）
- [x] `infra/errors.py` — 异常层级
- [x] `infra/tokens/counter.py` — Token 精确计数 (tiktoken)
- [x] `infra/storage/large_results.py` — 大工具结果持久化
- [x] `config/settings.py` — pydantic-settings 配置加载
- [x] `tools/definition.py` — ToolDefinition + ToolRegistry
- [x] `model/anthropic.py` — Anthropic SDK 适配器
- [x] 12 个内置工具 (tools/builtin/)
- [x] `agent/loop.py` — Agent Loop (async generator)
- [x] `main.py` — CLI 入口
- [x] 管道模式最小可用闭环验证

### Python 迁移 — M2 上下文压缩 Pipeline ✅

- [x] `context/strategy.py` — 统一 CompactionStrategy 接口
- [x] `context/constants.py` — 阈值与限制常量
- [x] `context/groups.py` — 公共消息分组逻辑（消除重复）
- [x] `context/snip.py` — SnipCompact 策略
- [x] `context/micro.py` — Microcompact 策略
- [x] `context/collapse.py` — ContextCollapse 策略（投影视图）
- [x] `context/auto.py` — AutoCompact 策略
- [x] `context/pipeline.py` — Pipeline 编排器
- [x] Agent Loop 集成 Pipeline

### Python 迁移 — M3 MCP + Skill + 权限 ✅

- [x] `skills/discover.py` — 多源分层 Skill 发现 + 同名去重
- [x] `skills/installer.py` — Skill 安装/卸载管理
- [x] `perm/manager.py` — PermissionManager 公共 API
- [x] `perm/chain.py` — 决策链编排
- [x] `perm/classifier.py` — 11 类危险命令识别
- [x] `perm/store.py` — 权限 JSON 持久化
- [x] `perm/handlers/` — 5 个独立决策处理器
- [x] `mcp/client.py` — McpClient 抽象接口
- [x] `mcp/stdio.py` — Stdio 帧协议客户端 + 协议协商
- [x] `mcp/http_client.py` — Streamable HTTP 客户端
- [x] `mcp/proxy.py` — 工具代理 + resources/prompts
- [x] `mcp/auth.py` — Bearer Token 管理
- [x] `main.py` 集成 M3 全部模块

---

## 待完成

### Python 迁移 — M4~M5

- [ ] `session/` — JSONL 会话持久化
- [ ] `ui/tty/` — 终端全屏交互
- [ ] `ui/pipe/` — 管道模式
- [ ] `commands/` — 斜杠命令插件系统
- [ ] 测试覆盖

---

## 已知技术债务

| # | 来源 | 描述 | 优先级 |
|---|------|------|--------|
| 1 | phase-3 | `tty-app.ts` 单文件过大 (~2100行)，职责混杂 | 高 |
| 2 | phase-3 | 项目无任何测试 | 高 |
| 3 | phase-3 | Token 估算纯启发式（字符数/固定比率），中文误差大 | 高 |
| 4 | phase-3 | `snipCompact` 与 `context-collapse` 消息分组逻辑重复 | 高 |
| 5 | phase-3 | MCP Token 缓存无 TTL，Token 过期需重启刷新 | 高 |
| 6 | phase-3 | 权限提示同步阻塞 Agent Loop，无超时 | 中 |
| 7 | phase-3 | 模型上下文窗口配置硬编码，新增模型需改代码 | 中 |
| 8 | phase-3 | `fetch` 调用无 AbortController 超时 | 中 |
| 9 | phase-3 | MockModelAdapter 与生产逻辑脱节 | 中 |
| 10 | phase-3 | `reconstructSnippedEvents` O(n²) | 低 |
| 11 | phase-3 | 后台任务无法获取输出 | 低 |
| 12 | phase-3 | `projectDirName` 路径编码可能冲突 | 低 |

---

## 架构优化待办

Python 迁移中规划的优化（区别于原型中的问题）：

| # | 描述 | 对应文档 |
|---|------|---------|
| 1 | Async Generator Agent Loop 替代回调模式 | phase-6 §3.1 |
| 2 | 统一 CompactionStrategy 接口替代分散调用 | phase-6 §3.2 |
| 3 | 决策链权限引擎替代 if-else 链 | phase-6 §3.4 |
| 4 | 斜杠命令装饰器注册替代 switch-case | phase-6 §3.6 |
| 5 | UserInterface 协议解耦 TTY/Pipe 模式 | phase-6 §3.5 |
| 6 | tiktoken 精确计数替代字符数估算 | phase-5 §4 |
| 7 | tenacity 统一重试替代分散重试逻辑 | phase-5 §5 |
| 8 | Pydantic 序列化消除 JSONL 手写序列化代码 | phase-6 §3.3 |

---

## 已识别风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| TTY raw mode 在 Windows/Python 下行为差异 | TTY 交互可能不可用 | 优先 Unix 环境开发，prompt_toolkit 跨平台 |
| asyncio 子进程语义与 Node.js child_process 不同 | MCP stdio 客户端需重新设计流处理 | 先做 MCP 协议单测 |
| Anthropic SDK 响应格式差异 | 解析逻辑需适配 | 抽取 parse_response 为独立函数 |

---

## 里程碑规划

```
M1: 基础设施 + Agent Loop ──── 已完成 ✅
M2: 上下文压缩 Pipeline ───── 已完成 ✅
M3: MCP + Skill + 权限 ────── 已完成 ✅
M4: 终端 UI ───────────────── 待开始
M5: 会话持久化 ────────────── 待开始
```

---

*最后更新: 2026-05-25*
