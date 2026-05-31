# AI PR Review

AI PR Review 是一个本地优先的 GitHub Pull Request 智能代码评审工具。它支持命令行和本地 Web 控制台两种使用方式，可以自动读取 PR 元数据、变更文件、diff、commit、评论上下文，并结合规则引擎与大模型生成结构化 Review 报告。

默认情况下，本工具只在本地输出报告，不会写回 GitHub。只有显式启用 `--post-comment` 或 `--post-inline-comments` 时才会向 GitHub 发表评论。

## 核心能力

- 输入 GitHub PR URL 后自动拉取 PR 信息、变更文件、commit、issue comments、review comments 和 raw diff。
- 输出 Markdown 或 JSON 格式 Review 报告。
- 支持规则引擎扫描常见高风险问题。
- 支持 OpenAI API 或兼容大模型 API。
- 支持大 PR 分块分析和分析覆盖率展示。
- 支持本地 Web 控制台运行 Review、查看历史、查看 diff、批量 Review 和 PR 监控。
- 支持 GitHub PR 浏览：输入用户名或组织，读取仓库和 PR。
- 支持 PR 浏览页直接多选 PR 并进入批量 Review。
- 支持批量 Review 后在报告页直接切换本批次全部报告。
- 支持 Watcher 监控仓库 PR，发现新 PR 或 head SHA 变化后自动创建本地 Review 任务。
- 支持本地历史记录、报告导出、质量评测、配置诊断和大模型 smoke test。
- 支持可选 GitHub summary comment 和 guarded inline review comments。

## 适用场景

- 开发者提交 PR 前自查风险。
- Reviewer 快速理解 PR 改动范围和潜在问题。
- Tech Lead 批量检查多个 PR 的风险概况。
- 开源项目维护者在合并前辅助判断是否需要阻塞。
- 演示或比赛场景中展示 AI 代码评审完整链路。

## 快速开始

下面的步骤适合第一次拉取项目后快速验证 CLI 和 Web 控制台。

### 1. 准备环境

```bash
python --version
pip install -e .
```

项目要求 Python 3.11 或更高版本。若使用 conda，推荐单独创建环境：

```bash
conda create -n aipr python=3.11 -y
conda activate aipr
pip install -e .
```

### 2. 配置 GitHub 和模型

公开仓库可以不配置 `GITHUB_TOKEN`，但建议配置以避免 rate limit：

```bash
export GITHUB_TOKEN=ghp_xxx
export OPENAI_API_KEY=sk_xxx
export OPENAI_MODEL=gpt-4.1-mini
```

如果使用兼容 OpenAI 的网关：

```bash
export OPENAI_BASE_URL=https://your-gateway.example.com/v1
export OPENAI_API_MODE=chat
export OPENAI_MODEL=your-model
```

### 3. 运行一次 CLI Review

```bash
ai-pr-review https://github.com/org/repo/pull/123 --format markdown
```

没有模型密钥时，可以先只验证规则引擎：

```bash
ai-pr-review https://github.com/org/repo/pull/123 --no-llm
```

### 4. 启动 Web 控制台

```bash
cd frontend
npm install
npm run build
cd ..
ai-pr-review web
```

浏览器打开：

```text
http://127.0.0.1:8765
```

### 5. 演示路径

建议按下面顺序演示：

1. 在 `本地配置` 页面运行配置诊断。
2. 在 `PR 浏览` 页面输入 GitHub 用户或组织，选择仓库和 PR。
3. 对单个 PR 运行 Review，查看结构化报告和 diff。
4. 在报告页查看风险概览、finding、证据和合并建议。
5. 勾选多个 PR 进入 `批量 Review`。
6. 展示批量报告切换。
7. 创建一个 Watcher，演示仓库 PR 监控配置。
8. 打开 `质量评测` 页面运行本地固定评测集。

## 当前边界

- 这是本地工具，不是多用户 Web 平台。
- 没有数据库，运行状态和报告保存在本地文件中。
- 不默认写回 GitHub。
- 不替代人工 Review，只做证据驱动的辅助判断。
- 大 PR 会受预算限制，低覆盖率时需要人工重点复核。

## 技术栈

后端和 CLI：

- Python 3.11+
- Typer
- Rich
- HTTPX
- Pydantic v2
- unidiff
- OpenAI Python SDK
- PyYAML

前端：

- Vue 3
- Vite
- lucide-vue
- markdown-it

## 架构设计

AI PR Review 按本地优先的方式组织，核心链路是：

```text
GitHub PR URL
  -> GitHubClient 拉取 PR 元数据、文件、diff、commit、评论上下文
  -> diff_parser 拆分文件、hunk 和 chunk
  -> chunk_priority / chunk_budget 排序并控制大 PR 分析预算
  -> rules 运行确定性规则扫描
  -> llm 对高价值 chunk 做模型分析
  -> evidence 校验 finding 证据是否来自 diff
  -> aggregate 合并、去重、排序并生成风险概览
  -> render 输出 Markdown / JSON
  -> comments / inline_comments 可选写回 GitHub
```

CLI 和 Web 共用同一套评审核心逻辑。Web 控制台只负责本地任务编排、状态保存和页面展示，不绕过 CLI 的安全默认值。

### 后端模块职责

| 模块 | 职责 |
| --- | --- |
| `cli.py` | 命令行入口、参数解析、Review 主流程编排。 |
| `github.py` | GitHub API 调用、PR URL 解析、diff 和评论上下文拉取。 |
| `diff_parser.py` | 将 raw diff 拆成文件、hunk、chunk。 |
| `chunk_priority.py` | 根据路径、变更类型和风险信号排序 chunk。 |
| `chunk_budget.py` | 控制大 PR 文件数、chunk 数和 patch 行数预算。 |
| `rules.py` | 运行不依赖 LLM 的确定性风险规则。 |
| `llm.py` | 调用 OpenAI 或兼容模型 API，解析结构化 finding。 |
| `evidence.py` | 校验 finding 引用的证据是否存在于 diff。 |
| `aggregate.py` | 合并规则和 LLM findings，计算风险概览和合并建议。 |
| `render.py` | 输出 Markdown 和 JSON 报告。 |
| `comments.py` | 构建 summary comment。 |
| `inline_comments.py` | 将高置信阻塞 finding 映射为 GitHub inline comments。 |
| `doctor.py` | 配置诊断和模型 smoke test。 |
| `quality_eval.py` | 本地固定评测集、质量评分和快照对比。 |
| `web.py` | 本地 HTTP API、Review job、批量任务、Watcher 和静态资源服务。 |

### 前端模块职责

| 组件 | 职责 |
| --- | --- |
| `App.vue` | 单页应用状态、API 调用和页面切换。 |
| `AppShell.vue` | 顶层布局和导航。 |
| `RepoBrowser.vue` | GitHub owner/repo/PR 浏览和多选。 |
| `ReviewRunner.vue` | 单 PR Review 参数表单和运行入口。 |
| `BatchReviewPanel.vue` | 批量 Review 队列和结果汇总。 |
| `WatcherPanel.vue` | PR Watcher 创建、启动、暂停和检查。 |
| `ReportViewer.vue` | Markdown/JSON 报告、diff、inline preview 和批次切换。 |
| `HistoryPanel.vue` | 本地历史记录列表、重跑、删除和导出。 |
| `QualityEvalPanel.vue` | 质量评测运行、快照保存和对比。 |
| `SettingsPanel.vue` | 本地配置诊断和模型 smoke test。 |
| `CommandModal.vue` | 命令和快捷入口。 |
| `HelpPanel.vue` | 参数和功能帮助。 |

## 目录结构

```text
.
├── README.md
├── pyproject.toml
├── .ai-pr-review.example.yml
├── src/ai_pr_review/
│   ├── cli.py
│   ├── github.py
│   ├── diff_parser.py
│   ├── context.py
│   ├── rules.py
│   ├── prompts.py
│   ├── llm.py
│   ├── aggregate.py
│   ├── render.py
│   ├── web.py
│   ├── doctor.py
│   ├── quality_eval.py
│   └── schemas.py
├── frontend/
│   ├── package.json
│   ├── src/
│   └── dist/
└── tests/
```

本地运行数据默认保存在：

```text
.ai-pr-review/
├── runs/          # Review 历史报告
├── watchers/      # PR watcher 状态
└── quality-eval/  # 质量评测快照
```

这些目录被 `.gitignore` 忽略，不会提交到仓库。

## 安装

推荐使用已有 conda 环境：

```bash
conda activate aipr
pip install -e .
```

安装前端依赖并构建 Web 资源：

```bash
cd frontend
npm install
npm run build
cd ..
```

## 配置

### 方式一：环境变量

```bash
export GITHUB_TOKEN=ghp_xxx
export OPENAI_API_KEY=sk_xxx
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_MODE=auto
export OPENAI_MODEL=your-default-model
export OPENAI_FAST_MODEL=your-fast-model
export OPENAI_STRONG_MODEL=your-strong-model
```

说明：

- `GITHUB_TOKEN` 用于访问私有仓库、提高 GitHub API rate limit、写回评论。
- 公开仓库可以不配置 `GITHUB_TOKEN`，但匿名 API 限流更严格。
- `OPENAI_API_KEY` 用于大模型分析。
- 不配置 `OPENAI_API_KEY` 时，工具仍可运行规则引擎，但会跳过 LLM 分析。
- `OPENAI_BASE_URL` 支持 OpenAI 官方 API 或兼容网关。
- 兼容网关通常建议以 `/v1` 结尾。
- `OPENAI_API_MODE=auto` 会先尝试 Responses API，再降级到 Chat Completions。
- 兼容网关如果不完整支持 Responses API，建议使用 `OPENAI_API_MODE=chat`。

### 常用环境变量

| 变量 | 说明 |
| --- | --- |
| `GITHUB_TOKEN` | GitHub 访问令牌，用于私有仓库、提高 rate limit 和写回评论。 |
| `OPENAI_API_KEY` | 模型 API key。 |
| `OPENAI_BASE_URL` | OpenAI 或兼容网关地址，兼容网关通常以 `/v1` 结尾。 |
| `OPENAI_API_MODE` | `auto`、`responses` 或 `chat`。 |
| `OPENAI_MODEL` | 默认模型。 |
| `OPENAI_FAST_MODEL` | `--model fast` 使用的模型。 |
| `OPENAI_STRONG_MODEL` | `--model accurate` 使用的模型。 |
| `AI_PR_REVIEW_CONFIG` | 指定额外配置文件路径。 |

### 方式二：本地私密配置文件

复制示例文件：

```bash
cp .ai-pr-review.example.yml .ai-pr-review.local.yml
```

然后编辑 `.ai-pr-review.local.yml`：

```yaml
credentials:
  github_token: ghp_xxx

openai:
  api_key: sk_xxx
  model: your-default-model
  base_url: https://api.openai.com/v1
  api_mode: auto
  timeout_seconds: 45
```

`.ai-pr-review.local.yml` 已被 `.gitignore` 忽略，请不要提交。

### 最小可用配置

只检查公开仓库且不使用 LLM：

```bash
ai-pr-review https://github.com/org/repo/pull/123 --no-llm
```

检查公开仓库并启用 LLM：

```bash
export OPENAI_API_KEY=sk_xxx
ai-pr-review https://github.com/org/repo/pull/123
```

检查私有仓库：

```bash
export GITHUB_TOKEN=ghp_xxx
export OPENAI_API_KEY=sk_xxx
ai-pr-review https://github.com/org/private-repo/pull/123
```

### 配置优先级

密钥优先级：

```text
环境变量 > .ai-pr-review.local.yml > .ai-pr-review.yml
```

模型优先级：

```text
OPENAI_FAST_MODEL / OPENAI_STRONG_MODEL > OPENAI_MODEL > openai.model > models.fast / models.strong
```

## CLI 使用

最简单的用法：

```bash
ai-pr-review https://github.com/org/repo/pull/123
```

如果没有安装 console script，也可以用模块方式：

```bash
PYTHONPATH=src python -m ai_pr_review https://github.com/org/repo/pull/123
```

常用命令：

```bash
ai-pr-review https://github.com/org/repo/pull/123 --format markdown
ai-pr-review https://github.com/org/repo/pull/123 --format json
ai-pr-review https://github.com/org/repo/pull/123 --changed-only
ai-pr-review https://github.com/org/repo/pull/123 --with-context
ai-pr-review https://github.com/org/repo/pull/123 --no-llm
ai-pr-review https://github.com/org/repo/pull/123 --llm-max-chunks 2
ai-pr-review https://github.com/org/repo/pull/123 --max-files 80 --max-chunks 40
ai-pr-review https://github.com/org/repo/pull/123 --fail-on high
```

写回 GitHub：

```bash
ai-pr-review https://github.com/org/repo/pull/123 --post-comment
ai-pr-review https://github.com/org/repo/pull/123 --post-inline-comments
```

写回说明：

- `--post-comment` 会创建一个 PR summary comment。
- `--post-inline-comments` 只会把 high/critical、blocking、高置信、能映射到新增 diff 行的问题写成 GitHub inline review comment。
- 默认不会写回 GitHub。

## CLI 参数说明

| 参数 | 说明 |
| --- | --- |
| `--format markdown\|json` | 输出 Markdown 或 JSON 报告。 |
| `--post-comment` | 将完整 Review 报告写成 GitHub PR 评论。 |
| `--post-inline-comments` | 将高置信阻塞问题写成 GitHub inline review comments。 |
| `--fail-on critical\|high\|medium\|low` | CI 场景下，当阻塞 finding 达到阈值时返回非零退出码。 |
| `--model fast\|balanced\|accurate` | 选择模型档位。 |
| `--changed-only` | 只分析 PR diff，不拉取相关上下文。 |
| `--with-context` | 启用启发式上下文检索。 |
| `--no-llm` | 跳过大模型，只运行规则引擎。 |
| `--llm-max-chunks N` | 限制送入 LLM 的 chunk 数量。 |
| `--max-files N` | 限制进入深度分析的高优先级文件数。 |
| `--max-chunks N` | 限制候选 diff chunk 数量。 |
| `--max-context-files N` | 限制上下文文件数量。 |
| `--max-patch-lines-per-chunk N` | 控制单个 chunk 的 patch 行数预算。 |
| `--debug-chunks` | 在报告中输出 chunk 排序和选择原因。 |

## Web 控制台

启动本地 Web：

```bash
PYTHONPATH=src python -m ai_pr_review web --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765
```

也可以指定前端资源目录：

```bash
PYTHONPATH=src python -m ai_pr_review web --frontend-dir frontend/dist
```

### Web 页面

Web 控制台包含以下页面：

- `PR 浏览`：输入 GitHub 用户或组织，读取仓库和 PR。
- `Review 运行`：配置单个 PR Review 参数并运行。
- `批量 Review`：选择多个 PR 后按队列逐个运行。
- `PR 监控`：持续轮询仓库 PR，发现新 PR 或 head SHA 变化后自动创建本地 Review。
- `报告结果`：查看结构化报告、原始输出、JSON、变更代码 diff、inline 评论预览。
- `历史记录`：查看本地 Review 历史、重跑、删除、导出。
- `质量评测`：运行本地固定评测集并保存/对比快照。
- `本地配置`：检查 GitHub/OpenAI 配置和大模型连通性。
- `帮助`：查看常用参数说明。

### Web API 概览

Web 控制台通过本地 HTTP API 工作。常用接口包括：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查。 |
| `POST` | `/api/reviews` | 创建单 PR Review job。 |
| `GET` | `/api/reviews/{id}` | 查询 Review job 状态。 |
| `GET` | `/api/history` | 查询本地 Review 历史。 |
| `GET` | `/api/history/{id}` | 读取某次历史报告。 |
| `DELETE` | `/api/history/{id}` | 删除本地历史报告。 |
| `GET` | `/api/github/repos?owner=OWNER` | 查询用户或组织仓库。 |
| `GET` | `/api/github/pulls?owner=OWNER&repo=REPO` | 查询仓库 PR。 |
| `POST` | `/api/batches` | 创建批量 Review。 |
| `GET` | `/api/batches/{id}` | 查询批量 Review 状态。 |
| `GET` | `/api/watchers` | 查询 watcher 列表。 |
| `POST` | `/api/watchers` | 创建 watcher。 |
| `POST` | `/api/watchers/{id}/start` | 启动 watcher。 |
| `POST` | `/api/watchers/{id}/pause` | 暂停 watcher。 |
| `POST` | `/api/watchers/{id}/check` | 立即检查 watcher。 |
| `POST` | `/api/quality-eval` | 运行质量评测。 |
| `GET` | `/api/quality-eval/snapshots` | 查询质量评测快照。 |
| `POST` | `/api/doctor` | 运行配置诊断。 |

这些接口只监听本机地址，默认用于本地浏览器和本地 Python 服务通信，不设计为公网服务。

### PR 浏览

PR 浏览页支持：

- 输入 GitHub 用户或组织。
- 自动读取仓库列表。
- 选择仓库后读取 PR 列表。
- 单击 PR 标题，将其作为当前单 PR Review 目标。
- 勾选多个 PR，直接进入批量 Review。
- 全选、清空和批量审核已选 PR。

### 单 PR Review

流程：

1. 在 `PR 浏览` 里选择一个 PR，或直接在 `Review 运行` 中粘贴 PR URL。
2. 选择模型档位和分析参数。
3. 点击运行。
4. 自动进入 `报告结果` 页面。
5. 查看结构化报告、风险等级、finding、分析覆盖率和 diff。

### 批量 Review

流程：

1. 在 `PR 浏览` 中勾选多个 PR。
2. 点击 `批量审核已选`。
3. 在 `批量 Review` 页面点击 `运行选中 PR`。
4. 工具会按队列逐个运行，每个 PR 生成独立报告。
5. 批量完成后可以点击：
   - 单个结果右侧按钮：打开某一个报告。
   - `查看全部报告`：进入报告页并直接切换本批次全部报告。

批量 Review 默认不会写回 GitHub，即使单 PR 配置里打开了写回选项，批量请求也会强制关闭写回。

### PR 监控

Watcher 支持持续关注一个仓库：

- 配置 owner、repo、轮询间隔和模型档位。
- 发现新 PR 或已有 PR head SHA 变化时，自动创建本地 Review 任务。
- 支持启动、暂停、立即检查和删除。
- watcher 状态保存到 `.ai-pr-review/watchers/`。
- Web 服务重启后，watcher 会恢复为 `paused`，需要手动启动，避免重启后自动扫仓库。

### 报告结果

报告页包含：

- 运行状态和进度时间线。
- 风险总览：critical、high、medium、low、blocking。
- 合并建议：`merge`、`merge_with_suggestions` 或 `do_not_merge`。
- 按严重等级分组的 findings。
- 每条 finding 的 path、line、severity、category、confidence、evidence、problem、suggestion 和 blocking。
- 分析覆盖率：分析文件数、LLM chunk 数、规则扫描文件数、覆盖率。
- 高风险未深度分析文件列表。
- 变更代码 diff viewer。
- finding 到 diff 行的跳转。
- inline 评论预览。
- 原始输出和 JSON 输出。

批量 Review 打开的报告页还会显示本批次报告切换条，可以直接查看全部报告。

## 输出示例

Markdown 报告会包含风险概览、合并建议、发现的问题、测试建议和限制说明。典型结构如下：

```markdown
# AI PR Review Report

## Risk Overview

- Critical: 0
- High: 1
- Medium: 2
- Low: 1
- Blocking: 1

## Merge Recommendation

do_not_merge

## Findings

### High

- path: src/auth.py
- line: 42
- category: security
- confidence: 0.93
- blocking: true

Problem:
新增代码绕过了 token 校验。

Evidence:
`+ return True`

Suggestion:
恢复鉴权检查，并补充未授权访问测试。
```

JSON 报告适合 CI 或后续自动化消费：

```bash
ai-pr-review https://github.com/org/repo/pull/123 --format json > report.json
```

CI 中可以用 `--fail-on` 控制退出码：

```bash
ai-pr-review https://github.com/org/repo/pull/123 --fail-on high
```

当存在 blocking 且 severity 达到阈值时，命令返回非零退出码。

## 报告字段

JSON 报告主要包含：

```json
{
  "pr": {
    "url": "https://github.com/org/repo/pull/123",
    "title": "PR title",
    "summary": "summary"
  },
  "scope": [],
  "analysisCoverage": {},
  "riskOverview": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0,
    "blocking": 0
  },
  "findings": [],
  "testSuggestions": [],
  "mergeRecommendation": "merge",
  "limitations": []
}
```

每条 finding 包含：

```json
{
  "path": "src/app.py",
  "line": 42,
  "severity": "high",
  "category": "security",
  "confidence": 0.91,
  "evidence": ["+ risky_code()"],
  "problem": "问题原因",
  "suggestion": "修改建议",
  "blocking": true,
  "source": "llm"
}
```

## 风险等级和合并建议

风险等级：

- `critical`：极高风险，通常涉及安全、数据损坏、严重线上事故。
- `high`：高风险，可能导致安全、核心逻辑、兼容性或生产问题。
- `medium`：中风险，需要修改或补充测试，但不一定阻塞。
- `low`：低风险，通常是建议性问题。

合并建议：

- `merge`：未发现阻塞问题，可以合并。
- `merge_with_suggestions`：可以合并，但建议补充测试、人工复核或处理非阻塞问题。
- `do_not_merge`：存在阻塞问题，不建议合并。

阻塞条件通常要求：

- severity 为 `critical` 或 `high`。
- confidence 足够高。
- 有明确 evidence。
- 可能导致安全问题、数据损坏、线上故障、严重兼容性破坏或关键测试缺失。

## 规则引擎

规则引擎会在不依赖大模型的情况下扫描明确风险，包括：

- 疑似密钥泄露。
- SQL 字符串拼接。
- 删除或削弱测试。
- manifest 和 lockfile 不一致。
- 危险权限或鉴权变更。
- migration 风险。
- 高风险路径缺少测试。

规则 finding 会进入统一 finding schema，并和 LLM finding 合并、去重、排序。

## 大模型分析

模型档位：

- `fast`：优先速度和成本，适合日常快速检查。
- `balanced`：默认平衡档位。
- `accurate`：使用强模型，适合复杂、高风险 PR。

API mode：

```text
auto      先尝试 Responses API，失败后降级到 Chat Completions。
responses 只使用 Responses API。
chat      只使用 Chat Completions，适合 OpenAI-compatible gateway。
```

兼容模型或网关可能出现以下提示：

```text
Responses API 调用失败，已降级到 Chat Completions: OpenAI Responses API 未返回可解析文本
Chat Completions 返回非标准 JSON，已尝试从文本中提取 JSON
```

这通常不是最终失败，表示工具自动降级或从非标准文本中提取 JSON。如果最终报告正常生成，说明兜底成功。若要减少第一条提示，可以设置：

```bash
export OPENAI_API_MODE=chat
```

## 大 PR 处理

大 PR 不会把所有内容无差别送入模型。工具会：

- 解析 raw diff 为文件、hunk 和 chunk。
- 对文件和 chunk 进行风险排序。
- 优先分析高风险路径、鉴权、支付、数据库、测试、API 兼容性相关变更。
- 跳过或降级处理生成文件、lockfile、二进制文件、纯文档变更。
- 在报告中输出 `analysisCoverage`。
- 明确标记高风险但未深度分析的文件。

常用控制参数：

```bash
ai-pr-review PR_URL --llm-max-chunks 4
ai-pr-review PR_URL --max-files 80
ai-pr-review PR_URL --max-chunks 40
ai-pr-review PR_URL --max-context-files 20
ai-pr-review PR_URL --max-patch-lines-per-chunk 400
```

## 质量评测

运行本地固定评测集：

```bash
ai-pr-review eval
ai-pr-review eval --format json
ai-pr-review eval --fixture harmful_pr
```

评测集不访问 GitHub 或 OpenAI。它使用固定 diff 测试规则引擎和聚合逻辑，覆盖：

- 高质量 PR。
- 低质量 PR。
- 有害 PR。
- 文档-only PR。

Web 控制台的 `质量评测` 页面支持保存快照并和历史快照比较。

## 配置诊断

检查本地配置和大模型连通性：

```bash
ai-pr-review doctor
ai-pr-review doctor --format json
ai-pr-review doctor --model balanced
ai-pr-review doctor --no-smoke
```

`doctor` 会检查：

- 是否配置 GitHub token。
- 是否配置 OpenAI API key。
- base URL 形态是否像 API endpoint。
- 当前 API mode。
- fast/strong 模型名。
- 大模型 smoke test 是否通过。

`doctor` 不会输出 token 或 API key。

## GitHub 权限要求

只读取公开仓库：

- 不需要 `GITHUB_TOKEN`。
- 但容易遇到 GitHub 匿名 rate limit。

读取私有仓库：

- 需要配置 `GITHUB_TOKEN`。
- token 需要能读取对应 repo。

写回 PR 评论：

- `--post-comment` 需要 issue comment 权限。
- `--post-inline-comments` 需要 pull request review 权限。

建议遵循最小权限原则：

- 本地自查和演示：只给 public repo 读取权限即可。
- 私有仓库评审：只给目标 repo 读取权限。
- 需要写回评论时，再额外开启 issues / pull requests 写权限。
- 不要把 token 写入仓库文件、截图或报告附件。

## 隐私和本地数据

本工具是本地优先：

- 浏览器不会收到 `GITHUB_TOKEN`、`OPENAI_API_KEY` 或本地私密配置。
- Web 前端通过本地 Python 后端发起 GitHub/OpenAI 请求。
- `.ai-pr-review.local.yml` 不应提交。
- `.ai-pr-review/` 不应提交。
- 本地历史报告可能包含 PR URL、diff 片段、报告输出和代码片段。
- 如果分析私有仓库，请把 `.ai-pr-review/` 视为私密数据。

### 数据流说明

- GitHub token 只在本地后端进程中读取，用于请求 GitHub API。
- OpenAI API key 只在本地后端进程中读取，用于调用模型服务。
- 浏览器端只看到任务状态、报告内容和脱敏配置状态。
- Review 报告默认保存在本地 `.ai-pr-review/runs/`。
- Watcher 状态默认保存在本地 `.ai-pr-review/watchers/`。
- 质量评测快照默认保存在本地 `.ai-pr-review/quality-eval/`。

## 常见问题

### GitHub API rate limit

现象：

```text
API rate limit exceeded
```

处理：

- 配置 `GITHUB_TOKEN`。
- 避免短时间频繁刷新仓库和 PR。

### 大模型连接失败

现象：

```text
Connection error
```

处理：

- 检查网络。
- 检查 `OPENAI_API_KEY`。
- 检查 `OPENAI_BASE_URL`。
- 兼容网关建议 `OPENAI_BASE_URL` 以 `/v1` 结尾。
- 对兼容网关尝试 `OPENAI_API_MODE=chat`。

### Responses API 降级提示

现象：

```text
Responses API 调用失败，已降级到 Chat Completions
```

说明：

- 当前网关或模型可能不完整支持 Responses API。
- 工具已自动降级到 Chat Completions。
- 如果报告正常生成，可以继续使用。
- 若想减少提示，设置 `OPENAI_API_MODE=chat`。

### 报告为空或只有规则结果

可能原因：

- 未设置 `OPENAI_API_KEY`。
- 使用了 `--no-llm`。
- `--llm-max-chunks` 太小。
- 大 PR 超出预算，部分文件只做规则扫描。

### Web 页面打开但功能失败

检查：

```bash
curl -s http://127.0.0.1:8765/api/health
ai-pr-review doctor --format json
```

如果前端资源不存在，重新构建：

```bash
cd frontend
npm run build
cd ..
PYTHONPATH=src python -m ai_pr_review web
```

### Web 端口被占用

现象：

```text
Address already in use
```

处理：

```bash
ai-pr-review web --port 8766
```

### 批量 Review 太慢

可能原因：

- PR 数量过多。
- 每个 PR 的 diff 很大。
- 模型响应慢。
- GitHub API rate limit。

处理：

- 减少一次批量选择的 PR 数。
- 使用 `fast` 模型档位。
- 降低 `llm_max_chunks`、`max_files` 或 `max_chunks`。
- 配置 `GITHUB_TOKEN`。

### Inline 评论没有写回

可能原因：

- 未开启 `--post-inline-comments`。
- finding 不是 high/critical。
- finding 不是 blocking。
- confidence 不够高。
- finding 不能映射到新增 diff 行。
- token 没有 PR review 写权限。

这是预期的保护策略，避免把低置信或无法定位的问题写成代码行评论。

## 开发和验证

安装开发依赖后，运行：

```bash
conda activate aipr
python -m pytest -q
git diff --check
python -m compileall src tests
```

前端构建：

```bash
cd frontend
npm run build
```

质量评测：

```bash
PYTHONPATH=src python -m ai_pr_review eval --format json
```

Web 验证：

```bash
PYTHONPATH=src python -m ai_pr_review web --host 127.0.0.1 --port 8765
curl -s http://127.0.0.1:8765/api/health
```

## 交付前检查

建议交付或演示前执行：

```bash
git status --short
conda run -n aipr python -m pytest -q
git diff --check
conda run -n aipr python -m compileall src tests
cd frontend && npm run build
cd ..
PYTHONPATH=src conda run -n aipr python -m ai_pr_review eval --format json
PYTHONPATH=src conda run -n aipr python -m ai_pr_review doctor --format json --model balanced
```

演示建议：

1. 打开 Web 控制台。
2. 在 `PR 浏览` 中读取仓库和 PR。
3. 选择一个高质量 PR 跑单 PR Review。
4. 查看结构化报告和变更代码。
5. 选择多个 PR 跑批量 Review。
6. 在报告页切换批量报告。
7. 展示 Watcher 监控配置。
8. 展示质量评测结果。

## 版本状态

当前版本定位为 MVP 交付版，重点覆盖：

- 可运行的 CLI。
- 可运行的本地 Web 控制台。
- GitHub PR 拉取。
- 规则引擎。
- 大模型分析。
- 结构化报告。
- 批量 Review。
- PR Watcher。
- 本地历史。
- 质量评测。

后续建议以稳定性维护、误报/漏报校准和真实 PR 回归为主，不再随意扩展大功能。
