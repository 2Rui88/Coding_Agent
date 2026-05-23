# Coding_Agent 项目进度

## 概述

Coding_Agent 是一个 AI 终端编程助手，支持多模型适配、上下文压缩、MCP 扩展、权限沙箱与终端全屏交互。


---



### Python 迁移 — M1 基础设施

- [x] 项目脚手架：目录结构、`pyproject.toml`
- [x] `infra/types.py` — Pydantic 消息模型（discriminated union）
- [x] `infra/errors.py` — 异常层级
- [x] `infra/tokens/counter.py` — Token 精确计数 (tiktoken)
- [ ] `infra/storage/large_results.py` — 大工具结果持久化
- [x] `config/settings.py` — pydantic-settings 配置加载
- [x] `tools/definition.py` — ToolDefinition + ToolRegistry
- [x] `model/anthropic.py` — Anthropic SDK 适配器
- [ ] 12 个内置工具
- [ ] `agent/loop.py` — Agent Loop (async generator)
- [ ] `main.py` — CLI 入口
- [ ] 管道模式最小可用闭环验证

---

## 待完成

### Python 迁移 — M2~M5

- [ ] `context/pipeline.py` — 四层压缩 Pipeline
- [ ] `context/snip.py` — SnipCompact
- [ ] `context/collapse.py` — ContextCollapse
- [ ] `perm/` — 权限决策链引擎
- [ ] `session/` — JSONL 会话持久化
- [ ] `mcp/` — 双传输 MCP 客户端
- [ ] `skills/` — Skill 发现与加载
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
M1: 基础设施 + Agent Loop ──── 当前
M2: 上下文压缩 Pipeline
M3: MCP + Skill + 权限
M4: 终端 UI
M5: 会话持久化
```

---

*最后更新: 2026-05-23*
