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
