from __future__ import annotations

import io
import json

from ai_pr_review import cli
from ai_pr_review.schemas import ReviewReport, RiskOverview


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
            "--no-llm",
            "--llm-max-chunks",
            "2",
            "--debug-chunks",
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
    assert runner.calls[0]["no_llm"] is True
    assert runner.calls[0]["llm_max_chunks"] == 2
    assert runner.calls[0]["debug_chunks"] is True


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
    )

    assert calls["paths"] == ["src/app/users.py"]
    assert calls["max_chunks"] is None
    assert report.chunk_debug[0].path == "src/app/users.py"
    assert report.chunk_debug[0].selected is True
    assert report.chunk_debug[1].path == "src/ui.py"
    assert report.chunk_debug[1].selected is False
