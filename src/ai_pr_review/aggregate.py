from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from ai_pr_review.schemas import ChunkSummary, Finding, ReviewReport, RiskOverview, ScopeItem


SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def aggregate_report(
    *,
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    findings: list[Finding],
    limitations: list[str],
    chunk_debug: list[ChunkSummary] | None = None,
) -> ReviewReport:
    filtered = [_calibrate_blocking(finding) for finding in findings if finding.evidence]
    deduped = _dedupe_findings(filtered)
    sorted_findings = sorted(
        deduped,
        key=lambda finding: (
            not finding.blocking,
            -SEVERITY_RANK[finding.severity],
            -finding.confidence,
            finding.path,
            finding.line or 0,
        ),
    )
    risk = _risk_overview(sorted_findings)
    summary = _summary(pr, files, commits)
    report = ReviewReport(
        pr_url=str(pr.get("html_url") or ""),
        title=str(pr.get("title") or ""),
        summary=summary,
        scope=_scope(files),
        risk_overview=risk,
        findings=sorted_findings,
        chunk_debug=chunk_debug or [],
        test_suggestions=_test_suggestions(sorted_findings),
        merge_recommendation=_merge_recommendation(sorted_findings),
        limitations=_unique(limitations),
    )
    return report


def should_fail_ci(report: ReviewReport, fail_on: str | None) -> bool:
    if not fail_on:
        return False
    threshold_rank = SEVERITY_RANK[fail_on]
    finding_match = any(
        finding.blocking and SEVERITY_RANK[finding.severity] >= threshold_rank
        for finding in report.findings
    )
    if finding_match:
        return True
    if report.findings or report.risk_overview.blocking <= 0:
        return False
    overview_counts = {
        "critical": report.risk_overview.critical,
        "high": report.risk_overview.high,
        "medium": report.risk_overview.medium,
        "low": report.risk_overview.low,
    }
    return any(
        count > 0 and SEVERITY_RANK[severity] >= threshold_rank
        for severity, count in overview_counts.items()
    )


def _calibrate_blocking(finding: Finding) -> Finding:
    should_block = (
        finding.severity in {"critical", "high"}
        and finding.confidence >= 0.75
        and bool(finding.evidence)
        and finding.category
        in {"security", "logic", "concurrency", "compatibility", "test", "performance"}
    )
    if finding.blocking == should_block:
        return finding
    return finding.model_copy(update={"blocking": should_block})


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    best: dict[tuple[str, int | None, str], Finding] = {}
    for finding in findings:
        key = (finding.path, finding.line, finding.category)
        current = best.get(key)
        if current is None or _score(finding) > _score(current):
            best[key] = finding
    return list(best.values())


def _score(finding: Finding) -> tuple[int, float, int]:
    source_weight = 1 if finding.source == "rule" else 0
    return (SEVERITY_RANK[finding.severity], finding.confidence, source_weight)


def _risk_overview(findings: list[Finding]) -> RiskOverview:
    counts = Counter(finding.severity for finding in findings)
    return RiskOverview(
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
        blocking=sum(1 for finding in findings if finding.blocking),
    )


def _summary(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    commits: list[dict[str, Any]],
) -> str:
    title = str(pr.get("title") or "未命名 PR")
    body = str(pr.get("body") or "").strip()
    total_files = len(files)
    additions = sum(int(file.get("additions") or 0) for file in files)
    deletions = sum(int(file.get("deletions") or 0) for file in files)
    commit_count = len(commits)
    body_hint = f"PR 描述：{body[:160]}" if body else "PR 未提供详细描述"
    return (
        f"{title}。本次变更涉及 {total_files} 个文件，"
        f"+{additions}/-{deletions} 行，包含 {commit_count} 个 commit。{body_hint}"
    )


def _scope(files: list[dict[str, Any]]) -> list[ScopeItem]:
    by_module: dict[str, list[str]] = defaultdict(list)
    for file in files:
        path = str(file.get("filename") or "")
        module = _module_for_path(path)
        by_module[module].append(path)
    return [
        ScopeItem(module=module, files=len(paths), description=_describe_module(module))
        for module, paths in sorted(by_module.items())
    ]


def _module_for_path(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return "."
    if len(parts) >= 2 and parts[0] in {"src", "app", "lib", "packages", "services"}:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _describe_module(module: str) -> str:
    if module in {"docs", "doc"}:
        return "文档变更"
    if "test" in module:
        return "测试相关变更"
    return "代码或配置变更"


def _test_suggestions(findings: list[Finding]) -> list[str]:
    suggestions: list[str] = []
    if any(finding.category == "security" for finding in findings):
        suggestions.append("增加权限不足、未认证访问和恶意输入场景测试。")
    if any(finding.category == "concurrency" for finding in findings):
        suggestions.append("增加并发执行、重复提交和事务回滚测试。")
    if any(finding.category == "compatibility" for finding in findings):
        suggestions.append("增加 API/数据迁移向后兼容测试。")
    if any(finding.category == "test" for finding in findings):
        suggestions.append("补充覆盖本次变更核心路径的测试。")
    return _unique(suggestions)


def _merge_recommendation(findings: list[Finding]) -> str:
    if any(finding.blocking for finding in findings):
        return "do_not_merge"
    if findings:
        return "merge_with_suggestions"
    return "merge"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
