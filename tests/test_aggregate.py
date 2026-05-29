from __future__ import annotations

from ai_pr_review.aggregate import aggregate_report, should_fail_ci
from ai_pr_review.schemas import Finding


def test_aggregate_dedupes_drops_unsupported_and_calibrates_blocking() -> None:
    findings = [
        Finding(
            path="src/auth/service.py",
            line=10,
            severity="high",
            category="security",
            confidence=0.9,
            evidence=["removed require_admin"],
            problem="鉴权检查被删除",
            suggestion="恢复权限校验",
            blocking=False,
            source="rule",
            rule_id="auth_check_removed",
        ),
        Finding(
            path="src/auth/service.py",
            line=10,
            severity="high",
            category="security",
            confidence=0.8,
            evidence=["removed require_admin"],
            problem="重复问题",
            suggestion="恢复权限校验",
            blocking=True,
            source="llm",
        ),
        Finding(
            path="src/style.py",
            line=1,
            severity="medium",
            category="maintainability",
            confidence=0.95,
            evidence=[],
            problem="无证据问题",
            suggestion="忽略",
            blocking=True,
            source="llm",
        ),
    ]

    report = aggregate_report(
        pr={
            "html_url": "https://github.com/org/repo/pull/1",
            "title": "Tighten auth",
            "body": "Updates auth checks",
        },
        files=[{"filename": "src/auth/service.py", "additions": 2, "deletions": 1}],
        commits=[],
        comments=[],
        findings=findings,
        limitations=["未获取完整仓库上下文"],
    )

    assert len(report.findings) == 1
    assert report.findings[0].blocking is True
    assert report.risk_overview.blocking == 1
    assert report.merge_recommendation == "do_not_merge"
    assert should_fail_ci(report, "high") is True
    assert should_fail_ci(report, "critical") is False


def test_aggregate_allows_merge_with_non_blocking_suggestions() -> None:
    report = aggregate_report(
        pr={"html_url": "https://github.com/org/repo/pull/2", "title": "Docs", "body": ""},
        files=[{"filename": "README.md", "additions": 1, "deletions": 0}],
        commits=[],
        comments=[],
        findings=[
            Finding(
                path="README.md",
                line=1,
                severity="low",
                category="maintainability",
                confidence=0.8,
                evidence=["README changed"],
                problem="建议补充说明",
                suggestion="增加示例",
                blocking=False,
                source="rule",
            )
        ],
        limitations=[],
    )

    assert report.merge_recommendation == "merge_with_suggestions"
    assert should_fail_ci(report, "low") is False
