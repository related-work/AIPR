from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_pr_review.aggregate import aggregate_report
from ai_pr_review.comments import build_comment_context
from ai_pr_review.config import ReviewConfig
from ai_pr_review.diff_parser import DiffFile, parse_diff
from ai_pr_review.rules import run_rules


FixtureKind = Literal["high_quality", "low_quality", "harmful", "clean"]


class QualityFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: FixtureKind
    title: str
    description: str
    raw_diff: str
    expected_rule_ids: set[str] = Field(default_factory=set)
    allowed_rule_ids: set[str] | None = None
    config: dict = Field(default_factory=dict)


class FixtureEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str = Field(alias="fixtureId")
    kind: FixtureKind
    title: str
    passed: bool
    expected_rule_ids: set[str] = Field(alias="expectedRuleIds")
    actual_rule_ids: set[str] = Field(alias="actualRuleIds")
    missed_rule_ids: set[str] = Field(alias="missedRuleIds")
    unexpected_rule_ids: set[str] = Field(alias="unexpectedRuleIds")
    finding_count: int = Field(alias="findingCount")
    merge_recommendation: str = Field(alias="mergeRecommendation")


class QualityEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    passed: int
    failed: int
    false_positives: int = Field(alias="falsePositives")
    false_negatives: int = Field(alias="falseNegatives")
    results: list[FixtureEvaluationResult]


class QualityEvaluationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    label: str
    created_at: str = Field(alias="createdAt")
    report: QualityEvaluationReport


class FixtureSnapshotComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    fixture_id: str = Field(alias="fixtureId")
    kind: str
    base_passed: bool | None = Field(alias="basePassed")
    target_passed: bool | None = Field(alias="targetPassed")
    passed_changed: bool = Field(alias="passedChanged")
    base_actual_rule_ids: set[str] = Field(alias="baseActualRuleIds")
    target_actual_rule_ids: set[str] = Field(alias="targetActualRuleIds")
    added_rule_ids: set[str] = Field(alias="addedRuleIds")
    removed_rule_ids: set[str] = Field(alias="removedRuleIds")


class QualitySnapshotComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    base_id: str = Field(alias="baseId")
    target_id: str = Field(alias="targetId")
    delta_passed: int = Field(alias="deltaPassed")
    delta_failed: int = Field(alias="deltaFailed")
    delta_false_positives: int = Field(alias="deltaFalsePositives")
    delta_false_negatives: int = Field(alias="deltaFalseNegatives")
    fixture_changes: list[FixtureSnapshotComparison] = Field(alias="fixtureChanges")


class QualitySnapshotStore:
    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def save(
        self,
        report: QualityEvaluationReport,
        *,
        label: str | None = None,
    ) -> QualityEvaluationSnapshot:
        created_at = _now()
        snapshot_id = _snapshot_id(created_at)
        snapshot = QualityEvaluationSnapshot(
            id=snapshot_id,
            label=(label or "").strip() or f"eval {created_at}",
            createdAt=created_at,
            report=report,
        )
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path(snapshot_id).write_text(
            snapshot.model_dump_json(by_alias=True),
            encoding="utf-8",
        )
        return snapshot

    def get(self, snapshot_id: str) -> QualityEvaluationSnapshot:
        path = self._path(snapshot_id)
        if not path.exists():
            raise KeyError(snapshot_id)
        return QualityEvaluationSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list_summaries(self) -> list[dict]:
        snapshots: list[tuple[int, QualityEvaluationSnapshot]] = []
        if not self._directory.exists():
            return []
        for path in self._directory.glob("*.json"):
            try:
                snapshot = QualityEvaluationSnapshot.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                mtime_ns = path.stat().st_mtime_ns
            except (OSError, ValueError):
                continue
            snapshots.append((mtime_ns, snapshot))
        snapshots.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [_snapshot_summary(snapshot) for _, snapshot in snapshots]

    def compare(self, base_id: str, target_id: str) -> QualitySnapshotComparison:
        base = self.get(base_id)
        target = self.get(target_id)
        return compare_quality_snapshots(base, target)

    def _path(self, snapshot_id: str) -> Path:
        return self._directory / f"{snapshot_id}.json"


def builtin_quality_fixtures() -> list[QualityFixture]:
    return [
        QualityFixture(
            id="high_quality_pr",
            kind="high_quality",
            title="参数化查询并补充测试",
            description="安全修复带测试，规则引擎不应报告风险。",
            raw_diff="""diff --git a/src/users/service.py b/src/users/service.py
--- a/src/users/service.py
+++ b/src/users/service.py
@@ -1,3 +1,4 @@
 def get_user(conn, user_id):
-    return conn.execute("select * from users where id=?", (user_id,))
+    query = "select * from users where id=?"
+    return conn.execute(query, (user_id,))
diff --git a/tests/test_users.py b/tests/test_users.py
--- a/tests/test_users.py
+++ b/tests/test_users.py
@@ -1,2 +1,3 @@
 def test_get_user_uses_bound_param():
+    assert repo.get_user("u_1").id == "u_1"
     assert True
""",
        ),
        QualityFixture(
            id="low_quality_pr",
            kind="low_quality",
            title="核心支付逻辑变更但削弱测试",
            description="业务代码变更未补充测试，同时现有断言被削弱。",
            config={"rules": {"require_tests_for": ["src/payment/**"]}},
            expected_rule_ids={"missing_required_tests", "test_assertion_weakened"},
            raw_diff="""diff --git a/src/payment/service.py b/src/payment/service.py
--- a/src/payment/service.py
+++ b/src/payment/service.py
@@ -1,3 +1,4 @@
 def charge(order):
+    order.retry_count += 1
     return gateway.charge(order)
diff --git a/tests/test_payment.py b/tests/test_payment.py
--- a/tests/test_payment.py
+++ b/tests/test_payment.py
@@ -1,3 +1,3 @@
 def test_charge_success():
-    assert response.status_code == 201
+    assert response.status_code != 500
""",
        ),
        QualityFixture(
            id="harmful_pr",
            kind="harmful",
            title="移除鉴权并引入注入和凭据风险",
            description="覆盖安全、数据模型和 migration 风险。",
            expected_rule_ids={
                "auth_check_removed",
                "possible_secret",
                "sql_string_interpolation",
                "migration_risk",
            },
            raw_diff="""diff --git a/src/admin/audit.py b/src/admin/audit.py
--- a/src/admin/audit.py
+++ b/src/admin/audit.py
@@ -1,6 +1,6 @@
 def audit_log(request, user_id):
-    require_admin(request.user)
+    API_TOKEN = "prod-token-12345"
+    query = f"select * from audit_logs where user_id={user_id}"
     return db.fetch(query)
diff --git a/src/models/user.py b/src/models/user.py
--- a/src/models/user.py
+++ b/src/models/user.py
@@ -1,3 +1,4 @@
 class User:
+    deleted_at = Column(DateTime)
     pass
""",
        ),
        QualityFixture(
            id="clean_docs_pr",
            kind="clean",
            title="文档说明更新",
            description="纯文档变更不应触发代码风险。",
            raw_diff="""diff --git a/docs/review.md b/docs/review.md
--- a/docs/review.md
+++ b/docs/review.md
@@ -1,2 +1,3 @@
 # Review Guide
+Add reviewer rotation notes.
 Keep reports evidence-based.
""",
        ),
    ]


def evaluate_builtin_fixtures(fixture_id: str | None = None) -> QualityEvaluationReport:
    fixtures = builtin_quality_fixtures()
    if fixture_id and fixture_id != "all":
        fixtures = [fixture for fixture in fixtures if fixture.id == fixture_id]
        if not fixtures:
            raise ValueError(f"未知 fixture：{fixture_id}")
    return evaluate_fixtures(fixtures)


def evaluate_fixtures(fixtures: list[QualityFixture]) -> QualityEvaluationReport:
    results = [_evaluate_fixture(fixture) for fixture in fixtures]
    false_positives = sum(len(result.unexpected_rule_ids) for result in results)
    false_negatives = sum(len(result.missed_rule_ids) for result in results)
    passed = sum(1 for result in results if result.passed)
    return QualityEvaluationReport(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        falsePositives=false_positives,
        falseNegatives=false_negatives,
        results=results,
    )


def render_quality_evaluation_json(report: QualityEvaluationReport) -> str:
    return json.dumps(report.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2) + "\n"


def render_quality_evaluation_markdown(report: QualityEvaluationReport) -> str:
    lines = [
        "# AI PR Review Quality Evaluation",
        "",
        "## 总览",
        "",
        f"- Fixtures：{report.total}",
        f"- 通过：{report.passed}",
        f"- 失败：{report.failed}",
        f"- 误报：{report.false_positives}",
        f"- 漏报：{report.false_negatives}",
        "",
        "## 结果",
        "",
        "| Fixture | 类型 | 状态 | 预期 | 实际 | 漏报 | 误报 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for result in report.results:
        lines.append(
            f"| {result.fixture_id} | {result.kind} | "
            f"{'pass' if result.passed else 'fail'} | "
            f"{len(result.expected_rule_ids)} | {len(result.actual_rule_ids)} | "
            f"{len(result.missed_rule_ids)} | {len(result.unexpected_rule_ids)} |"
        )
    lines.extend(["", "## 明细", ""])
    for result in report.results:
        lines.extend(
            [
                f"### {result.fixture_id}",
                "",
                f"- 标题：{result.title}",
                f"- 合并建议：{result.merge_recommendation}",
                f"- 预期 rule：{_format_rule_ids(result.expected_rule_ids)}",
                f"- 实际 rule：{_format_rule_ids(result.actual_rule_ids)}",
                f"- 漏报：{_format_rule_ids(result.missed_rule_ids)}",
                f"- 误报：{_format_rule_ids(result.unexpected_rule_ids)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def compare_quality_snapshots(
    base: QualityEvaluationSnapshot,
    target: QualityEvaluationSnapshot,
) -> QualitySnapshotComparison:
    base_results = {result.fixture_id: result for result in base.report.results}
    target_results = {result.fixture_id: result for result in target.report.results}
    fixture_changes: list[FixtureSnapshotComparison] = []
    for fixture_id in sorted(set(base_results) | set(target_results)):
        base_result = base_results.get(fixture_id)
        target_result = target_results.get(fixture_id)
        base_actual = base_result.actual_rule_ids if base_result else set()
        target_actual = target_result.actual_rule_ids if target_result else set()
        base_passed = base_result.passed if base_result else None
        target_passed = target_result.passed if target_result else None
        if base_passed == target_passed and base_actual == target_actual:
            continue
        kind = (target_result or base_result).kind if (target_result or base_result) else "unknown"
        fixture_changes.append(
            FixtureSnapshotComparison(
                fixtureId=fixture_id,
                kind=kind,
                basePassed=base_passed,
                targetPassed=target_passed,
                passedChanged=base_passed != target_passed,
                baseActualRuleIds=base_actual,
                targetActualRuleIds=target_actual,
                addedRuleIds=target_actual - base_actual,
                removedRuleIds=base_actual - target_actual,
            )
        )
    return QualitySnapshotComparison(
        baseId=base.id,
        targetId=target.id,
        deltaPassed=target.report.passed - base.report.passed,
        deltaFailed=target.report.failed - base.report.failed,
        deltaFalsePositives=target.report.false_positives - base.report.false_positives,
        deltaFalseNegatives=target.report.false_negatives - base.report.false_negatives,
        fixtureChanges=fixture_changes,
    )


def _evaluate_fixture(fixture: QualityFixture) -> FixtureEvaluationResult:
    config = ReviewConfig.from_mapping(fixture.config)
    diff_files = parse_diff(fixture.raw_diff)
    github_files = _github_files_from_diff(diff_files)
    rule_findings = run_rules(github_files, diff_files, config)
    report = aggregate_report(
        pr={
            "html_url": f"fixture://{fixture.id}",
            "title": fixture.title,
            "body": fixture.description,
        },
        files=github_files,
        commits=[],
        comments=[],
        findings=rule_findings,
        limitations=[],
        comment_context=build_comment_context(
            issue_comments=[],
            review_comments=[],
            pull_reviews=[],
        ),
    )
    actual_rule_ids = {
        finding.rule_id for finding in report.findings if finding.rule_id is not None
    }
    allowed_rule_ids = fixture.allowed_rule_ids or fixture.expected_rule_ids
    missed = fixture.expected_rule_ids - actual_rule_ids
    unexpected = actual_rule_ids - allowed_rule_ids
    return FixtureEvaluationResult(
        fixtureId=fixture.id,
        kind=fixture.kind,
        title=fixture.title,
        passed=not missed and not unexpected,
        expectedRuleIds=fixture.expected_rule_ids,
        actualRuleIds=actual_rule_ids,
        missedRuleIds=missed,
        unexpectedRuleIds=unexpected,
        findingCount=len(report.findings),
        mergeRecommendation=report.merge_recommendation,
    )


def _github_files_from_diff(diff_files: list[DiffFile]) -> list[dict]:
    files = []
    for diff_file in diff_files:
        added = sum(
            1
            for hunk in diff_file.hunks
            for line in hunk.lines
            if line.kind == "add"
        )
        removed = sum(
            1
            for hunk in diff_file.hunks
            for line in hunk.lines
            if line.kind == "remove"
        )
        files.append(
            {
                "filename": diff_file.path,
                "status": diff_file.status,
                "additions": added,
                "deletions": removed,
                "patch": diff_file.patch,
            }
        )
    return files


def _format_rule_ids(rule_ids: set[str]) -> str:
    if not rule_ids:
        return "-"
    return ", ".join(sorted(rule_ids))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _snapshot_id(created_at: str) -> str:
    compact_time = (
        created_at.replace("+00:00", "Z")
        .replace("-", "")
        .replace(":", "")
        .replace("T", "-")
    )
    return f"{compact_time}-{uuid.uuid4().hex[:8]}"


def _snapshot_summary(snapshot: QualityEvaluationSnapshot) -> dict:
    report = snapshot.report
    return {
        "id": snapshot.id,
        "label": snapshot.label,
        "createdAt": snapshot.created_at,
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "falsePositives": report.false_positives,
        "falseNegatives": report.false_negatives,
    }
