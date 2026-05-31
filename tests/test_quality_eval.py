from __future__ import annotations

import json

from ai_pr_review.quality_eval import (
    QualityEvaluationReport,
    QualitySnapshotStore,
    builtin_quality_fixtures,
    evaluate_builtin_fixtures,
    render_quality_evaluation_json,
    render_quality_evaluation_markdown,
)


def test_builtin_quality_fixtures_cover_core_pr_shapes() -> None:
    fixtures = builtin_quality_fixtures()

    assert {fixture.kind for fixture in fixtures} == {
        "high_quality",
        "low_quality",
        "harmful",
        "clean",
    }
    assert all(fixture.raw_diff.startswith("diff --git") for fixture in fixtures)
    assert all(fixture.expected_rule_ids is not None for fixture in fixtures)


def test_quality_evaluation_scores_false_positives_and_false_negatives() -> None:
    report = evaluate_builtin_fixtures()
    by_id = {result.fixture_id: result for result in report.results}

    assert report.total == 4
    assert report.passed == 4
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert by_id["harmful_pr"].expected_rule_ids == {
        "auth_check_removed",
        "possible_secret",
        "sql_string_interpolation",
        "migration_risk",
    }
    assert by_id["low_quality_pr"].expected_rule_ids == {
        "missing_required_tests",
        "test_assertion_weakened",
    }
    assert by_id["high_quality_pr"].actual_rule_ids == set()
    assert by_id["clean_docs_pr"].actual_rule_ids == set()


def test_quality_evaluation_renderers_are_stable() -> None:
    report = evaluate_builtin_fixtures()

    payload = json.loads(render_quality_evaluation_json(report))
    markdown = render_quality_evaluation_markdown(report)

    assert payload["passed"] == 4
    assert payload["falsePositives"] == 0
    assert payload["falseNegatives"] == 0
    assert "# AI PR Review Quality Evaluation" in markdown
    assert "| harmful_pr | harmful | pass | 4 | 4 | 0 | 0 |" in markdown


def test_quality_snapshot_store_saves_lists_and_compares_reports(tmp_path) -> None:
    store = QualitySnapshotStore(tmp_path)
    baseline_report = evaluate_builtin_fixtures()
    degraded_report = _degraded_report(baseline_report)

    baseline = store.save(baseline_report, label="baseline")
    target = store.save(degraded_report, label="after-change")
    summaries = store.list_summaries()
    comparison = store.compare(baseline.id, target.id)

    assert [summary["label"] for summary in summaries] == ["after-change", "baseline"]
    assert store.get(baseline.id).report.passed == 4
    assert comparison.base_id == baseline.id
    assert comparison.target_id == target.id
    assert comparison.delta_passed == -1
    assert comparison.delta_false_negatives == 1
    assert comparison.fixture_changes[0].fixture_id == "high_quality_pr"
    assert comparison.fixture_changes[0].passed_changed is True


def _degraded_report(report: QualityEvaluationReport) -> QualityEvaluationReport:
    changed_results = []
    for result in report.results:
        if result.fixture_id == "high_quality_pr":
            changed_results.append(
                result.model_copy(
                    update={
                        "passed": False,
                        "missed_rule_ids": {"unexpected_regression"},
                    }
                )
            )
        else:
            changed_results.append(result)
    return report.model_copy(
        update={
            "passed": report.passed - 1,
            "failed": report.failed + 1,
            "false_negatives": report.false_negatives + 1,
            "results": changed_results,
        }
    )
