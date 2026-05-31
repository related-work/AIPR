from __future__ import annotations

import pytest

from ai_pr_review.github import GitHubAPIError, GitHubClient


def test_list_owner_repositories_falls_back_to_org_when_user_not_found(monkeypatch) -> None:
    client = GitHubClient.__new__(GitHubClient)
    calls = []

    def fake_paginate(path, *, params=None):
        calls.append((path, params))
        if path == "/users/acme/repos":
            raise GitHubAPIError("GitHub API 请求失败: GET /users/acme/repos -> HTTP 404: Not Found")
        return [
            {
                "name": "api",
                "full_name": "acme/api",
                "private": False,
                "archived": False,
                "default_branch": "main",
                "open_issues_count": 2,
                "updated_at": "2026-05-31T01:00:00Z",
                "html_url": "https://github.com/acme/api",
            }
        ]

    monkeypatch.setattr(client, "_paginate", fake_paginate)

    repos = client.list_owner_repositories("acme")

    assert calls == [
        ("/users/acme/repos", {"sort": "updated", "direction": "desc", "type": "owner"}),
        ("/orgs/acme/repos", {"sort": "updated", "direction": "desc", "type": "all"}),
    ]
    assert repos[0]["full_name"] == "acme/api"


def test_list_owner_repositories_keeps_non_404_errors(monkeypatch) -> None:
    client = GitHubClient.__new__(GitHubClient)

    def fake_paginate(path, *, params=None):
        raise GitHubAPIError("GitHub API 请求失败: GET /users/acme/repos -> HTTP 403: rate limit")

    monkeypatch.setattr(client, "_paginate", fake_paginate)

    with pytest.raises(GitHubAPIError, match="HTTP 403"):
        client.list_owner_repositories("acme")


def test_list_repository_pulls_uses_open_state_and_updated_sort(monkeypatch) -> None:
    client = GitHubClient.__new__(GitHubClient)
    calls = []

    def fake_paginate(path, *, params=None):
        calls.append((path, params))
        return [
            {
                "number": 4,
                "title": "fix auth",
                "html_url": "https://github.com/acme/api/pull/4",
                "state": "open",
                "updated_at": "2026-05-31T02:00:00Z",
                "user": {"login": "alice"},
            }
        ]

    monkeypatch.setattr(client, "_paginate", fake_paginate)

    pulls = client.list_repository_pulls("acme", "api")

    assert calls == [
        (
            "/repos/acme/api/pulls",
            {"state": "open", "sort": "updated", "direction": "desc"},
        )
    ]
    assert pulls[0]["number"] == 4
