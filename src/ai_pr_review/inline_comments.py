from __future__ import annotations

from ai_pr_review.diff_parser import DiffFile
from ai_pr_review.schemas import Finding


INLINE_SEVERITIES = {"critical", "high"}
MIN_INLINE_CONFIDENCE = 0.75


def build_inline_review_comments(
    findings: list[Finding],
    diff_files: list[DiffFile],
) -> tuple[list[dict], list[str]]:
    comments: list[dict] = []
    skipped_non_actionable = 0
    skipped_unmapped = 0

    for finding in findings:
        if not _should_post_inline(finding):
            skipped_non_actionable += 1
            continue
        if finding.line is None or not _is_added_line(diff_files, finding.path, finding.line):
            skipped_unmapped += 1
            continue
        comments.append(
            {
                "path": finding.path,
                "line": finding.line,
                "side": "RIGHT",
                "body": _comment_body(finding),
            }
        )

    limitations: list[str] = []
    if skipped_non_actionable:
        limitations.append(
            f"已跳过 {skipped_non_actionable} 条低风险、低置信度或非阻塞 finding 的 inline comment"
        )
    if skipped_unmapped:
        limitations.append(
            f"已跳过 {skipped_unmapped} 条无法映射到 diff 新增行的 inline comment"
        )
    return comments, limitations


def _should_post_inline(finding: Finding) -> bool:
    return (
        finding.blocking
        and finding.severity in INLINE_SEVERITIES
        and finding.confidence >= MIN_INLINE_CONFIDENCE
    )


def _is_added_line(diff_files: list[DiffFile], path: str, line: int) -> bool:
    for diff_file in diff_files:
        if diff_file.path != path:
            continue
        for hunk in diff_file.hunks:
            for diff_line in hunk.lines:
                if diff_line.kind == "add" and diff_line.new_line_no == line:
                    return True
    return False


def _comment_body(finding: Finding) -> str:
    evidence = "\n".join(f"- `{item}`" for item in finding.evidence[:3])
    blocking = "是" if finding.blocking else "否"
    return (
        f"**AI PR Review: {finding.severity} {finding.category}**\n\n"
        f"{finding.problem}\n\n"
        "**证据**\n"
        f"{evidence}\n\n"
        "**建议**\n"
        f"{finding.suggestion}\n\n"
        f"置信度：{finding.confidence:.2f}；阻塞合并：{blocking}。"
    )
