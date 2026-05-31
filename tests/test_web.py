from __future__ import annotations

import time

from ai_pr_review.web import (
    ReviewJobStore,
    ReviewRunRequest,
    build_cli_args,
    display_command,
    github_pulls_payload,
    github_repos_payload,
)


def test_build_cli_args_includes_review_options() -> None:
    request = ReviewRunRequest(
        pr_url="https://github.com/org/repo/pull/123",
        format="json",
        postComment=True,
        postInlineComments=True,
        failOn="high",
        model="accurate",
        changedOnly=True,
        withContext=True,
        noLlm=True,
        llmMaxChunks=3,
        debugChunks=True,
    )

    assert build_cli_args(request) == [
        "https://github.com/org/repo/pull/123",
        "--format",
        "json",
        "--model",
        "accurate",
        "--post-comment",
        "--post-inline-comments",
        "--fail-on",
        "high",
        "--changed-only",
        "--with-context",
        "--no-llm",
        "--llm-max-chunks",
        "3",
        "--debug-chunks",
    ]
    assert display_command(request).startswith("ai-pr-review https://github.com/org/repo/pull/123")


def test_review_job_store_tracks_successful_job() -> None:
    calls = []

    def fake_executor(command, *, cwd, env):
        calls.append((command, cwd, env))

        class Result:
            returncode = 0
            stdout = "# AI PR Review\n\n建议合并。"
            stderr = ""

        return Result()

    store = ReviewJobStore(executor=fake_executor)
    job = store.start(
        ReviewRunRequest(
            pr_url="https://github.com/org/repo/pull/123",
            changedOnly=True,
            llmMaxChunks=2,
            debugChunks=True,
        )
    )

    deadline = time.monotonic() + 2
    while store.get(job.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    finished = store.get(job.id)
    assert finished.status == "succeeded"
    assert finished.exit_code == 0
    assert "建议合并" in finished.stdout
    assert calls[0][0][-4:] == ["--changed-only", "--llm-max-chunks", "2", "--debug-chunks"]
    assert "PYTHONPATH" in calls[0][2]


def test_review_job_store_tracks_failed_job() -> None:
    def fake_executor(command, *, cwd, env):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "blocking finding"

        return Result()

    store = ReviewJobStore(executor=fake_executor)
    job = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/123"))

    deadline = time.monotonic() + 2
    while store.get(job.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    finished = store.get(job.id)
    assert finished.status == "failed"
    assert finished.exit_code == 1
    assert finished.stderr == "blocking finding"


def test_github_repos_payload_sorts_and_sanitizes_fields() -> None:
    class FakeGitHub:
        def list_owner_repositories(self, owner):
            assert owner == "oldsheeppp"
            return [
                {
                    "name": "old",
                    "full_name": "oldsheeppp/old",
                    "private": True,
                    "archived": True,
                    "default_branch": "master",
                    "open_issues_count": 0,
                    "updated_at": "2026-05-01T00:00:00Z",
                    "html_url": "https://github.com/oldsheeppp/old",
                },
                {
                    "name": "aiprtest",
                    "full_name": "oldsheeppp/aiprtest",
                    "private": False,
                    "archived": False,
                    "default_branch": "main",
                    "open_issues_count": 3,
                    "updated_at": "2026-05-31T00:00:00Z",
                    "html_url": "https://github.com/oldsheeppp/aiprtest",
                },
            ]

    payload = github_repos_payload("oldsheeppp", FakeGitHub())

    assert payload == {
        "owner": "oldsheeppp",
        "repos": [
            {
                "name": "aiprtest",
                "fullName": "oldsheeppp/aiprtest",
                "private": False,
                "archived": False,
                "defaultBranch": "main",
                "openIssues": 3,
                "updatedAt": "2026-05-31T00:00:00Z",
                "url": "https://github.com/oldsheeppp/aiprtest",
            },
            {
                "name": "old",
                "fullName": "oldsheeppp/old",
                "private": True,
                "archived": True,
                "defaultBranch": "master",
                "openIssues": 0,
                "updatedAt": "2026-05-01T00:00:00Z",
                "url": "https://github.com/oldsheeppp/old",
            },
        ],
    }


def test_github_pulls_payload_returns_review_ready_urls() -> None:
    class FakeGitHub:
        def list_repository_pulls(self, owner, repo, *, state="open"):
            assert (owner, repo, state) == ("oldsheeppp", "aiprtest", "open")
            return [
                {
                    "number": 4,
                    "title": "fix auth",
                    "html_url": "https://github.com/oldsheeppp/aiprtest/pull/4",
                    "state": "open",
                    "updated_at": "2026-05-31T00:00:00Z",
                    "user": {"login": "alice"},
                }
            ]

    payload = github_pulls_payload("oldsheeppp", "aiprtest", "open", FakeGitHub())

    assert payload == {
        "owner": "oldsheeppp",
        "repo": "aiprtest",
        "state": "open",
        "pulls": [
            {
                "number": 4,
                "title": "fix auth",
                "url": "https://github.com/oldsheeppp/aiprtest/pull/4",
                "author": "alice",
                "state": "open",
                "updatedAt": "2026-05-31T00:00:00Z",
            }
        ],
    }
