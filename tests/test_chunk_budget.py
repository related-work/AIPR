from __future__ import annotations

from ai_pr_review.chunk_budget import (
    ReviewBudget,
    apply_chunk_budget,
    build_analysis_coverage,
)
from ai_pr_review.diff_parser import DiffChunk, FileClassification


def _chunk(path: str, patch: str, *, new_start: int = 1) -> DiffChunk:
    return DiffChunk(
        path=path,
        patch=patch,
        old_start=new_start,
        new_start=new_start,
        old_length=3,
        new_length=3,
        classification=FileClassification(path=path),
    )


def test_apply_chunk_budget_limits_files_chunks_and_llm_selection_by_risk() -> None:
    low_risk = _chunk("src/ui.py", "+label = 'Save'")
    auth_risk = _chunk("src/auth/service.py", "-require_admin(user)")
    sql_risk = _chunk(
        "src/app/users.py",
        '+query = f"SELECT * FROM users WHERE id = {user_id}"',
    )

    selection = apply_chunk_budget(
        [low_risk, auth_risk, sql_risk],
        ReviewBudget(max_files=1, max_chunks=2, max_llm_chunks=1),
    )

    assert [chunk.path for chunk in selection.candidate_chunks] == ["src/auth/service.py"]
    assert [chunk.path for chunk in selection.llm_chunks] == ["src/auth/service.py"]
    assert [item.path for item in selection.chunk_debug] == [
        "src/auth/service.py",
        "src/app/users.py",
        "src/ui.py",
    ]
    assert selection.chunk_debug[0].selected is True
    assert selection.chunk_debug[1].selected is False
    assert selection.chunk_debug[2].selected is False
    assert any("文件预算" in item for item in selection.limitations)


def test_build_analysis_coverage_reports_large_pr_and_skipped_reasons() -> None:
    github_files = [
        {"filename": "src/app/users.py", "patch": "+query = 'safe'", "additions": 1, "deletions": 0},
        {"filename": "src/ui.py", "patch": "+label = 'Save'", "additions": 1, "deletions": 0},
        {"filename": "docs/readme.md", "patch": "+docs", "additions": 1, "deletions": 0},
        {"filename": "package-lock.json", "patch": "+{}", "additions": 1, "deletions": 0},
        {"filename": "dist/app.generated.js", "patch": "+bundle", "additions": 1, "deletions": 0},
        {"filename": "assets/logo.png", "patch": None, "additions": 0, "deletions": 0},
    ]
    chunks = [
        _chunk("src/app/users.py", "+query = 'safe'"),
        _chunk("src/ui.py", "+label = 'Save'"),
    ]

    coverage = build_analysis_coverage(
        github_files=github_files,
        chunks=chunks,
        llm_chunks=[chunks[0]],
        budget=ReviewBudget(
            max_files=5,
            max_chunks=5,
            max_llm_chunks=1,
            large_pr_file_threshold=3,
            large_pr_line_threshold=100,
        ),
        llm_enabled=True,
    )

    assert coverage.large_pr is True
    assert coverage.changed_files == 6
    assert coverage.analyzed_files == 1
    assert coverage.skipped_files == 5
    assert coverage.total_chunks == 2
    assert coverage.llm_analyzed_chunks == 1
    assert coverage.rules_scanned_files == 5
    assert coverage.coverage_ratio == 0.17
    assert coverage.budget_limits.max_llm_chunks == 1
    assert {item.reason: item.count for item in coverage.skipped_reasons} == {
        "documentation": 1,
        "generated_file": 1,
        "lockfile": 1,
        "binary_file": 1,
        "over_budget_low_risk": 1,
    }
    file_coverage = {item.path: item for item in coverage.file_coverage}
    assert file_coverage["src/app/users.py"].status == "analyzed"
    assert file_coverage["src/ui.py"].status == "rule_only"
    assert file_coverage["src/ui.py"].reason == "over_budget_low_risk"
    assert file_coverage["docs/readme.md"].status == "rule_only"
    assert file_coverage["assets/logo.png"].status == "skipped"


def test_build_analysis_coverage_flags_high_risk_unreviewed_files() -> None:
    github_files = [
        {"filename": "src/auth/service.py", "patch": "-require_admin(user)", "additions": 0, "deletions": 1},
        {"filename": "src/ui.py", "patch": "+label = 'Save'", "additions": 1, "deletions": 0},
    ]
    chunks = [
        _chunk("src/auth/service.py", "-require_admin(user)"),
        _chunk("src/ui.py", "+label = 'Save'"),
    ]

    coverage = build_analysis_coverage(
        github_files=github_files,
        chunks=chunks,
        llm_chunks=[chunks[1]],
        budget=ReviewBudget(),
        llm_enabled=True,
    )

    auth_file = next(item for item in coverage.file_coverage if item.path == "src/auth/service.py")
    ui_file = next(item for item in coverage.file_coverage if item.path == "src/ui.py")

    assert auth_file.status == "rule_only"
    assert auth_file.high_risk_unreviewed is True
    assert auth_file.risk_score >= 70
    assert "auth" in auth_file.reasons
    assert ui_file.status == "analyzed"
    assert ui_file.high_risk_unreviewed is False


def test_build_analysis_coverage_marks_model_eligible_files_as_llm_disabled() -> None:
    github_files = [
        {"filename": "src/app.py", "patch": "+return 1", "additions": 1, "deletions": 0},
    ]
    chunks = [_chunk("src/app.py", "+return 1")]

    coverage = build_analysis_coverage(
        github_files=github_files,
        chunks=chunks,
        llm_chunks=[],
        budget=ReviewBudget(),
        llm_enabled=False,
    )

    assert coverage.analyzed_files == 0
    assert coverage.llm_analyzed_chunks == 0
    assert coverage.coverage_ratio == 0
    assert coverage.skipped_reasons[0].reason == "llm_disabled"
