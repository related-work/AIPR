from __future__ import annotations

import json
from collections import defaultdict

from ai_pr_review.schemas import Finding, ReviewReport


MERGE_TEXT = {
    "merge": "建议合并。",
    "merge_with_suggestions": "可以合并，但建议先处理非阻塞问题。",
    "do_not_merge": "暂不建议合并，需要先处理阻塞问题。",
}


def render_markdown(report: ReviewReport) -> str:
    lines: list[str] = [
        "# AI PR Review",
        "",
        "## PR 总结",
        "",
        f"- PR：{report.pr_url}",
        f"- 标题：{report.title}",
        f"- 摘要：{report.summary}",
        "",
        "## 改动范围",
        "",
        "| 模块 | 文件数 | 说明 |",
        "|---|---:|---|",
    ]
    if report.scope:
        for item in report.scope:
            lines.append(f"| {item.module} | {item.files} | {item.description} |")
    else:
        lines.append("| 无 | 0 | 未识别到文件变更 |")

    if report.chunk_debug:
        lines.extend(
            [
                "",
                "## Chunk 调试",
                "",
                "| 选择 | 分数 | 位置 | 原因 |",
                "|---|---:|---|---|",
            ]
        )
        for item in report.chunk_debug:
            location = item.path if item.new_start is None else f"{item.path}:{item.new_start}"
            lines.append(
                f"| {'是' if item.selected else '否'} | {item.score} | "
                f"{location} | {_escape_table(', '.join(item.reasons))} |"
            )

    coverage = report.analysis_coverage
    lines.extend(
        [
            "",
            "## 分析覆盖率",
            "",
            f"- 大 PR：{'是' if coverage.large_pr else '否'}",
            f"- 变更文件：{coverage.changed_files}",
            f"- 深度分析文件：{coverage.analyzed_files} / {coverage.changed_files}",
            f"- 规则扫描文件：{coverage.rules_scanned_files}",
            f"- LLM 分析 chunk：{coverage.llm_analyzed_chunks} / {coverage.total_chunks}",
            f"- 覆盖率：{coverage.coverage_ratio:.2f}",
        ]
    )
    if coverage.budget_limits.model_dump(exclude_none=True):
        lines.extend(
            [
                "",
                "| 预算项 | 值 |",
                "|---|---:|",
            ]
        )
        budget_labels = [
            ("max_files", "max_files"),
            ("max_chunks", "max_chunks"),
            ("max_llm_chunks", "max_llm_chunks"),
            ("max_context_files", "max_context_files"),
            ("max_patch_lines_per_chunk", "max_patch_lines_per_chunk"),
        ]
        for key, label in budget_labels:
            value = getattr(coverage.budget_limits, key)
            if value is not None:
                lines.append(f"| {label} | {value} |")
    if coverage.skipped_reasons:
        lines.extend(["", "跳过/未深度分析原因："])
        lines.extend(f"- {item.reason}：{item.count}" for item in coverage.skipped_reasons)
    high_risk_unreviewed = [
        item for item in coverage.file_coverage if item.high_risk_unreviewed
    ]
    if high_risk_unreviewed:
        lines.extend(
            [
                "",
                "### 高风险未深度分析文件",
                "",
                "| 文件 | 状态 | 原因 | 风险分 | 风险信号 |",
                "|---|---|---|---:|---|",
            ]
        )
        for item in high_risk_unreviewed:
            lines.append(
                f"| {item.path} | {item.status} | {item.reason} | "
                f"{item.risk_score} | {_escape_table(', '.join(item.reasons))} |"
            )
    if coverage.file_coverage:
        lines.extend(
            [
                "",
                "### 文件覆盖明细",
                "",
                "| 文件 | 状态 | 原因 | 风险分 | 高风险未深度分析 |",
                "|---|---|---|---:|---|",
            ]
        )
        for item in coverage.file_coverage:
            lines.append(
                f"| {item.path} | {item.status} | {item.reason} | "
                f"{item.risk_score} | {'是' if item.high_risk_unreviewed else '否'} |"
            )

    risk = report.risk_overview
    lines.extend(
        [
            "",
            "## 评论上下文",
            "",
            f"- 普通评论：{report.comment_context.issue_comments}（Copilot {report.comment_context.copilot_issue_comments}）",
            f"- 行内评论：{report.comment_context.review_comments}（Copilot {report.comment_context.copilot_review_comments}）",
            f"- Review 总结：{report.comment_context.pull_reviews}（Copilot {report.comment_context.copilot_pull_reviews}）",
            "- 评论上下文仅作背景；阻塞问题必须有 diff 或代码上下文证据。",
            "",
            "## 风险总览",
            "",
            f"- Critical：{risk.critical}",
            f"- High：{risk.high}",
            f"- Medium：{risk.medium}",
            f"- Low：{risk.low}",
            f"- 阻塞问题：{risk.blocking}",
            f"- 合并建议：{MERGE_TEXT[report.merge_recommendation]}",
            "",
            "## 重点问题列表",
            "",
            "| 等级 | 位置 | 置信度 | 阻塞 | 摘要 |",
            "|---|---|---:|---|---|",
        ]
    )
    if report.findings:
        for finding in report.findings:
            lines.append(
                f"| {finding.severity} | {_location(finding)} | "
                f"{finding.confidence:.2f} | {'是' if finding.blocking else '否'} | "
                f"{_escape_table(finding.problem)} |"
            )
    else:
        lines.append("| - | - | - | - | 未发现有证据支持的风险问题 |")

    lines.extend(["", "## 文件级 Review 建议", ""])
    if report.findings:
        for path, findings in _group_by_path(report.findings).items():
            lines.append(f"### {path}")
            lines.append("")
            for finding in findings:
                label = "must_fix" if finding.blocking else "should_fix"
                lines.extend(_finding_lines(label, finding))
            lines.append("")
    else:
        lines.append("未发现需要文件级处理的问题。")
        lines.append("")

    lines.extend(["## 测试建议", ""])
    if report.test_suggestions:
        lines.extend(f"- {item}" for item in report.test_suggestions)
    else:
        lines.append("- 未识别到额外测试建议。")

    lines.extend(
        [
            "",
            "## 是否建议合并",
            "",
            MERGE_TEXT[report.merge_recommendation],
            "",
            "## 分析限制",
            "",
        ]
    )
    if report.limitations:
        lines.extend(f"- {item}" for item in report.limitations)
    else:
        lines.append("- 未记录额外限制。")
    return "\n".join(lines).rstrip() + "\n"


def render_json(report: ReviewReport) -> str:
    payload = {
        "pr": {
            "url": report.pr_url,
            "title": report.title,
            "summary": report.summary,
        },
        "scope": [item.model_dump() for item in report.scope],
        "chunkDebug": [item.model_dump() for item in report.chunk_debug],
        "analysisCoverage": report.analysis_coverage.model_dump(by_alias=True),
        "commentContext": {
            "issueComments": report.comment_context.issue_comments,
            "reviewComments": report.comment_context.review_comments,
            "pullReviews": report.comment_context.pull_reviews,
            "copilotIssueComments": report.comment_context.copilot_issue_comments,
            "copilotReviewComments": report.comment_context.copilot_review_comments,
            "copilotPullReviews": report.comment_context.copilot_pull_reviews,
        },
        "riskOverview": report.risk_overview.model_dump(),
        "findings": [finding.model_dump() for finding in report.findings],
        "testSuggestions": report.test_suggestions,
        "mergeRecommendation": report.merge_recommendation,
        "limitations": report.limitations,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _group_by_path(findings: list[Finding]) -> dict[str, list[Finding]]:
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.path].append(finding)
    return dict(grouped)


def _finding_lines(label: str, finding: Finding) -> list[str]:
    line = finding.line if finding.line is not None else "文件级"
    evidence = "; ".join(finding.evidence)
    return [
        f"- [{label}] line {line}",
        f"  - 风险类型：{finding.category}",
        f"  - 风险等级：{finding.severity}",
        f"  - 置信度：{finding.confidence:.2f}",
        f"  - 问题原因：{finding.problem}",
        f"  - 证据：{evidence}",
        f"  - 修改建议：{finding.suggestion}",
        f"  - 是否阻塞：{'是' if finding.blocking else '否'}",
    ]


def _location(finding: Finding) -> str:
    if finding.line is None:
        return finding.path
    return f"{finding.path}:{finding.line}"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
