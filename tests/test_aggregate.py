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


def test_aggregate_drops_llm_findings_outside_changed_files() -> None:
    report = aggregate_report(
        pr={"html_url": "https://github.com/org/repo/pull/3", "title": "Change app", "body": ""},
        files=[{"filename": "src/app.py", "additions": 1, "deletions": 0}],
        commits=[],
        comments=[],
        findings=[
            Finding(
                path="tests/ (推测)",
                line=None,
                severity="medium",
                category="test",
                confidence=0.8,
                evidence=["PR 描述"],
                problem="模型推测的非变更路径",
                suggestion="补测试",
                blocking=False,
                source="llm",
            ),
            Finding(
                path="src/app.py",
                line=None,
                severity="low",
                category="maintainability",
                confidence=0.7,
                evidence=["+return value"],
                problem="当前文件建议",
                suggestion="调整当前文件",
                blocking=False,
                source="llm",
            ),
        ],
        limitations=[],
    )

    assert [finding.path for finding in report.findings] == ["src/app.py"]


def test_aggregate_merges_rule_and_llm_duplicates_with_precise_line() -> None:
    report = aggregate_report(
        pr={
            "html_url": "https://github.com/org/repo/pull/4",
            "title": "Unsafe SQL",
            "body": "",
        },
        files=[{"filename": "src/app/users.py", "additions": 3, "deletions": 1}],
        commits=[],
        comments=[],
        findings=[
            Finding(
                path="src/app/users.py",
                line=31,
                severity="high",
                category="security",
                confidence=0.82,
                evidence=['+    query = f"SELECT id FROM users WHERE id = {user_id}"'],
                problem="SQL 语句疑似通过字符串拼接或插值构造，存在注入风险。",
                suggestion="改用参数化查询。",
                blocking=True,
                source="rule",
                rule_id="sql_string_interpolation",
            ),
            Finding(
                path="src/app/users.py",
                line=None,
                severity="critical",
                category="security",
                confidence=1.0,
                evidence=[
                    'query = f"SELECT id FROM users WHERE id = {user_id}"',
                    "参数类型已从 int 改为 str",
                ],
                problem="通过 f-string 将用户输入直接拼接到 SQL 查询中，导致 SQL 注入攻击风险。",
                suggestion='使用参数化查询：connection.execute("SELECT id FROM users WHERE id = ?", (user_id,))',
                blocking=True,
                source="llm",
            ),
        ],
        limitations=[],
    )

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.path == "src/app/users.py"
    assert finding.line == 31
    assert finding.severity == "critical"
    assert finding.confidence == 1.0
    assert finding.source == "rule"
    assert finding.rule_id == "sql_string_interpolation"
    assert "f-string" in finding.problem
    assert "参数化查询" in finding.suggestion
    assert len(finding.evidence) == 2
    assert report.risk_overview.critical == 1
    assert report.risk_overview.high == 0
    assert report.risk_overview.blocking == 1


def test_aggregate_merges_same_security_issue_even_when_llm_line_is_wrong() -> None:
    report = aggregate_report(
        pr={"html_url": "https://github.com/org/repo/pull/5", "title": "Unsafe SQL", "body": ""},
        files=[{"filename": "src/app/users.py", "additions": 3, "deletions": 1}],
        commits=[],
        comments=[],
        findings=[
            Finding(
                path="src/app/users.py",
                line=31,
                severity="high",
                category="security",
                confidence=0.82,
                evidence=['+    query = f"SELECT id FROM users WHERE id = {user_id}"'],
                problem="SQL 语句疑似通过字符串拼接或插值构造，存在注入风险。",
                suggestion="改用参数化查询。",
                blocking=True,
                source="rule",
                rule_id="sql_string_interpolation",
            ),
            Finding(
                path="src/app/users.py",
                line=1,
                severity="critical",
                category="security",
                confidence=1.0,
                evidence=['query = f"SELECT id FROM users WHERE id = {user_id}"'],
                problem="直接通过 f-string 拼接用户输入构造 SQL 查询，导致 SQL 注入。",
                suggestion="使用参数化查询。",
                blocking=True,
                source="llm",
            ),
        ],
        limitations=[],
    )

    assert len(report.findings) == 1
    assert report.findings[0].line == 31
    assert report.findings[0].severity == "critical"


def test_aggregate_merges_auth_removal_duplicates_with_different_evidence() -> None:
    report = aggregate_report(
        pr={"html_url": "https://github.com/org/repo/pull/6", "title": "Auth removal", "body": ""},
        files=[{"filename": "src/app/main.py", "additions": 3, "deletions": 2}],
        commits=[],
        comments=[],
        findings=[
            Finding(
                path="src/app/main.py",
                line=7,
                severity="high",
                category="security",
                confidence=0.82,
                evidence=["-from .auth import require_admin"],
                problem="鉴权或权限检查相关代码被删除，可能扩大访问权限。",
                suggestion="恢复权限校验。",
                blocking=True,
                source="rule",
                rule_id="auth_check_removed",
            ),
            Finding(
                path="src/app/main.py",
                line=None,
                severity="critical",
                category="security",
                confidence=1.0,
                evidence=[
                    '@app.get("/admin/audit-log", dependencies=[Depends(require_admin)]) 被改为 @app.get("/admin/audit-log")'
                ],
                problem="删除 require_admin 依赖使 /admin/audit-log 端点变为公开。",
                suggestion="恢复 require_admin 依赖。",
                blocking=True,
                source="llm",
            ),
        ],
        limitations=[],
    )

    assert len(report.findings) == 1
    assert report.findings[0].line == 7
    assert report.findings[0].severity == "critical"
