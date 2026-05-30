from __future__ import annotations

from ai_pr_review.github import GitHubClient, PRReference


def test_github_client_lists_pull_reviews(monkeypatch) -> None:
    client = GitHubClient(token=None)
    calls: list[str] = []

    def fake_paginate(path: str) -> list[dict]:
        calls.append(path)
        return [{"id": 1, "body": "review summary"}]

    monkeypatch.setattr(client, "_paginate", fake_paginate)
    try:
        reviews = client.list_pull_reviews(PRReference(owner="org", repo="repo", number=12))
    finally:
        client.close()

    assert reviews == [{"id": 1, "body": "review summary"}]
    assert calls == ["/repos/org/repo/pulls/12/reviews"]
