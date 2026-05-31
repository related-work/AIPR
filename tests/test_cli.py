from __future__ import annotations

import io
import json

from ai_pr_review import cli
from ai_pr_review.config import ReviewConfig
from ai_pr_review.progress import read_progress_events
from ai_pr_review.doctor import DoctorReport
from ai_pr_review.schemas import Finding, ReviewReport, RiskOverview


class FakeRunner:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return ReviewReport(
            pr_url=kwargs["pr_url"],
            title="Fake PR",
            summary="fake summary",
            scope=[],
            risk_overview=RiskOverview(high=1, blocking=1),
            findings=[],
            test_suggestions=[],
            merge_recommendation="do_not_merge",
            limitations=[],
        )


def test_cli_parses_options_renders_json_and_returns_failure_for_threshold() -> None:
    runner = FakeRunner()
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = cli.main(
        [
            "https://github.com/org/repo/pull/1",
            "--format",
            "json",
            "--fail-on",
            "high",
            "--model",
            "accurate",
            "--changed-only",
            "--with-context",
            "--llm-max-chunks",
            "2",
            "--debug-chunks",
            "--no-llm",
            "--post-inline-comments",
        ],
        runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 1
    assert payload["mergeRecommendation"] == "do_not_merge"
    assert runner.calls[0]["post_comment"] is False
    assert runner.calls[0]["model_profile"] == "accurate"
    assert runner.calls[0]["changed_only"] is True
    assert runner.calls[0]["with_context"] is True
    assert runner.calls[0]["llm_max_chunks"] == 2
    assert runner.calls[0]["debug_chunks"] is True
    assert runner.calls[0]["no_llm"] is True
    assert runner.calls[0]["post_inline_comments"] is True


def test_cli_requires_explicit_post_comment() -> None:
    runner = FakeRunner()
    stdout = io.StringIO()

    cli.main(
        ["https://github.com/org/repo/pull/1", "--post-comment"],
        runner=runner,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert runner.calls[0]["post_comment"] is True


def test_cli_doctor_renders_json_and_returns_success() -> None:
    calls = []

    def fake_doctor_runner(**kwargs):
        calls.append(kwargs)
        return DoctorReport(
            ok=True,
            github_token_configured=True,
            openai_api_key_configured=True,
            openai_base_url_configured=True,
            openai_base_url_status="configured_api_like",
            api_mode="chat",
            fast_model="fast-model",
            strong_model="strong-model",
            smoke_ok=True,
            smoke_error=None,
            warnings=[],
            limitations=[],
        )

    stdout = io.StringIO()
    exit_code = cli.main(
        ["doctor", "--format", "json", "--model", "fast"],
        doctor_runner=fake_doctor_runner,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["fastModel"] == "fast-model"
    assert calls[0]["model_profile"] == "fast"
    assert calls[0]["smoke"] is True


def test_cli_doctor_returns_failure_when_report_not_ok() -> None:
    def fake_doctor_runner(**kwargs):
        return DoctorReport(
            ok=False,
            github_token_configured=False,
            openai_api_key_configured=False,
            openai_base_url_configured=False,
            openai_base_url_status="default",
            api_mode="chat",
            fast_model="fast-model",
            strong_model="strong-model",
            smoke_ok=False,
            smoke_error="未设置 OPENAI_API_KEY",
            warnings=[],
            limitations=[],
        )

    exit_code = cli.main(
        ["doctor", "--no-smoke"],
        doctor_runner=fake_doctor_runner,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 2


def test_cli_web_subcommand_invokes_web_runner() -> None:
    calls = []

    def fake_web_runner(**kwargs):
        calls.append(kwargs)
        return 0

    stdout = io.StringIO()
    exit_code = cli.main(
        ["web", "--host", "0.0.0.0", "--port", "9876", "--frontend-dir", "frontend/dist"],
        web_runner=fake_web_runner,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert calls == [
        {
            "host": "0.0.0.0",
            "port": 9876,
            "frontend_dir": "frontend/dist",
        }
    ]


def test_run_review_includes_pull_reviews_in_comment_context(monkeypatch) -> None:
    class FakeGitHub:
        def __init__(self, token=None):
            self.token = token

        def get_pr(self, ref):
            return {
                "html_url": ref.html_url,
                "title": "Fake PR",
                "body": "",
                "head": {"sha": "abc123"},
            }

        def list_pr_files(self, ref):
            return []

        def list_pr_commits(self, ref):
            return []

        def list_issue_comments(self, ref):
            return [{"user": {"login": "alice"}, "body": "普通评论"}]

        def list_review_comments(self, ref):
            return [{"user": {"login": "Copilot"}, "path": "src/app.py", "body": "行内评论"}]

        def list_pull_reviews(self, ref):
            return [
                {
                    "user": {"login": "copilot-pull-request-reviewer[bot]"},
                    "state": "COMMENTED",
                    "body": "review summary",
                }
            ]

        def get_pr_diff(self, ref):
            return ""

        def close(self):
            pass

    monkeypatch.setattr(cli, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(cli, "load_config", lambda: ReviewConfig())

    report = cli.run_review(
        pr_url="https://github.com/org/repo/pull/1",
        output_format="markdown",
        post_comment=False,
        fail_on=None,
        model_profile="fast",
        changed_only=True,
        with_context=False,
        no_llm=True,
        llm_max_chunks=None,
        post_inline_comments=False,
    )

    assert report.comment_context.issue_comments == 1
    assert report.comment_context.review_comments == 1
    assert report.comment_context.pull_reviews == 1
    assert report.comment_context.copilot_review_comments == 1
    assert report.comment_context.copilot_pull_reviews == 1


def test_run_review_applies_evidence_verifier_to_llm_findings(monkeypatch) -> None:
    class FakeGitHub:
        def __init__(self, token=None):
            self.token = token

        def get_pr(self, ref):
            return {
                "html_url": ref.html_url,
                "title": "Fake PR",
                "body": "",
                "head": {"sha": "abc123"},
            }

        def list_pr_files(self, ref):
            return [
                {
                    "filename": "src/app.py",
                    "additions": 1,
                    "deletions": 1,
                    "patch": "@@ -1 +1 @@\n-return 0\n+return 1",
                }
            ]

        def list_pr_commits(self, ref):
            return []

        def list_issue_comments(self, ref):
            return []

        def list_review_comments(self, ref):
            return []

        def list_pull_reviews(self, ref):
            return []

        def get_pr_diff(self, ref):
            return """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-return 0
+return 1
"""

        def close(self):
            pass

    unsupported = Finding(
        path="src/app.py",
        line=1,
        severity="high",
        category="logic",
        confidence=0.9,
        evidence=["Copilot 评论说这里有问题"],
        problem="仅由评论支撑的问题",
        suggestion="按评论修改",
        blocking=True,
        source="llm",
    )

    monkeypatch.setattr(cli, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(cli, "load_config", lambda: ReviewConfig())
    monkeypatch.setattr(cli, "analyze_chunks", lambda *_, **__: ([unsupported], []))
    monkeypatch.setattr(cli, "verify_high_risk_findings", lambda findings, **__: (findings, []))

    report = cli.run_review(
        pr_url="https://github.com/org/repo/pull/1",
        output_format="markdown",
        post_comment=False,
        fail_on=None,
        model_profile="fast",
        changed_only=True,
        with_context=False,
        no_llm=False,
        llm_max_chunks=None,
        post_inline_comments=False,
    )

    assert report.findings == []
    assert "已丢弃 1 条缺少 diff 或上下文代码证据的 LLM finding" in report.limitations


def test_run_review_prioritizes_chunks_before_llm(monkeypatch) -> None:
    class FakeGitHub:
        def __init__(self, token=None):
            self.token = token

        def get_pr(self, ref):
            return {
                "html_url": ref.html_url,
                "title": "Fake PR",
                "body": "",
                "head": {"sha": "abc123"},
            }

        def list_pr_files(self, ref):
            return [
                {"filename": "src/ui.py", "additions": 1, "deletions": 0, "patch": "+label = 'Save'"},
                {
                    "filename": "src/app/users.py",
                    "additions": 1,
                    "deletions": 0,
                    "patch": '+query = f"SELECT * FROM users WHERE id = {user_id}"',
                },
            ]

        def list_pr_commits(self, ref):
            return []

        def list_issue_comments(self, ref):
            return []

        def list_review_comments(self, ref):
            return []

        def list_pull_reviews(self, ref):
            return []

        def get_pr_diff(self, ref):
            return """diff --git a/src/ui.py b/src/ui.py
--- a/src/ui.py
+++ b/src/ui.py
@@ -1 +1 @@
+label = 'Save'
diff --git a/src/app/users.py b/src/app/users.py
--- a/src/app/users.py
+++ b/src/app/users.py
@@ -1 +1 @@
+query = f"SELECT * FROM users WHERE id = {user_id}"
"""

        def close(self):
            pass

    calls = {}

    def fake_analyze_chunks(chunks, **kwargs):
        calls["paths"] = [chunk.path for chunk in chunks]
        calls["max_chunks"] = kwargs["max_chunks"]
        return [], []

    monkeypatch.setattr(cli, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(cli, "load_config", lambda: ReviewConfig())
    monkeypatch.setattr(cli, "analyze_chunks", fake_analyze_chunks)

    report = cli.run_review(
        pr_url="https://github.com/org/repo/pull/1",
        output_format="markdown",
        post_comment=False,
        fail_on=None,
        model_profile="fast",
        changed_only=True,
        with_context=False,
        no_llm=False,
        llm_max_chunks=1,
        debug_chunks=True,
        post_inline_comments=False,
    )

    assert calls["paths"] == ["src/app/users.py"]
    assert calls["max_chunks"] is None
    assert report.chunk_debug[0].path == "src/app/users.py"
    assert report.chunk_debug[0].selected is True
    assert report.chunk_debug[1].path == "src/ui.py"
    assert report.chunk_debug[1].selected is False


def test_run_review_emits_progress_events(monkeypatch, tmp_path) -> None:
    class FakeGitHub:
        def __init__(self, token=None):
            self.token = token

        def get_pr(self, ref):
            return {
                "html_url": ref.html_url,
                "title": "Fake PR",
                "body": "",
                "head": {"sha": "abc123"},
            }

        def list_pr_files(self, ref):
            return [
                {
                    "filename": "src/app.py",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "@@ -1 +1 @@\n+return 1",
                }
            ]

        def list_pr_commits(self, ref):
            return []

        def list_issue_comments(self, ref):
            return []

        def list_review_comments(self, ref):
            return []

        def list_pull_reviews(self, ref):
            return []

        def get_pr_diff(self, ref):
            return """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
+return 1
"""

        def close(self):
            pass

    progress_file = tmp_path / "progress.jsonl"

    monkeypatch.setattr(cli, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(cli, "load_config", lambda: ReviewConfig())
    monkeypatch.setenv("AI_PR_REVIEW_PROGRESS_FILE", str(progress_file))

    cli.run_review(
        pr_url="https://github.com/org/repo/pull/1",
        output_format="markdown",
        post_comment=False,
        fail_on=None,
        model_profile="fast",
        changed_only=True,
        with_context=False,
        no_llm=True,
        llm_max_chunks=None,
        post_inline_comments=False,
    )

    events = read_progress_events(progress_file)
    stages = [(event["stage"], event["status"]) for event in events]

    assert ("github_fetch", "running") in stages
    assert ("github_fetch", "completed") in stages
    assert ("diff_parse", "completed") in stages
    assert ("rules", "completed") in stages
    assert ("llm", "skipped") in stages
    assert ("verification", "skipped") in stages
    assert ("aggregation", "completed") in stages
    assert ("writeback", "skipped") in stages
