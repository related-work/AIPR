# 大规模 PR 与批量 PR 处理设计

## 1. 背景

AI PR Review 工具在真实使用中会遇到两类规模问题：

1. 单个 PR 很大：一次 PR 修改几十到几百个文件，diff 很长，模型上下文和成本都不可控。
2. 同一仓库同时有很多 PR：维护者希望批量了解风险，而不是逐个手动运行。

这两类问题不能用同一种方案处理。单个大 PR 的核心是“风险优先和分析预算”；多个 PR 的核心是“队列、总览和可恢复运行”。

当前项目是 local-first 工具，默认不写回 GitHub。因此本设计优先保证本地 CLI/Web 可用、低噪音、有明确覆盖率，不做 CI gate、数据库或企业级任务调度。

## 2. 设计目标

- 大 PR 不因为 diff 过长而失败。
- 分析预算可控，避免无限调用模型。
- 高风险改动优先分析，低价值改动可以跳过或仅规则扫描。
- 报告必须说明分析覆盖范围和限制，避免用户误以为已经完整分析。
- 批量 PR 运行时，每个 PR 独立保存报告，失败不影响其他 PR。
- Web 端能展示批量运行总览，快速定位最值得人工 review 的 PR。
- 默认不自动评论 GitHub；写回必须显式 opt-in。

## 3. 非目标

- 不实现分布式任务队列。
- 不引入数据库。
- 不默认分析整个仓库。
- 不默认对所有 PR 自动写评论。
- 不把模型输出作为强制合并门禁。
- 不承诺大 PR 100% 全量深度分析，而是输出清晰覆盖率和风险优先结果。

## 4. 单个大 PR 处理方案

### 4.1 总体流程

```text
获取 PR metadata
  -> 获取 changed files 和 raw diff
  -> 文件分类和风险评分
  -> 全量规则扫描
  -> diff chunk 分块
  -> 根据预算选择 chunk
  -> LLM 分析高优先级 chunk
  -> 高风险 finding 复核
  -> 聚合报告
  -> 输出覆盖率、跳过原因和限制
```

### 4.2 文件分类

每个变更文件先进入分类器，决定是否值得送入模型。

| 分类 | 示例 | 默认处理 |
| --- | --- | --- |
| 高风险业务文件 | `auth/`, `payment/`, `billing/`, `permission/`, `api/` | 优先规则扫描和 LLM 分析 |
| 数据风险文件 | migration、schema、ORM model、SQL | 优先分析 |
| 配置和部署文件 | CI、Docker、Kubernetes、Terraform、env 示例 | 优先分析 |
| 测试文件 | `test_*.py`, `*.spec.ts`, `__tests__` | 用于判断测试覆盖和测试削弱 |
| lockfile | `package-lock.json`, `poetry.lock`, `yarn.lock` | 不送模型全文，只做一致性和依赖风险检查 |
| 生成文件 | `dist/`, `build/`, minified、generated 标记 | 默认跳过 |
| 二进制文件 | 图片、字体、压缩包 | 跳过 |
| 纯文档 | Markdown、docs | 默认低优先级，除非涉及安全、部署或 API 文档 |

### 4.3 风险评分

文件和 chunk 都需要打分。分数只用于排序，不直接生成 finding。

建议初始评分：

| 条件 | 加分 |
| --- | --- |
| 路径匹配 `high_risk_paths` | +40 |
| 修改鉴权、权限、token、session、cookie | +35 |
| 修改数据库 schema、migration、事务 | +30 |
| 修改支付、账单、订单、资金相关路径 | +30 |
| 删除或削弱测试断言 | +25 |
| 新增 SQL 字符串拼接 | +25 |
| 修改公开 API、路由、SDK 类型 | +20 |
| 修改 CI/CD、部署、权限配置 | +20 |
| 大量删除代码 | +10 |
| 纯文档、生成文件、lockfile 大块文本 | -30 |

### 4.4 Chunk 分块策略

Chunk 是模型分析的最小单位，不等于 Git diff 的原始 hunk。一个 chunk 应包含：

- `path`
- `old_start` / `old_lines`
- `new_start` / `new_lines`
- `patch`
- `risk_score`
- `file_category`
- `reason`

分块规则：

- 优先按文件分组，再按 hunk 切分。
- 单个 hunk 过长时按新增/删除行数再次拆分。
- 每个 chunk 控制在模型输入预算内，例如 200 到 400 行 patch。
- 相邻小 hunk 可以合并，减少模型调用次数。
- 同一文件的高风险 chunk 保留相邻上下文，但不把整个文件塞给模型。

### 4.5 分析预算

大 PR 必须有明确预算。建议提供配置项：

```yaml
review:
  max_files: 80
  max_chunks: 40
  max_llm_chunks: 20
  max_context_files: 20
  max_patch_lines_per_chunk: 400
  large_pr_file_threshold: 30
  large_pr_line_threshold: 3000
```

CLI 参数建议：

```bash
ai-pr-review <pr-url> --max-files 80 --max-chunks 40 --llm-max-chunks 20
```

预算策略：

- 规则引擎尽量扫描全部可解析 diff。
- LLM 只分析排序后的高价值 chunk。
- 超出预算的 chunk 不静默丢弃，必须进入报告的“未深度分析”列表。
- 如果 PR 超过阈值，报告中标记为 `large_pr: true`。

### 4.6 大 PR 报告新增内容

报告需要新增“分析覆盖率”部分：

```json
{
  "analysisCoverage": {
    "largePr": true,
    "changedFiles": 126,
    "analyzedFiles": 42,
    "skippedFiles": 84,
    "totalChunks": 180,
    "llmAnalyzedChunks": 20,
    "rulesScannedFiles": 118,
    "coverageRatio": 0.33,
    "budgetLimits": {
      "maxFiles": 80,
      "maxChunks": 40,
      "maxLlmChunks": 20
    },
    "skippedReasons": [
      {
        "reason": "generated_file",
        "count": 35
      },
      {
        "reason": "over_budget_low_risk",
        "count": 49
      }
    ]
  }
}
```

Markdown 报告中展示：

- 是否为大 PR。
- 分析了多少文件和 chunk。
- 哪些文件只做了规则扫描。
- 哪些文件跳过以及原因。
- 当前结论是否受覆盖率限制。

### 4.7 大 PR 合并建议策略

如果覆盖率不足，工具不能轻易给出“完全可以合并”的结论。

建议规则：

- 有 high/critical 阻塞 finding：建议暂缓合并。
- 无阻塞 finding，但 LLM 覆盖率低于阈值：建议人工重点复查未分析高风险文件。
- 仅纯文档或低风险生成文件超预算：可以给出低风险合并建议。
- 报告必须区分“未发现风险”和“未完整分析”。

## 5. 批量 PR 处理方案

### 5.1 总体流程

```text
选择 owner/repo
  -> 拉取 open PR 列表
  -> 计算每个 PR 的规模和初步风险
  -> 用户选择要运行的 PR
  -> 后台逐个创建 review job
  -> 每个 PR 独立执行和保存结果
  -> 批量总览页展示状态、风险和建议
```

### 5.2 PR 初筛和排序

批量模式不应一开始就对所有 PR 调 LLM。应先用 GitHub metadata 和 changed files 做轻量排序。

排序信号：

| 信号 | 影响 |
| --- | --- |
| 修改高风险路径 | 提高优先级 |
| 修改文件数很少 | 可以优先快速完成 |
| 修改文件数极大 | 标记为大 PR，需要预算 |
| 修改测试或删除测试 | 提高优先级 |
| 修改依赖、CI、部署、权限 | 提高优先级 |
| 纯文档 PR | 降低优先级 |
| 已有大量 review comments | 标记已有讨论，不重复评论 |
| 草稿 PR | 默认不自动运行，除非用户选择 |

### 5.3 批量运行模式

CLI 建议：

```bash
ai-pr-review batch https://github.com/org/repo --state open
ai-pr-review batch https://github.com/org/repo --prs 12,18,23
ai-pr-review batch https://github.com/org/repo --limit 10 --model fast
```

Web 建议：

- 仓库页展示 open PR 列表。
- 用户勾选多个 PR。
- 支持“只运行选中 PR”和“运行当前筛选结果”。
- 运行队列展示每个 PR 的状态。
- 每个 PR 点击后进入独立报告页。

### 5.4 批量总览输出

批量报告不是把所有 PR 的完整报告拼在一起，而是输出总览：

| PR | 状态 | 风险 | 建议 | 阻塞问题 | 覆盖率 |
| --- | --- | --- | --- | --- | --- |
| #12 | done | high | 暂缓合并 | 2 | 80% |
| #18 | done | low | 可以合并 | 0 | 100% |
| #23 | failed | unknown | 需要重试 | 0 | 0% |
| #31 | skipped | low | 纯文档跳过 | 0 | 100% |

每个 PR 仍然保存独立 JSON/Markdown 报告，批量总览只负责 triage。

### 5.5 失败处理

- 单个 PR 失败不能中断整批任务。
- 失败原因要可读，例如 GitHub rate limit、权限不足、diff 太大、模型超时。
- 支持重试单个 PR。
- 批量运行完成后给出失败列表。
- 如果未配置 OpenAI，批量模式仍可运行规则引擎和 no-LLM 审查。

## 6. 配置设计

建议扩展 `.ai-pr-review.yml`：

```yaml
review:
  max_files: 80
  max_chunks: 40
  max_llm_chunks: 20
  max_context_files: 20
  max_patch_lines_per_chunk: 400
  large_pr_file_threshold: 30
  large_pr_line_threshold: 3000

batch:
  default_state: open
  default_limit: 20
  max_parallel_jobs: 1
  include_drafts: false
  auto_skip_docs_only: true

high_risk_paths:
  - auth/**
  - payment/**
  - billing/**
  - migrations/**
  - .github/workflows/**
```

第一阶段建议 `max_parallel_jobs` 固定为 1，避免本地资源、GitHub API 和模型 API 同时被打满。后续再考虑并发。

## 7. Web 体验设计

### 7.1 大 PR 提示

在运行配置页或报告页显示：

- “这是一个大 PR”
- 文件数、patch 行数、chunk 数。
- 当前预算。
- 是否建议切换 fast/balanced/accurate。

报告页显示：

- 覆盖率卡片。
- 已分析文件列表。
- 跳过文件列表。
- 超预算原因。
- 建议人工优先查看的未分析文件。

### 7.2 批量 PR 页面

建议新增独立页面“批量 Review”，不要塞进当前单 PR 运行页。

页面结构：

```text
左侧：仓库和筛选条件
中间：PR 列表和勾选
右侧：运行队列和结果总览
```

主要状态：

- pending
- running
- done
- failed
- skipped

### 7.3 用户默认路径

普通用户默认仍然使用单 PR review。

高级用户路径：

1. 进入仓库浏览。
2. 选择多个 PR。
3. 点击批量运行。
4. 先看总览，按风险进入单个报告。

## 8. 后端模块设计

建议新增或扩展模块：

```text
src/ai_pr_review/
  chunk_budget.py       # chunk 预算和覆盖率统计
  risk_score.py         # 文件和 chunk 风险评分
  batch.py              # 批量 PR job 编排
  schemas.py            # AnalysisCoverage, BatchReviewSummary
  web.py                # batch API 和 coverage payload
```

核心数据结构：

```python
class AnalysisCoverage(BaseModel):
    large_pr: bool
    changed_files: int
    analyzed_files: int
    skipped_files: int
    total_chunks: int
    llm_analyzed_chunks: int
    rules_scanned_files: int
    coverage_ratio: float
    skipped_reasons: list[SkippedReason]
    budget_limits: BudgetLimits


class BatchReviewItem(BaseModel):
    pr_number: int
    title: str
    url: str
    status: Literal["pending", "running", "done", "failed", "skipped"]
    risk: Literal["critical", "high", "medium", "low", "unknown"]
    merge_recommendation: str | None
    blocking_findings: int
    coverage_ratio: float | None
    report_id: str | None
    error: str | None
```

## 9. 实现顺序

### 阶段 1：Large PR 基础能力

- 增加预算配置和 CLI 参数。
- 统一 chunk 预算逻辑。
- 报告输出 `analysisCoverage`。
- Web 报告页展示覆盖率和跳过原因。
- 测试覆盖大 diff、生成文件、lockfile、纯文档和超预算场景。

建议 commit：

```text
feat: add large pr analysis coverage
```

### 阶段 2：风险优先 chunk 选择

- 文件和 chunk 风险评分。
- LLM chunk 按风险排序。
- 报告展示高风险未分析项。
- 测试覆盖 auth、migration、test deletion、docs-only 等排序场景。

建议 commit：

```text
feat: prioritize review chunks by risk
```

### 阶段 3：批量 PR 总览

- CLI `batch` 命令。
- Web 多选 PR 并创建多个 review job。
- 批量总览页。
- 单个 PR 失败不影响整批。

建议 commit：

```text
feat: add batch pr review overview
```

### 阶段 4：批量运行体验增强

- 重试单个失败 PR。
- 批量历史记录。
- 总览导出 Markdown/JSON。
- 可选并发，但默认仍保守。

建议 commit：

```text
feat: manage batch review runs
```

## 10. 测试策略

必须保持网络无关测试。

核心测试：

- 大 PR 阈值识别。
- 文件分类和跳过原因。
- chunk 分块和预算截断。
- 风险评分排序。
- 报告覆盖率 JSON 和 Markdown 渲染。
- 批量 PR 中单个失败不影响其他 PR。
- Web API payload 不暴露 token。
- 批量运行默认不写回 GitHub。

建议 fixtures：

- 超大 docs-only PR。
- 超大 generated-file PR。
- 小而高风险 auth PR。
- migration + missing test PR。
- lockfile-only PR。
- 批量 PR 列表：成功、失败、跳过、超预算混合。

## 11. 关键原则

- 大 PR 的结论必须带覆盖率。
- 未分析不等于安全。
- 规则引擎尽量全量扫，LLM 只分析高价值 chunk。
- 批量模式先做 triage，不生成一个巨大报告。
- 每个 PR 的报告独立、可复查、可导出。
- 写回 GitHub 永远显式 opt-in。
