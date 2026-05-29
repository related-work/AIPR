from __future__ import annotations

import pytest

from ai_pr_review.github import PRUrlError, parse_pr_url


def test_parse_github_pull_request_url() -> None:
    ref = parse_pr_url("https://github.com/openai/example-repo/pull/123")

    assert ref.owner == "openai"
    assert ref.repo == "example-repo"
    assert ref.number == 123
    assert ref.html_url == "https://github.com/openai/example-repo/pull/123"


def test_parse_pull_request_url_with_query_and_trailing_path() -> None:
    ref = parse_pr_url("https://github.com/org/repo/pull/42/files?diff=split")

    assert (ref.owner, ref.repo, ref.number) == ("org", "repo", 42)
    assert ref.html_url == "https://github.com/org/repo/pull/42"


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/org/repo/pull/1",
        "https://github.com/org/repo/issues/1",
        "not-a-url",
        "https://github.com/org/repo/pull/not-number",
    ],
)
def test_parse_pull_request_url_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(PRUrlError):
        parse_pr_url(url)
