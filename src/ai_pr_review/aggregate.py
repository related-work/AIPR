from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
import re
from typing import Any

from ai_pr_review.schemas import (
    AnalysisCoverage,
    ChunkSummary,
    CommentContext,
    Finding,
    ReviewReport,
    RiskOverview,
    ScopeItem,
)


SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def aggregate_report(
    *,
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    findings: list[Finding],
    limitations: list[str],
    comment_context: CommentContext | None = None,
    chunk_debug: list[ChunkSummary] | None = None,
    analysis_coverage: AnalysisCoverage | None = None,
) -> ReviewReport:
    changed_paths = {str(file.get("filename") or "") for file in files}
    filtered = [
        _calibrate_blocking(finding)
        for finding in findings
        if finding.evidence and _is_supported_path(finding, changed_paths)
    ]
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
    coverage = analysis_coverage or AnalysisCoverage()
    report = ReviewReport(
        pr_url=str(pr.get("html_url") or ""),
        title=str(pr.get("title") or ""),
        summary=summary,
        scope=_scope(files),
        risk_overview=risk,
        findings=sorted_findings,
        comment_context=comment_context or CommentContext(),
        chunk_debug=chunk_debug or [],
        analysis_coverage=coverage,
        test_suggestions=_test_suggestions(sorted_findings),
        merge_recommendation=_merge_recommendation(sorted_findings, coverage),
        limitations=_unique([*limitations, *_coverage_limitations(coverage, sorted_findings)]),
    )
    return report


def _is_supported_path(finding: Finding, changed_paths: set[str]) -> bool:
    if finding.source != "llm":
        return True
    return finding.path in changed_paths


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
    best: dict[tuple[str, int | None, str, str | None], Finding] = {}
    for finding in findings:
        key = (
            finding.path,
            finding.line,
            finding.category,
            finding.rule_id if finding.source == "rule" else None,
        )
        current = best.get(key)
        if current is None or _score(finding) > _score(current):
            best[key] = finding
    return _merge_near_duplicates(list(best.values()))


def _merge_near_duplicates(findings: list[Finding]) -> list[Finding]:
    merged: list[Finding] = []
    for finding in findings:
        for index, current in enumerate(merged):
            if _is_near_duplicate(current, finding):
                merged[index] = _merge_pair(current, finding)
                break
        else:
            merged.append(finding)
    return merged


def _is_near_duplicate(left: Finding, right: Finding) -> bool:
    if left.path != right.path or left.category != right.category:
        return False
    if _evidence_overlaps(left, right):
        return True
    if _same_security_theme(left, right):
        return True
    if left.line is not None and right.line is not None and left.line != right.line:
        return False
    left_tokens = _tokens(" ".join([left.problem, left.suggestion, *left.evidence]))
    right_tokens = _tokens(" ".join([right.problem, right.suggestion, *right.evidence]))
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap >= 3 and overlap / min(len(left_tokens), len(right_tokens)) >= 0.35


def _same_security_theme(left: Finding, right: Finding) -> bool:
    if left.category != "security":
        return False
    left_text = " ".join([left.problem, left.suggestion, *left.evidence]).lower()
    right_text = " ".join([right.problem, right.suggestion, *right.evidence]).lower()
    themes = (
        ("sql", "select", "注入", "参数化", "f-string"),
        ("require_admin", "auth", "鉴权", "权限", "admin/audit-log"),
    )
    for theme in themes:
        if any(token in left_text for token in theme) and any(token in right_text for token in theme):
            return True
    return False


def _evidence_overlaps(left: Finding, right: Finding) -> bool:
    left_fragments = [_normalize_evidence(item) for item in left.evidence]
    right_fragments = [_normalize_evidence(item) for item in right.evidence]
    for left_item in left_fragments:
        for right_item in right_fragments:
            if len(left_item) < 12 or len(right_item) < 12:
                continue
            if left_item in right_item or right_item in left_item:
                return True
            if len(_tokens(left_item) & _tokens(right_item)) >= 4:
                return True
    return False


def _merge_pair(left: Finding, right: Finding) -> Finding:
    precise = _prefer_precise_location(left, right)
    severe = _prefer_higher_severity(left, right)
    informative = _prefer_informative_text(left, right)
    source = "rule" if left.source == "rule" or right.source == "rule" else severe.source
    rule_id = left.rule_id or right.rule_id
    return precise.model_copy(
        update={
            "severity": severe.severity,
            "confidence": max(left.confidence, right.confidence),
            "evidence": _unique_evidence([*left.evidence, *right.evidence]),
            "problem": informative.problem,
            "suggestion": informative.suggestion,
            "blocking": left.blocking or right.blocking,
            "source": source,
            "rule_id": rule_id,
        }
    )


def _prefer_precise_location(left: Finding, right: Finding) -> Finding:
    if left.line is not None and right.line is None:
        return left
    if right.line is not None and left.line is None:
        return right
    if left.source == "rule" and right.source != "rule":
        return left
    if right.source == "rule" and left.source != "rule":
        return right
    return _prefer_higher_severity(left, right)


def _prefer_higher_severity(left: Finding, right: Finding) -> Finding:
    if SEVERITY_RANK[left.severity] != SEVERITY_RANK[right.severity]:
        return left if SEVERITY_RANK[left.severity] > SEVERITY_RANK[right.severity] else right
    if left.confidence != right.confidence:
        return left if left.confidence > right.confidence else right
    return left if _score(left) >= _score(right) else right


def _prefer_informative_text(left: Finding, right: Finding) -> Finding:
    left_len = len(left.problem) + len(left.suggestion)
    right_len = len(right.problem) + len(right.suggestion)
    if left_len != right_len:
        return left if left_len > right_len else right
    return _prefer_higher_severity(left, right)


def _normalize_evidence(value: str) -> str:
    return " ".join(value.replace("+", " ").replace("-", " ").split()).lower()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|[\u4e00-\u9fff]{2,}", value.lower())
        if token not in {"the", "and", "for", "with", "from", "this", "that", "return"}
    }


def _unique_evidence(items: list[str]) -> list[str]:
    result: list[str] = []
    normalized_items: list[str] = []
    for item in items:
        normalized = _normalize_evidence(item)
        if any(
            normalized == existing
            or (len(normalized) >= 12 and normalized in existing)
            or (len(existing) >= 12 and existing in normalized)
            for existing in normalized_items
        ):
            continue
        normalized_items.append(normalized)
        result.append(item)
    return result


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


def _merge_recommendation(
    findings: list[Finding],
    coverage: AnalysisCoverage | None = None,
) -> str:
    if any(finding.blocking for finding in findings):
        return "do_not_merge"
    if findings:
        return "merge_with_suggestions"
    if coverage and coverage.large_pr and coverage.coverage_ratio < 0.5:
        return "merge_with_suggestions"
    return "merge"


def _coverage_limitations(
    coverage: AnalysisCoverage,
    findings: list[Finding],
) -> list[str]:
    if findings:
        return []
    if coverage.large_pr and coverage.coverage_ratio < 0.5:
        return [
            "大 PR 深度分析覆盖率较低，未发现风险不等于完整确认安全，建议人工复查未深度分析文件"
        ]
    return []


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
