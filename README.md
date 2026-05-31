# Coding-Agent

AI 终端编程助手。在命令行中与 LLM 协作完成代码阅读、搜索、编辑、命令执行等开发任务，支持多模型适配、上下文压缩、MCP 协议扩展、权限沙箱与终端全屏交互。

## 特性

- **Agent 自愈恢复**：自动检测模型空响应、推理中断等异常，区分截断恢复与空响应重试，内建次数上限与诊断透出，长链路任务在模型输出不稳定时自动恢复无须人工介入
- **多层上下文压缩**：四层渐进式压缩 Pipeline，按上下文利用率阈值分级触发裁剪删除、占位清理、LLM 摘要折叠与全文压缩；核心设计为投影视图与真相源分离——模型侧看到压缩后的摘要，用户侧转录完整保留原始内容，压缩不丢失原始信息
- **Skill 系统**：多源分层发现引擎，按 project → user → compat 四层优先级扫描 `SKILL.md` 并同名去重；元数据注册与 System Prompt 构建完全解耦，实际内容通过 `load_skill` 工具按需注入，避免 Skill 常驻占用上下文窗口
- **MCP 多服务器扩展**：双传输 JSON-RPC 2.0 客户端（Stdio 帧协议 + Streamable HTTP），支持协议类型自动探测与协商结果本地缓存；多服务器并行启动、单点故障隔离，外部工具通过 `mcp__server__tool` 命名空间统一注册，同时支持 resources/prompts 发布
- **决策链式权限系统**：将 workspace 豁免、Session 记忆、持久化记忆与交互审批四层决策解耦为独立处理器；内置危险命令模式识别（11 类），支持 7 级审批粒度（单次/回合/全局允许/附带反馈拒绝/永久拒绝），权限跨会话持久化
- **精确 Token 计数**：基于 tiktoken 的 BPE 编码替代字符数估算，结合 API 返回的 provider usage 实现混合计数——已知消息零误差、尾部新增消息精确补齐，上下文利用率判断准确
- **终端全屏交互**：基于 rich + prompt_toolkit 构建 TTY 全屏界面，支持对话转录滚动、斜杠命令补全、输入历史与权限审批弹窗
- **大工具结果治理**：超大输出自动落盘保存，上下文内替换为短预览与文件路径占位符，批量结果按字符数预算控制

## 架构概览

```
main.py                         ← CLI 入口（模式分发）
├── agent/                      ← Agent 核心
│   ├── loop.py                     Async Generator Agent Loop
│   └── events.py                   AgentEvent 类型
├── context/                    ← 上下文压缩 Pipeline
│   ├── pipeline.py                 压缩策略编排器
│   ├── strategy.py                 统一 CompactionStrategy 接口
│   ├── groups.py                   公共消息分组逻辑
│   ├── snip.py                     SnipCompact（裁剪删除）
│   ├── micro.py                    Microcompact（占位清理）
│   ├── collapse.py                 ContextCollapse（LLM 折叠）
│   └── auto.py                     AutoCompact（全文摘要）
├── commands/                   ← 斜杠命令插件系统
│   ├── registry.py                装饰器注册 + 自动补全
│   └── builtin/basic.py           7 个内置命令
├── config/                     ← 配置层
│   ├── settings.py                pydantic-settings 多层合并
│   └── paths.py                   路径常量
├── infra/                      ← 基础设施
│   ├── types.py                   Pydantic 消息模型
│   ├── errors.py                  异常层级
│   ├── tokens/counter.py          tiktoken 精确计数 + 上下文窗口
│   └── storage/large_results.py   大结果持久化
├── mcp/                        ← MCP 协议集成
│   ├── client.py                  McpClient 抽象接口
│   ├── stdio.py                   Stdio 帧协议客户端
│   ├── http_client.py             Streamable HTTP 客户端
│   ├── proxy.py                   工具代理 + resources/prompts
│   └── auth.py                    Bearer Token 管理
├── model/                      ← 模型适配层
│   └── anthropic.py              Anthropic SDK 封装
├── perm/                       ← 权限系统
│   ├── manager.py                PermissionManager 公共 API
│   ├── chain.py                  决策链引擎
│   ├── classifier.py             危险命令模式识别
│   ├── store.py                  权限持久化
│   └── handlers/                 5 个独立决策处理器
├── skills/                     ← Skill 系统
│   ├── discover.py               多源分层发现
│   └── installer.py              安装/卸载管理
├── tools/                      ← 工具层
│   ├── definition.py             ToolDefinition + ToolRegistry
│   ├── workspace.py              路径解析
│   ├── diff.py                   修改审查
│   └── builtin/                  12 个内置工具
└── ui/                         ← 交互层
    ├── protocol.py               UserInterface 抽象协议
    ├── pipe/app.py               PipeUI（管道模式）
    └── tty/                      TtyUI（全屏终端）
```

## 快速开始

### 环境要求

- Python >= 3.12
- [ripgrep](https://github.com/BurntSushi/ripgrep)（可选，用于代码搜索）

### 安装

```bash
# 克隆仓库
git clone <repo-url> mini-code
cd mini-code

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e .
```

### 配置

在 `~/.mini-code/settings.json` 中配置模型和认证：

```json
{
  "model": "claude-sonnet-4-6",
  "apiKey": "sk-ant-..."
}
```

支持的配置来源（优先级从低到高）：

1. `~/.claude/settings.json` — 兼容 Claude Code 配置
2. `~/.mini-code/settings.json` — 用户级配置
3. `.mcp.json` — 项目级 MCP 服务器
4. `~/.mini-code/mcp.json` — 全局 MCP 服务器
5. 环境变量（`MINI_CODE_MODEL` / `ANTHROPIC_API_KEY` 等）

### 使用

```bash
# 交互模式（TTY 全屏终端）
python -m main

# 管道模式（单次请求）
echo "读取 README.md 并总结" | python -m main

# 恢复会话
python -m main --resume

# 分支会话
python -m main --fork <session-id>
```

### 交互命令

在交互模式中，输入以 `/` 开头触发斜杠命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/tools` | 列出已注册的工具 |
| `/status` | 显示当前模型与配置 |
| `/model [name]` | 查看或切换模型 |
| `/skills` | 列出已发现的 Skill |
| `/mcp` | 查看 MCP 服务器连接状态 |
| `/exit` | 退出 |

## 配置 MCP 服务器

在 `.mcp.json` 或 `~/.mini-code/mcp.json` 中配置：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/path/to/project"]
    },
    "remote-api": {
      "url": "https://mcp.example.com/api",
      "headers": {
        "X-API-Key": "your-key"
      },
      "protocol": "streamable-http"
    }
  }
}
```

支持两种传输方式：
- **Stdio**：本地子进程通信，支持 content-length / newline-json 帧协议自动协商
- **Streamable HTTP**：远程 HTTP 通信，支持 Bearer Token 鉴权

## 配置 Skill

Skill 是位于 `.mini-code/skills/<name>/SKILL.md` 或 `~/.mini-code/skills/<name>/SKILL.md` 的 Markdown 文件，按优先级分层扫描。

```bash
# 安装 Skill
python -m main skills add ./my-skill --name my-skill

# 列出已发现的 Skill
python -m main skills list
```

## 内置工具

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件内容，支持 offset/limit |
| `write_file` | 写入文件 |
| `edit_file` | 精确文本替换 |
| `modify_file` | 全文替换（展示 diff） |
| `patch_file` | 多补丁应用 |
| `list_files` | 列出目录内容 |
| `grep_files` | 文件内容搜索 |
| `run_command` | 允许列表命令执行 |
| `web_fetch` | 网页内容抓取 |
| `web_search` | DuckDuckGo 搜索 |
| `ask_user` | 向用户发起澄清提问 |

## 项目结构

```
.
├── main.py                 # CLI 入口
├── pyproject.toml          # 项目配置与依赖
├── agent/                  # Agent 核心循环
├── context/                # 上下文压缩 Pipeline
├── commands/               # 斜杠命令
├── config/                 # 配置管理
├── infra/                  # 基础设施（类型、Token、存储）
├── mcp/                    # MCP 协议
├── model/                  # 模型适配
├── perm/                   # 权限控制
├── skills/                 # Skill 系统
├── tools/                  # 工具注册与实现
└── ui/                     # 交互层（TTY / Pipe）
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 代码检查
ruff check .
```

