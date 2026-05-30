from __future__ import annotations

import re

from ai_pr_review.context import RetrievedContext
from ai_pr_review.diff_parser import DiffFile
from ai_pr_review.schemas import Finding


COMMENT_OR_DESCRIPTION_MARKERS = (
    "copilot",
    "已有评论",
    "评论摘要",
    "根据评论",
    "背景信息",
    "background",
    "pr 描述",
    "pr描述",
    "pr description",
    "功能描述",
    "review comment",
    "issue comment",
    "comment summary",
)


def verify_finding_evidence(
    findings: list[Finding],
    *,
    diff_files: list[DiffFile],
    context: RetrievedContext,
) -> tuple[list[Finding], list[str]]:
    diff_by_path = {item.path: item.patch for item in diff_files}
    all_context = "\n".join(context.files.values())
    verified: list[Finding] = []
    dropped_unsupported_llm = 0
    dropped_low_confidence_llm = 0
    downgraded_blockers = 0

    for finding in findings:
        if finding.source == "rule":
            verified.append(finding)
            continue
        if finding.confidence <= 0.5:
            dropped_low_confidence_llm += 1
            continue

        diff_text = diff_by_path.get(finding.path, "")
        has_diff_evidence = _has_supported_evidence(finding, diff_text)
        has_context_evidence = _has_supported_evidence(finding, all_context)

        if not has_diff_evidence and not has_context_evidence:
            dropped_unsupported_llm += 1
            continue

        if _requires_diff_evidence(finding) and not has_diff_evidence:
            finding = finding.model_copy(
                update={
                    "severity": "medium",
                    "confidence": min(finding.confidence, 0.65),
                    "blocking": False,
                }
            )
            downgraded_blockers += 1
        verified.append(finding)

    limitations: list[str] = []
    if dropped_unsupported_llm:
        limitations.append(
            f"已丢弃 {dropped_unsupported_llm} 条缺少 diff 或上下文代码证据的 LLM finding"
        )
    if dropped_low_confidence_llm:
        limitations.append(f"已丢弃 {dropped_low_confidence_llm} 条低置信度 LLM finding")
    if downgraded_blockers:
        limitations.append(f"已降级 {downgraded_blockers} 条缺少 diff 证据的阻塞候选")
    return verified, limitations


def _requires_diff_evidence(finding: Finding) -> bool:
    return finding.blocking or finding.severity in {"critical", "high"}


def _has_supported_evidence(finding: Finding, haystack: str) -> bool:
    if not haystack:
        return False
    normalized_haystack = _normalize(haystack)
    for evidence in finding.evidence:
        if _is_comment_or_description_evidence(evidence):
            continue
        for fragment in _candidate_fragments(evidence):
            if fragment and _normalize(fragment) in normalized_haystack:
                return True
    return False


def _is_comment_or_description_evidence(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in COMMENT_OR_DESCRIPTION_MARKERS)


def _candidate_fragments(value: str) -> list[str]:
    fragments: list[str] = []
    fragments.extend(match.strip() for match in re.findall(r"`([^`]{4,})`", value))
    fragments.extend(match.strip() for match in re.findall(r'"([^"]{4,})"', value))
    fragments.extend(match.strip() for match in re.findall(r"'([^']{4,})'", value))
    stripped = value.strip()
    if len(stripped) >= 4:
        fragments.append(stripped)
    return _unique(fragment for fragment in fragments if len(fragment.strip()) >= 4)


def _normalize(value: str) -> str:
    value = value.replace("\\n", "\n")
    return " ".join(value.split()).lower()


def _unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
