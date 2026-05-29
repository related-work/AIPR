# AI 代码评审工具产品与技术方案

文档日期：2026-05-29

## 0. 背景与目标

本工具面向 GitHub Pull Request Review 场景。用户输入 GitHub PR 链接后，系统自动获取 PR 元数据、代码变更、commit、已有评论和相关代码上下文，并调用 AI 对变更进行总结、风险识别和 Review 建议生成。

MVP 目标是提供一个命令行工具：

```bash
ai-pr-review https://github.com/org/repo/pull/123
```

默认行为是输出结构化 Review 报告，不自动写回 GitHub。后续可通过 `--post-comment` 开启自动评论。

核心设计原则：

- 只提示对 Review 有实际价值的问题，避免风格类噪音。
- 所有风险判断必须有代码位置、证据和置信度。
- 高风险优先展示，低置信度问题降级为建议或参考。
- 支持大 PR 分块分析，兼顾速度、成本和准确性。
- MVP 可在 CLI、GitHub Actions 和本地开发流程中直接落地。

## 1. 真实用户需求分析

### 1.1 开发者

开发者希望工具帮助自己在提交或请求 Review 前发现明显问题，例如遗漏测试、边界条件缺失、权限判断错误、异常处理不完整、API 不兼容等。开发者最反感的是大量无关紧要的风格建议，因为这会增加返工成本并降低对工具的信任。

开发者的核心期望：

- 快速理解 AI 认为本次 PR 做了什么。
- 明确指出真正需要修的问题，而不是泛泛而谈。
- 每条建议都包含具体位置、原因和修改方向。
- 不确定的问题要明确标注置信度，不能伪装成确定结论。

### 1.2 Tech Lead

Tech Lead 关注 PR 对系统整体的影响，包括架构边界、模块职责、公共 API、数据一致性、可观测性、性能和上线风险。相比单行代码问题，Tech Lead 更需要工具识别跨文件、跨模块、跨服务的影响。

Tech Lead 的核心期望：

- 快速判断 PR 是否可以合并。
- 优先暴露会影响线上稳定性、安全性或兼容性的风险。
- 识别测试策略是否覆盖关键路径。
- 让团队 Review 标准更一致，减少 reviewer 经验差异。

### 1.3 Reviewer

Reviewer 的主要痛点是上下文切换成本高，尤其是中大型 PR：需要阅读 PR 描述、diff、commit、历史讨论、相关文件和测试。AI 工具应充当“Review 前置摘要器”和“风险雷达”，帮助 reviewer 把注意力放在最值得看的地方。

Reviewer 的核心期望：

- 先看 PR 摘要和风险概览，再深入文件级细节。
- 明确哪些问题可能阻塞合并。
- 关联已有评论，避免重复提出已经讨论过的问题。
- 对大 PR 能分阶段、分模块输出，而不是一次性返回不可读长文。

### 1.4 开源项目维护者

开源维护者通常面对大量来自不同贡献者的 PR，时间有限，且需要保持社区友好。AI 工具应帮助维护者快速 triage：这个 PR 是否合理、是否缺测试、是否违反贡献规范、是否存在安全或兼容风险。

开源维护者的核心期望：

- 快速识别低质量、破坏性或疑似恶意 PR。
- 输出语气中立、具体、可执行，减少维护者沟通负担。
- 支持公开仓库低权限运行。
- 默认不自动发布过多 inline 评论，避免打扰贡献者。

## 2. 产品方案设计

### 2.1 核心功能

MVP 功能：

- 支持输入 GitHub PR URL。
- 获取 PR 基本信息、changed files、diff、commits、issue comments、review comments。
- 识别语言、框架、目录结构和关键配置文件。
- 对 PR 进行摘要：目的、范围、影响模块。
- 对变更进行分块分析，识别逻辑、安全、性能、并发、事务、兼容性、测试缺失、可维护性和边界条件问题。
- 输出结构化 Review 报告。
- 支持 Markdown 和 JSON 输出。

增强功能：

- `--post-comment`：将报告作为 PR comment 发布。
- `--fail-on high`：在 CI 中遇到 high/critical 阻塞问题时返回非零退出码。
- `--model fast|balanced|accurate`：控制速度、成本和准确性。
- `--changed-only`：只分析 diff。
- `--with-context`：拉取相关上下文进行深度分析。

### 2.2 用户流程

```text
用户输入 PR URL
  -> CLI 解析 owner/repo/pull_number
  -> GitHub API 拉取 PR 数据
  -> diff 分块与上下文检索
  -> 规则引擎扫描确定性问题
  -> 快速模型进行局部分析
  -> 强推理模型复核高风险问题
  -> 聚合、去重、排序
  -> 输出 Markdown/JSON 报告
  -> 可选写回 GitHub PR comment
```

### 2.3 交互方式

CLI 示例：

```bash
ai-pr-review https://github.com/org/repo/pull/123
ai-pr-review https://github.com/org/repo/pull/123 --format json
ai-pr-review https://github.com/org/repo/pull/123 --post-comment
ai-pr-review https://github.com/org/repo/pull/123 --fail-on high
```

环境变量：

```bash
export GITHUB_TOKEN=ghp_xxx
export OPENAI_API_KEY=sk_xxx
export OPENAI_FAST_MODEL=gpt-5.4-mini
export OPENAI_STRONG_MODEL=gpt-5.5
```

### 2.4 输出策略

输出分三层：

1. 决策层：PR 总结、风险总览、是否建议合并。
2. 问题层：重点问题列表，按阻塞性和风险等级排序。
3. 细节层：文件级 Review 建议、测试建议、后续改进建议。

问题类型分为：

- `must_fix`：必须修改，通常阻塞合并。
- `should_fix`：建议修改，不一定阻塞。
- `fyi`：仅供参考，不应阻塞。

## 3. 系统架构设计

### 3.1 架构图

```text
CLI / Web UI
  |
  v
PR Orchestrator
  |
  +--> GitHub Client
  |      +--> PR metadata
  |      +--> changed files
  |      +--> raw diff
  |      +--> commits
  |      +--> issue comments
  |      +--> review comments
  |
  +--> Diff Parser
  |      +--> file chunks
  |      +--> hunk chunks
  |      +--> line mapping
  |
  +--> Context Retriever
  |      +--> base/head file content
  |      +--> imported files
  |      +--> tests
  |      +--> configs
  |      +--> dependency manifests
  |
  +--> Rule Engine
  |      +--> secrets / dangerous patterns
  |      +--> missing tests
  |      +--> dependency / lockfile checks
  |
  +--> AI Analyzer
  |      +--> local chunk analysis
  |      +--> high-risk verification
  |      +--> PR-level summary
  |
  +--> Aggregator
  |      +--> dedupe
  |      +--> rank
  |      +--> confidence calibration
  |
  v
Review Output
  +--> Markdown
  +--> JSON
  +--> GitHub PR comment
```

### 3.2 模块职责

#### CLI 入口

负责参数解析、进度展示、退出码控制和结果输出。MVP 使用 Python `typer` 实现，后续可以扩展 Web UI。

#### GitHub API 接入

负责调用 GitHub REST API，拉取 PR、files、commits、comments 和 diff。使用分页、重试、rate limit 处理和 ETag 缓存。

关键接口：

- `GET /repos/{owner}/{repo}/pulls/{pull_number}`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/files`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/commits`
- `GET /repos/{owner}/{repo}/issues/{issue_number}/comments`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`
- `GET /repos/{owner}/{repo}/pulls/{pull_number}` with `Accept: application/vnd.github.diff`

#### PR Diff 获取模块

负责将 raw diff 解析为文件、hunk 和 line mapping。需要保留新增行号、旧行号、上下文行和 patch 内容，便于生成可定位评论。

#### 上下文检索模块

负责从 PR 相关文件中补充上下文，例如：

- 变更文件完整内容。
- 相邻函数或类。
- import 指向的内部文件。
- 同名或相关测试文件。
- 配置文件、路由文件、schema、迁移文件。
- package、lockfile、CI 配置和 lint/test 配置。

#### AI 分析模块

负责调用模型进行局部和全局分析。局部分析关注单个 chunk 的直接风险，全局分析关注跨文件一致性、测试覆盖、API 兼容和合并建议。

#### 结果聚合模块

负责合并规则引擎和 LLM 结果，去重、排序、置信度校准和阻塞判定。

#### Review 输出模块

负责生成 Markdown、JSON 和可选 GitHub 评论。报告默认不生成大量 inline comments，而是先生成一条总览评论；只有高置信高风险问题才适合扩展为 inline comment。

## 4. AI 分析流程设计

### 4.1 获取 PR 元数据

需要获取：

- PR title、body、author、base branch、head branch。
- labels、assignees、reviewers。
- additions、deletions、changed files。
- mergeable 状态和 CI 状态。
- commit 列表和 commit message。

用途：

- 判断 PR 意图和变更范围。
- 识别是否是 bugfix、feature、refactor、dependency update 或 test-only PR。
- 辅助模型区分“预期变更”和“风险变更”。

### 4.2 获取 changed files 和 diff

changed files 提供文件级统计和 patch，raw diff 提供完整 diff 结构。MVP 中同时获取两者：

- files API 用于文件列表、增删行数、状态、文件名。
- raw diff 用于更稳定的 hunk 解析和 line mapping。

对二进制文件、大文件、生成文件、lockfile 要特殊处理：

- 二进制文件跳过 AI 分析，只记录变更。
- 生成文件默认低优先级，除非影响发布产物。
- lockfile 结合 manifest 判断依赖变更风险。

### 4.3 识别语言、框架和目录结构

识别信号：

- 文件扩展名：`.py`、`.ts`、`.go`、`.java`、`.rs` 等。
- manifest：`package.json`、`pyproject.toml`、`go.mod`、`pom.xml`、`Cargo.toml`。
- 框架特征：Next.js、React、FastAPI、Django、Spring、Rails、NestJS 等。
- 目录：`src/`、`test/`、`migrations/`、`routes/`、`controllers/`、`services/`。

输出：

```json
{
  "languages": ["TypeScript"],
  "frameworks": ["Next.js"],
  "riskHints": ["api_route_changed", "auth_related", "missing_tests"]
}
```

### 4.4 检索相关文件、调用链、测试和配置

MVP 不需要完整代码图谱，但需要实用的启发式检索：

- 对变更文件查找同目录测试和同名测试。
- 对 import 的本地模块获取关键接口定义。
- 对 API handler 获取 route/schema/middleware。
- 对 DB 变更获取 migration/model/repository。
- 对权限相关变更获取 auth middleware 和 policy 文件。
- 对公共导出变更获取 package entry、types、README 或 API docs。

上下文预算策略：

- 小文件直接放入完整内容。
- 大文件只放变更函数、类、相邻上下文和符号签名。
- 对每个 chunk 限制上下文 token，优先放高相关文件。

### 4.5 局部分析

局部分析以 file/hunk/function 为单位。输入包括：

- PR 摘要。
- 当前文件路径、语言、框架。
- diff hunk。
- 相邻上下文。
- 相关测试和配置摘要。
- 已有评论摘要。

局部分析输出：

- 是否存在问题。
- 问题位置。
- 风险类型。
- 证据。
- 置信度。
- 修复建议。
- 是否可能阻塞合并。

### 4.6 全局聚合

全局聚合关注：

- PR 的真实目的和影响范围。
- 多个文件之间是否一致。
- API、schema、配置、测试是否同步。
- 是否存在“局部看没问题，全局有问题”的风险。

典型问题：

- 新增 API 但未加权限校验。
- 改了响应结构但未更新客户端类型。
- 改了数据库字段但未补 migration。
- 改了业务逻辑但测试只覆盖 happy path。
- 多处调用方未同步适配。

### 4.7 输出风险问题与 Review 建议

每个问题必须满足：

- 有具体文件和行号，或解释为什么只能定位到文件级。
- 有直接证据，不能只说“可能有问题”。
- 有影响说明。
- 有可执行修改建议。
- 有置信度和阻塞判断。

## 5. 模型选择与 Prompt 策略

### 5.1 模型选择

根据 OpenAI 官方文档，截至 2026-05-29，复杂推理和代码任务建议优先使用 `gpt-5.5`；如果优化延迟和成本，可选择 `gpt-5.4-mini` 或更小模型。Reasoning 模型适合复杂问题、编码和多步骤工作流，Responses API 是推荐接口。

MVP 推荐：

- 快速模型：`gpt-5.4-mini`
- 强推理模型：`gpt-5.5`
- 高成本高准确模式：`gpt-5.5` + 更高 reasoning effort

使用策略：

| 场景 | 推荐模型 | 原因 |
|---|---|---|
| PR 元数据摘要 | 快速模型 | 任务简单，追求速度 |
| 文件分类和风险初筛 | 快速模型 | 大量 chunk 并行处理 |
| 单文件常规逻辑分析 | 快速模型或中等模型 | 成本可控 |
| 安全/事务/并发/API 兼容 | 强推理模型 | 需要多步推理 |
| 高风险问题复核 | 强推理模型 | 降低误报 |
| 最终合并建议 | 强推理模型 | 需要全局权衡 |

### 5.2 分块分析

分块优先级：

1. 高风险路径：auth、payment、permission、migration、public API。
2. 大改动文件。
3. 删除测试或修改测试断言的文件。
4. 配置、依赖和 CI 变更。
5. 普通业务逻辑。

chunk 粒度：

- 小文件：整个文件 diff + 文件上下文。
- 中等文件：按函数或 hunk。
- 大文件：按 hunk + 相关函数签名。

### 5.3 长上下文处理

不要把整个仓库塞进模型。应使用“检索后生成”的方式：

- 先构建 PR index：文件、符号、风险标签、测试映射。
- 对每个 chunk 检索最相关上下文。
- 对高风险问题二次检索更深上下文。
- 最终聚合只输入摘要、候选问题和关键证据。

### 5.4 结构化 JSON 输出

OpenAI Structured Outputs 可让模型严格遵守 JSON Schema，减少解析失败和字段缺失。MVP 中所有 LLM 分析结果都使用结构化输出。

示例 schema：

```json
{
  "type": "object",
  "required": ["summary", "findings"],
  "properties": {
    "summary": { "type": "string" },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "path",
          "line",
          "severity",
          "category",
          "confidence",
          "evidence",
          "problem",
          "suggestion",
          "blocking"
        ],
        "properties": {
          "path": { "type": "string" },
          "line": { "type": ["integer", "null"] },
          "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low"]
          },
          "category": {
            "type": "string",
            "enum": [
              "logic",
              "security",
              "performance",
              "concurrency",
              "compatibility",
              "test",
              "maintainability",
              "edge_case"
            ]
          },
          "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "evidence": {
            "type": "array",
            "items": { "type": "string" }
          },
          "problem": { "type": "string" },
          "suggestion": { "type": "string" },
          "blocking": { "type": "boolean" }
        }
      }
    }
  }
}
```

### 5.5 Prompt 设计

系统 Prompt 核心要求：

```text
你是严谨的代码评审助手。只基于提供的 PR diff 和上下文判断。
不要报告纯风格问题，除非它会造成可维护性或行为风险。
没有明确证据时，不要生成 finding。
如果问题不确定，降低 confidence，并把 blocking 设为 false。
每个 finding 必须包含 path、line、severity、category、confidence、evidence、problem、suggestion、blocking。
优先识别逻辑错误、安全风险、性能问题、并发/事务问题、API 兼容性、测试缺失、边界条件遗漏。
```

局部分析用户 Prompt 模板：

```text
PR 信息：
{pr_summary}

文件：
{path}

语言/框架：
{language_framework}

Diff：
{diff_hunk}

相关上下文：
{retrieved_context}

已有评论摘要：
{comment_summary}

请输出结构化 JSON。只报告有证据、对 Review 有实际价值的问题。
```

高风险复核 Prompt：

```text
以下是候选问题。请只做复核：
1. 判断证据是否充分。
2. 判断问题是否真实可能发生。
3. 判断 severity、confidence、blocking 是否过高。
4. 删除纯猜测、重复、风格类或已被上下文否定的问题。

候选问题：
{candidate_findings}

补充上下文：
{deep_context}
```

### 5.6 避免模型臆测

机制：

- Prompt 明确“只基于提供内容”。
- 输出必须包含证据数组。
- 无证据 finding 在聚合阶段删除。
- 低置信度不能阻塞合并。
- 高风险 finding 必须经过复核模型或规则确认。
- 报告中保留“分析限制”部分，说明未获取到的上下文。

## 6. 误报与漏报控制方案

### 6.1 基于证据的判断

每条 finding 至少要有一种证据：

- diff 中的具体新增/删除代码。
- 相关上下文中的调用方、接口定义或配置。
- 测试文件缺失或断言变化。
- 已有评论或 PR 描述中的明确事实。
- 规则引擎扫描结果。

没有证据的问题不进入最终报告。

### 6.2 置信度评分

建议评分标准：

| confidence | 含义 | 默认处理 |
|---|---|---|
| 0.85-1.00 | 证据充分，风险路径清晰 | 可标记阻塞 |
| 0.70-0.84 | 较可信，但仍需人工确认 | should_fix 或 must_fix |
| 0.50-0.69 | 有风险信号，但证据不足 | should_fix |
| < 0.50 | 仅提醒 reviewer 留意 | fyi |

### 6.3 多轮校验

流程：

1. 快速模型生成候选问题。
2. 规则引擎补充确定性问题。
3. 聚合器删除无位置、无证据、重复问题。
4. 强推理模型复核高风险问题。
5. 最终按风险和置信度排序。

### 6.4 规则引擎 + LLM 结合

规则适合发现确定性模式：

- 明文密钥、token、private key。
- SQL 字符串拼接。
- 关闭鉴权或删除权限校验。
- 删除测试或降低断言强度。
- manifest 和 lockfile 不一致。
- 数据迁移文件缺失。
- 危险依赖升级。

LLM 适合判断上下文相关问题：

- 业务逻辑是否破坏不变量。
- API 兼容性是否受影响。
- 并发、事务、幂等性风险。
- 测试是否覆盖关键路径。
- 变更是否符合 PR 目标。

### 6.5 阻塞策略

只有满足以下条件的问题才建议阻塞合并：

- severity 为 `critical` 或 `high`。
- confidence 大于等于 0.75。
- 有明确代码位置和证据。
- 可能导致安全、数据损坏、线上故障、严重兼容破坏或关键测试缺失。

不应阻塞：

- 纯风格问题。
- 低置信度猜测。
- 仅可维护性轻微优化。
- 已被已有评论或后续 commit 解决的问题。

## 7. 输出格式设计

### 7.1 Markdown 报告

```md
# AI PR Review

## PR 总结

- 目的：...
- 范围：...
- 主要影响模块：...
- 分析限制：...

## 改动范围

| 模块 | 文件数 | 说明 |
|---|---:|---|
| API | 3 | 新增订单查询接口 |
| Tests | 1 | 增加部分单测 |

## 风险总览

- Critical：0
- High：2
- Medium：3
- Low：1
- 阻塞问题：2
- 合并建议：暂不建议合并

## 重点问题列表

| 等级 | 位置 | 置信度 | 阻塞 | 摘要 |
|---|---|---:|---|---|
| high | src/payment/service.py:87 | 0.91 | 是 | 扣款流程缺少事务保护 |

## 文件级 Review 建议

### src/payment/service.py

- [must_fix] line 87
  - 风险类型：concurrency / transaction
  - 问题原因：...
  - 证据：...
  - 修改建议：...
  - 是否阻塞：是

## 测试建议

- 增加并发扣款测试。
- 增加失败回滚测试。
- 增加权限不足场景测试。

## 是否建议合并

暂不建议合并。需要先修复 2 个 high 风险问题。

## 后续改进建议

- 为支付模块建立事务边界测试模板。
- 将权限校验规则加入团队 Review 规则。
```

### 7.2 JSON 报告

```json
{
  "pr": {
    "url": "https://github.com/org/repo/pull/123",
    "title": "Add payment refund API",
    "summary": "新增退款接口并调整支付服务"
  },
  "scope": [
    {
      "module": "payment",
      "files": 4,
      "description": "支付和退款逻辑"
    }
  ],
  "riskOverview": {
    "critical": 0,
    "high": 2,
    "medium": 3,
    "low": 1,
    "blocking": 2
  },
  "findings": [
    {
      "path": "src/payment/service.py",
      "line": 87,
      "severity": "high",
      "category": "concurrency",
      "confidence": 0.91,
      "blocking": true,
      "problem": "扣款和状态更新不在同一个事务中",
      "evidence": ["..."],
      "suggestion": "将扣款、状态更新和事件发送放入统一事务边界，或引入 outbox 模式"
    }
  ],
  "testSuggestions": [
    "增加并发退款测试",
    "增加事务回滚测试"
  ],
  "mergeRecommendation": "do_not_merge"
}
```

## 8. MVP 实现方案

### 8.1 技术选型

推荐 Python 实现 MVP。

理由：

- CLI 生态成熟，`typer` 和 `rich` 可快速构建良好命令行体验。
- `pydantic` 适合定义和校验 LLM 结构化输出。
- `httpx` 适合 GitHub API 调用。
- `unidiff` 可用于 diff 解析。
- 后续接入 CI、GitHub Actions 和企业脚本环境成本低。

### 8.2 选型依据

#### 8.2.1 产品入口：优先 CLI，而不是先做 Web 平台

MVP 优先选择 CLI，原因是 AI PR Review 的第一批核心用户通常是开发者、Reviewer 和 CI 维护者，他们已经在终端、GitHub Actions 或本地脚本中工作。CLI 可以用最短路径验证核心能力：给定 PR URL，获取上下文，输出 Review 报告。

不优先做 Web 平台的原因：

- Web 平台需要用户系统、OAuth、任务队列、数据库、前端交互和部署运维，验证成本高。
- 在核心 Review 准确性尚未验证前，过早做平台会把资源消耗在非核心体验上。
- CLI 更容易嵌入现有研发流程，例如 pre-review、本地脚本和 CI。

升级条件：

- 团队需要多人共享报告、历史趋势、规则配置和审计记录时，再扩展 Web UI。
- 需要自动响应 GitHub webhook 时，再演进为 GitHub App 后端服务。

#### 8.2.2 语言与运行时：优先 Python，而不是 Node.js

Python 更适合作为 MVP 的默认实现语言。该工具的主要复杂度在 API 编排、文本处理、diff 解析、结构化数据校验、规则扫描和 LLM 调用，Python 在这些方面开发效率高，生态成熟。

选择 Python 的依据：

- `typer` 和 `rich` 能快速实现可用的 CLI 和进度展示。
- `pydantic` 适合定义 LLM 输出 schema，并在聚合前做强校验。
- `httpx` 对 REST API、超时、重试和异步扩展支持较好。
- Python 更容易和 Semgrep、CodeQL wrapper、脚本化 CI 任务集成。
- 企业环境中 Python 脚本和命令行工具接受度高。

Node.js 也可行，尤其适合未来做 Web 控制台或 GitHub App 服务。但对 MVP 来说，Node.js 的优势主要在前端和同构生态，而不是 diff 分析和规则编排本身。因此建议先用 Python 快速验证核心 Review 能力；如果后续需要 Web 产品，再把核心能力封装为服务接口，前端或 GitHub App 可以用 Node.js/TypeScript 实现。

#### 8.2.3 GitHub 接入：优先 REST API，而不是 GraphQL 或本地 clone

MVP 优先使用 GitHub REST API。

选择 REST API 的依据：

- PR、changed files、commits、review comments、issue comments 都有直接端点，能力覆盖 MVP 需求。
- REST API 对分页、权限、错误处理和调试更直观。
- 可以通过 diff media type 获取 PR diff，便于保留 GitHub 的行号映射。
- 对公开仓库可以低门槛运行，对私有仓库只需要最小 read 权限 token。

不优先 GraphQL 的原因：

- GraphQL 适合一次性聚合复杂对象，但 schema 查询和分页复杂度更高。
- 对 diff 和 patch 内容的处理不如 REST files/diff 路径直接。
- MVP 需要的是稳定、易调试、低实现成本，而不是极致减少请求数。

不默认本地 clone 的原因：

- clone 大仓库成本高，对 CLI 首次体验不友好。
- 企业私有仓库可能有网络、凭证和子模块问题。
- MVP 的核心判断主要基于 PR diff 和少量相关上下文，通过 API 拉取即可。

升级条件：

- 需要精确调用图、跨仓库引用或运行静态分析时，可增加 shallow clone。
- 需要复杂批量字段聚合时，可引入 GraphQL 优化请求数量。

#### 8.2.4 Diff 处理：REST files + raw diff 双通道

MVP 同时使用 changed files API 和 raw diff。

选择双通道的依据：

- files API 提供文件状态、增删行数、patch、raw_url 和 blob_url，适合文件级统计和上下文获取。
- raw diff 更适合统一解析 hunk、line mapping 和跨文件 diff 结构。
- 两者互补，可以提高行号定位和异常处理能力。

设计取舍：

- 只用 files API：实现简单，但 patch 可能受长度限制，且复杂 diff 的结构化处理较弱。
- 只用 raw diff：适合解析，但缺少文件级元数据和 GitHub 提供的 URL 信息。
- 双通道：实现略复杂，但更稳定，适合作为 Review 工具的基础数据层。

#### 8.2.5 上下文检索：启发式检索优先，而不是一开始建设完整 RAG

MVP 采用启发式上下文检索：根据文件路径、import、测试命名、配置文件和风险标签拉取少量高相关文件。

选择启发式检索的依据：

- PR Review 的大部分高价值问题与变更文件、相邻代码、测试、配置和依赖声明强相关。
- 不需要预先索引整个仓库即可运行，适合一次性 CLI 场景。
- 对中小 PR 的准确性、速度和成本平衡较好。

不优先完整 RAG 的原因：

- RAG 需要索引、存储、更新策略、权限隔离和召回评估，工程成本高。
- 如果没有良好的代码切分和符号索引，简单 embedding 检索容易召回噪音。
- MVP 阶段更需要验证“AI Review 判断是否可靠”，而不是先建设复杂检索平台。

升级条件：

- PR 涉及大型单体仓库、跨模块调用和历史上下文时，引入代码索引。
- 需要团队级长期使用时，建设 embedding + 符号表 + 历史 Review 的 RAG。

#### 8.2.6 AI 接口：优先 OpenAI Responses API + Structured Outputs

MVP 优先使用 OpenAI Responses API，并要求模型通过 Structured Outputs 返回 JSON。

选择依据：

- Responses API 适合多步骤、工具化和结构化输出场景。
- Structured Outputs 可以约束模型返回符合 JSON Schema 的结果，减少解析失败、字段缺失和类型错误。
- Review finding 天然是结构化数据，需要稳定字段：位置、风险等级、置信度、证据、建议和阻塞判断。

不使用自由文本作为内部结果的原因：

- 难以稳定聚合、去重和排序。
- 难以在 CI 中基于严重程度做退出码判断。
- 难以自动生成 GitHub inline comment 或统计趋势。

#### 8.2.7 模型策略：快速模型初筛 + 强推理模型复核

MVP 不建议对所有内容都使用最强模型。推荐使用快速模型处理大部分 chunk，再用强推理模型复核高风险候选和生成最终合并建议。

选择依据：

- PR Review 的输入量可能很大，全部使用强模型会增加延迟和成本。
- 很多 chunk 只是常规改动，快速模型足以完成摘要和低风险判断。
- 安全、事务、并发、兼容性和跨文件问题需要更强推理能力，应该把预算集中在这些位置。

默认策略：

- `gpt-5.4-mini`：文件分类、PR 摘要、chunk 初筛、低风险建议。
- `gpt-5.5`：高风险问题复核、跨文件分析、最终合并建议。

这类分层策略比“单模型全量分析”更适合实际工程场景，因为它把成本花在最可能影响合并决策的地方。

#### 8.2.8 规则引擎：必须与 LLM 结合，而不是完全依赖 LLM

MVP 应内置轻量规则引擎，并与 LLM 结果合并。

选择依据：

- 密钥泄露、SQL 拼接、权限删除、测试删除、manifest/lockfile 不一致等问题更适合规则检测。
- 规则引擎可解释、稳定、便宜，能降低漏报。
- LLM 擅长结合上下文解释风险和生成修复建议，能降低纯规则扫描的噪音。

边界划分：

- 规则引擎负责“确定性风险信号”。
- LLM 负责“上下文判断和修复建议”。
- 聚合器负责“去重、降噪、置信度校准和阻塞判定”。

#### 8.2.9 输出策略：默认报告型输出，而不是默认大量 inline 评论

MVP 默认输出一份 Markdown 报告，不自动发布大量 inline comments。

选择依据：

- AI Review 初期应降低打扰成本，避免在 PR 中制造评论噪音。
- 报告型输出适合 reviewer 先整体判断，再选择需要跟进的问题。
- 自动 inline comment 对行号准确性、语气、重复评论和误报控制要求更高，应在准确性稳定后再开启。

默认建议：

- 本地 CLI：输出 Markdown。
- CI：输出 Markdown + JSON artifact。
- GitHub App：默认 summary comment。
- inline comment：仅用于高置信、高风险、可定位的问题。

#### 8.2.10 数据存储：MVP 无数据库，优先无状态运行

MVP 不引入数据库，运行时只使用内存和可选本地缓存。

选择依据：

- CLI 一次性运行天然适合无状态设计。
- 无数据库可以降低安装、部署和权限管理成本。
- 早期重点是 Review 准确性，不是历史分析和团队看板。

升级条件：

- 需要历史趋势、团队规则学习、报告审计和多用户协作时，引入数据库。
- 需要仓库级 RAG 时，引入向量库和代码索引存储。

#### 8.2.11 配置方式：环境变量 + 配置文件

MVP 使用环境变量保存密钥，使用 `.ai-pr-review.yml` 保存团队规则。

选择依据：

- `GITHUB_TOKEN` 和 `OPENAI_API_KEY` 符合 CLI 与 CI 常见实践。
- 配置文件适合声明忽略路径、风险目录、阻塞阈值、模型策略和团队规则。
- 配置与代码仓库绑定，便于团队共享 Review 策略。

示例：

```yaml
models:
  fast: gpt-5.4-mini
  strong: gpt-5.5

review:
  fail_on: high
  ignore_paths:
    - "dist/**"
    - "generated/**"
  high_risk_paths:
    - "src/auth/**"
    - "src/payment/**"
    - "migrations/**"

rules:
  require_tests_for:
    - "src/payment/**"
    - "src/api/**"
```

#### 8.2.12 总体取舍

本方案的核心取舍是：先用低部署成本的 CLI 验证 Review 准确性，用 REST API 和启发式上下文检索降低实现复杂度，用结构化输出和规则引擎保证可控性，再把强推理模型预算集中到真正高风险的问题上。

这不是最终形态，而是适合 MVP 的工程路径。后续当准确性、团队使用频率和自动化需求被验证后，再演进到 GitHub App、Web 控制台、RAG 代码库索引和多模型交叉验证。

依赖建议：

```toml
[project]
dependencies = [
  "typer>=0.12",
  "rich>=13.0",
  "httpx>=0.27",
  "pydantic>=2.0",
  "unidiff>=0.7",
  "openai>=1.0"
]
```

### 8.3 代码结构

```text
ai-pr-review/
  pyproject.toml
  README.md
  src/ai_pr_review/
    __init__.py
    cli.py
    github.py
    diff_parser.py
    context.py
    rules.py
    prompts.py
    llm.py
    aggregate.py
    render.py
    schemas.py
  tests/
    test_parse_pr_url.py
    test_diff_parser.py
    test_aggregate.py
```

### 8.4 核心数据结构

```python
from pydantic import BaseModel, Field
from typing import Literal


Severity = Literal["critical", "high", "medium", "low"]
Category = Literal[
    "logic",
    "security",
    "performance",
    "concurrency",
    "compatibility",
    "test",
    "maintainability",
    "edge_case",
]


class Finding(BaseModel):
    path: str
    line: int | None
    severity: Severity
    category: Category
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    problem: str
    suggestion: str
    blocking: bool


class ChunkAnalysis(BaseModel):
    summary: str
    findings: list[Finding]


class ReviewReport(BaseModel):
    pr_url: str
    title: str
    summary: str
    scope: list[str]
    findings: list[Finding]
    test_suggestions: list[str]
    merge_recommendation: Literal[
        "merge",
        "merge_with_suggestions",
        "do_not_merge",
    ]
```

### 8.5 GitHub Client 示例

```python
import httpx


class GitHubClient:
    def __init__(self, token: str | None):
        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}" if token else "",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            timeout=30,
        )

    def get_pr(self, owner: str, repo: str, number: int) -> dict:
        return self._get(f"/repos/{owner}/{repo}/pulls/{number}")

    def list_pr_files(self, owner: str, repo: str, number: int) -> list[dict]:
        return self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/files")

    def list_pr_commits(self, owner: str, repo: str, number: int) -> list[dict]:
        return self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/commits")

    def list_issue_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        return self._paginate(f"/repos/{owner}/{repo}/issues/{number}/comments")

    def list_review_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        return self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/comments")

    def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        response = self.client.get(
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.diff"},
        )
        response.raise_for_status()
        return response.text

    def _get(self, path: str) -> dict:
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def _paginate(self, path: str) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            response = self.client.get(path, params={"per_page": 100, "page": page})
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            items.extend(batch)
            page += 1
        return items
```

### 8.6 CLI 编排伪代码

```python
import os
import typer

app = typer.Typer()


@app.command()
def review(
    pr_url: str,
    post_comment: bool = False,
    output_format: str = "markdown",
    fail_on: str | None = None,
):
    ref = parse_pr_url(pr_url)
    gh = GitHubClient(token=os.getenv("GITHUB_TOKEN"))

    pr = gh.get_pr(ref.owner, ref.repo, ref.number)
    files = gh.list_pr_files(ref.owner, ref.repo, ref.number)
    commits = gh.list_pr_commits(ref.owner, ref.repo, ref.number)
    diff = gh.get_pr_diff(ref.owner, ref.repo, ref.number)
    comments = (
        gh.list_issue_comments(ref.owner, ref.repo, ref.number)
        + gh.list_review_comments(ref.owner, ref.repo, ref.number)
    )

    chunks = build_chunks(diff, files)
    repo_context = retrieve_context(gh, ref, files, pr)

    rule_findings = run_rules(files, diff, repo_context)
    chunk_results = analyze_chunks(chunks, repo_context)

    candidates = collect_candidates(rule_findings, chunk_results)
    verified = verify_high_risk_findings(candidates, repo_context)

    report = aggregate_report(
        pr=pr,
        files=files,
        commits=commits,
        comments=comments,
        findings=verified,
    )

    rendered = render_json(report) if output_format == "json" else render_markdown(report)
    typer.echo(rendered)

    if post_comment:
        gh.create_issue_comment(ref.owner, ref.repo, ref.number, rendered)

    if should_fail_ci(report, fail_on):
        raise typer.Exit(code=1)
```

### 8.7 LLM 调用伪代码

```python
from openai import OpenAI


client = OpenAI()


def analyze_chunk(chunk, context, model: str) -> ChunkAnalysis:
    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": REVIEW_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": build_chunk_prompt(chunk, context),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "chunk_analysis",
                "strict": True,
                "schema": CHUNK_ANALYSIS_JSON_SCHEMA,
            }
        },
    )
    return ChunkAnalysis.model_validate(response.output_parsed)
```

### 8.8 MVP 里程碑

第一阶段：本地 CLI 可用。

- 支持 PR URL 解析。
- 支持 GitHub API 获取 PR、files、commits、comments、diff。
- 支持 diff chunking。
- 支持调用 LLM 输出 JSON。
- 支持 Markdown 报告。

第二阶段：准确性增强。

- 增加规则引擎。
- 增加上下文检索。
- 增加高风险复核。
- 增加去重和置信度校准。

第三阶段：工程化。

- 支持 GitHub Actions。
- 支持 `--post-comment`。
- 支持缓存和并发。
- 支持配置文件 `.ai-pr-review.yml`。

## 9. 速度、成本和准确性平衡

### 9.1 速度

- 文件分块并行分析。
- 大文件只取相关上下文。
- 先用快速模型初筛。
- 对无风险 chunk 不进入强推理复核。
- 使用 GitHub API 缓存和 ETag。

### 9.2 成本

- 默认不使用强模型分析所有 chunk。
- 生成文件、lockfile、纯文档变更使用规则或摘要，不做深度分析。
- 使用 token budget 控制每个 chunk 上下文。
- 对重复文件模式复用摘要。

### 9.3 准确性

- 对高风险候选进行二次复核。
- 引入规则引擎补充确定性问题。
- 要求所有 finding 带证据和置信度。
- 使用结构化输出降低解析错误。
- 记录分析限制，避免给用户过度确定的结论。

## 10. 未来扩展方向

### 10.1 GitHub App 集成

将 CLI 逻辑封装为服务，由 GitHub App 监听 `pull_request`、`pull_request_review_comment`、`synchronize` 事件。使用 installation token，按仓库配置最小权限。

### 10.2 自动 PR 评论

支持三种评论模式：

- summary-only：只发布总览。
- blocking-only：只发布阻塞问题。
- inline：对高置信高风险问题发布 inline comment。

默认推荐 summary-only，避免噪音。

### 10.3 企业私有代码库支持

- 支持 GitHub Enterprise Server。
- 支持私有模型网关或兼容 OpenAI API 的模型服务。
- 支持日志脱敏和审计。
- 支持只在企业网络内运行。

### 10.4 多模型交叉验证

对 critical/high 问题使用多个模型或多个 prompt 视角复核。只有交叉验证通过的问题才标记为阻塞。

### 10.5 RAG 代码库上下文检索

为主干代码建立索引：

- 文件级 embedding。
- 符号表和调用关系。
- 历史 PR 和 issue。
- 架构文档和团队规范。

PR Review 时按变更路径检索最相关上下文。

### 10.6 团队 Review 规则学习

从历史 Review 评论中学习团队偏好：

- 哪些问题经常被要求修改。
- 哪些建议经常被忽略。
- 不同目录的 owner 规则。
- 团队对测试、日志、错误处理、兼容性的要求。

### 10.7 与 CI/CD 集成

作为 GitHub Actions 或其他 CI step 运行：

```yaml
- name: AI PR Review
  run: ai-pr-review ${{ github.event.pull_request.html_url }} --fail-on high
```

CI 中只应让高置信高风险问题失败，避免因低置信建议阻塞研发流程。

### 10.8 安全扫描工具结合

集成：

- Semgrep：语义规则扫描。
- CodeQL：深度代码安全分析。
- gitleaks：密钥泄露检测。
- dependency review：依赖漏洞。
- SBOM：供应链风险。

LLM 的角色是解释扫描结果、结合上下文降噪、生成修复建议，而不是替代确定性安全工具。

## 11. 关键技术依据

- GitHub REST API 支持获取 Pull Request、PR files、PR commits、review comments 和 issue comments，并支持通过 diff media type 获取 PR diff。
- OpenAI 官方文档建议复杂推理和代码任务使用强推理模型，低延迟和低成本场景使用较小模型。
- OpenAI Structured Outputs 可以让模型输出符合 JSON Schema 的结构化结果，适合本工具的 finding/report 数据契约。

参考链接：

- GitHub Pull Requests REST API: https://docs.github.com/en/rest/pulls/pulls
- GitHub Pull Request Review Comments REST API: https://docs.github.com/en/rest/pulls/comments
- GitHub Issue Comments REST API: https://docs.github.com/en/rest/issues/comments
- OpenAI Models: https://platform.openai.com/docs/models
- OpenAI Reasoning Models: https://platform.openai.com/docs/guides/reasoning
- OpenAI Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
