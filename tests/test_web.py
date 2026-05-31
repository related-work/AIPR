from __future__ import annotations

import json
import threading
import time

from ai_pr_review.web import (
    ReviewJob,
    ReviewJobStore,
    ReviewRunRequest,
    build_cli_args,
    display_command,
    doctor_payload,
    github_pulls_payload,
    github_repos_payload,
    inline_preview_payload,
    quality_snapshot_compare_payload,
    quality_snapshot_list_payload,
    quality_snapshot_save_payload,
    quality_evaluation_payload,
)
from ai_pr_review.config import ReviewConfig
from ai_pr_review.progress import PROGRESS_FILE_ENV, ProgressReporter
from ai_pr_review.quality_eval import QualitySnapshotStore, evaluate_builtin_fixtures


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


def test_review_job_store_records_progress_for_successful_job() -> None:
    def fake_executor(command, *, cwd, env):
        class Result:
            returncode = 0
            stdout = "# AI PR Review\n\n完成"
            stderr = ""

        return Result()

    store = ReviewJobStore(executor=fake_executor)
    job = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/123"))

    deadline = time.monotonic() + 2
    while store.get(job.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    finished = store.get(job.id)
    progress = [event.model_dump() for event in finished.progress]

    assert [event["stage"] for event in progress] == [
        "queued",
        "process_start",
        "process_exit",
    ]
    assert progress[-1]["status"] == "completed"
    assert store.list_recent()[0]["progress"][-1]["label"] == "Review 进程完成"


def test_review_job_store_merges_cli_progress_events(tmp_path) -> None:
    def fake_executor(command, *, cwd, env):
        reporter = ProgressReporter(env[PROGRESS_FILE_ENV])
        reporter.emit("github_fetch", "获取 GitHub PR 数据", "running")
        reporter.emit("github_fetch", "GitHub PR 数据获取完成", "completed")

        class Result:
            returncode = 0
            stdout = "# AI PR Review\n\n完成"
            stderr = ""

        return Result()

    store = ReviewJobStore(executor=fake_executor, storage_dir=tmp_path)
    job = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/123"))

    deadline = time.monotonic() + 2
    while store.get(job.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    finished = store.get(job.id)
    stages = [(event.stage, event.status) for event in finished.progress]

    assert ("github_fetch", "running") in stages
    assert ("github_fetch", "completed") in stages
    assert finished.progress[-1].stage == "process_exit"


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
    assert finished.progress[-1].stage == "process_exit"
    assert finished.progress[-1].status == "failed"


def test_review_job_store_records_progress_for_executor_error() -> None:
    def fake_executor(command, *, cwd, env):
        raise RuntimeError("boom")

    store = ReviewJobStore(executor=fake_executor)
    job = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/123"))

    deadline = time.monotonic() + 2
    while store.get(job.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    finished = store.get(job.id)

    assert finished.status == "failed"
    assert finished.error == "boom"
    assert finished.progress[-1].stage == "process_error"
    assert finished.progress[-1].status == "failed"


def test_review_job_store_lists_recent_jobs_without_large_output() -> None:
    def fake_executor(command, *, cwd, env):
        class Result:
            returncode = 0
            stdout = "# AI PR Review\n\n" + ("x" * 200)
            stderr = ""

        return Result()

    store = ReviewJobStore(executor=fake_executor, max_jobs=2)
    first = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/1"))
    second = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/2"))
    third = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/3"))

    deadline = time.monotonic() + 2
    while any(store.get(job.id).status in {"queued", "running"} for job in [second, third]) and time.monotonic() < deadline:
        time.sleep(0.01)

    jobs = store.list_recent()

    assert [job["request"]["prUrl"] for job in jobs] == [
        "https://github.com/org/repo/pull/3",
        "https://github.com/org/repo/pull/2",
    ]
    assert all("stdout" not in job for job in jobs)
    assert all("stderr" not in job for job in jobs)
    assert all("outputPreview" in job for job in jobs)
    assert first.id not in {job["id"] for job in jobs}


def test_review_job_store_filters_history_by_query_status_repo_and_date(tmp_path) -> None:
    _write_history_job(
        tmp_path,
        job_id="one",
        pr_url="https://github.com/org/api/pull/1",
        status="succeeded",
        created_at="2026-05-30T10:00:00+00:00",
        stdout="# API report",
    )
    _write_history_job(
        tmp_path,
        job_id="two",
        pr_url="https://github.com/org/web/pull/2",
        status="failed",
        created_at="2026-05-31T10:00:00+00:00",
        stderr="blocking finding",
    )
    store = ReviewJobStore(
        executor=lambda command, *, cwd, env: None,
        storage_dir=tmp_path,
    )

    jobs = store.list_recent(
        query="blocking",
        status="failed",
        repository="org/web",
        created_from="2026-05-31",
        created_to="2026-05-31",
    )

    assert [job["id"] for job in jobs] == ["two"]


def test_review_job_store_deletes_history_job_and_files(tmp_path) -> None:
    _write_history_job(
        tmp_path,
        job_id="delete-me",
        pr_url="https://github.com/org/repo/pull/1",
        status="succeeded",
    )
    progress_file = tmp_path / "delete-me.progress.jsonl"
    progress_file.write_text(
        '{"stage":"x","label":"x","status":"completed","timestamp":"2026-05-31T00:00:00+00:00"}\n'
    )
    store = ReviewJobStore(
        executor=lambda command, *, cwd, env: None,
        storage_dir=tmp_path,
    )

    assert store.delete("delete-me") is True

    assert store.list_recent() == []
    assert not (tmp_path / "delete-me.json").exists()
    assert not progress_file.exists()


def test_review_job_store_clears_finished_history_but_keeps_running_jobs() -> None:
    release = threading.Event()

    def fake_executor(command, *, cwd, env):
        release.wait(timeout=2)

        class Result:
            returncode = 0
            stdout = "# done"
            stderr = ""

        return Result()

    store = ReviewJobStore(executor=fake_executor)
    running = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/1"))
    with store._lock:
        store._jobs["finished"] = ReviewJob(
            id="finished",
            status="succeeded",
            command="ai-pr-review https://github.com/org/repo/pull/2",
            request=ReviewRunRequest(pr_url="https://github.com/org/repo/pull/2"),
            createdAt="2026-05-31T00:00:00+00:00",
            exitCode=0,
            stdout="# finished",
        )
        store._order.append("finished")

    deleted = store.clear_finished()

    assert deleted == 1
    assert store.get(running.id).status in {"queued", "running"}
    assert [job["id"] for job in store.list_recent()] == [running.id]

    release.set()
    deadline = time.monotonic() + 2
    while store.get(running.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)


def test_review_job_store_exports_history_as_markdown_and_json(tmp_path) -> None:
    _write_history_job(
        tmp_path,
        job_id="export-me",
        pr_url="https://github.com/org/repo/pull/1",
        status="succeeded",
        stdout="# Review\n\n建议合并。",
    )
    store = ReviewJobStore(
        executor=lambda command, *, cwd, env: None,
        storage_dir=tmp_path,
    )

    markdown = store.export("export-me", "markdown")
    payload = json.loads(store.export("export-me", "json"))

    assert markdown == "# Review\n\n建议合并。"
    assert payload["id"] == "export-me"
    assert payload["request"]["prUrl"] == "https://github.com/org/repo/pull/1"


def test_review_job_store_persists_finished_jobs_to_disk(tmp_path) -> None:
    def fake_executor(command, *, cwd, env):
        class Result:
            returncode = 0
            stdout = "# AI PR Review\n\n持久化报告"
            stderr = ""

        return Result()

    store = ReviewJobStore(executor=fake_executor, storage_dir=tmp_path)
    job = store.start(ReviewRunRequest(pr_url="https://github.com/org/repo/pull/9"))

    deadline = time.monotonic() + 2
    while store.get(job.id).status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    loaded_store = ReviewJobStore(executor=fake_executor, storage_dir=tmp_path)
    loaded = loaded_store.get(job.id)

    assert loaded.status == "succeeded"
    assert loaded.stdout == "# AI PR Review\n\n持久化报告"
    assert loaded_store.list_recent()[0]["request"]["prUrl"] == "https://github.com/org/repo/pull/9"


def test_review_job_store_marks_interrupted_persisted_jobs_failed(tmp_path) -> None:
    stale_id = "stale-job"
    (tmp_path / f"{stale_id}.json").write_text(
        json.dumps(
            {
                "id": stale_id,
                "status": "running",
                "command": "ai-pr-review https://github.com/org/repo/pull/10",
                "request": {"prUrl": "https://github.com/org/repo/pull/10"},
                "createdAt": "2026-05-31T00:00:00+00:00",
                "startedAt": "2026-05-31T00:00:01+00:00",
                "finishedAt": None,
                "exitCode": None,
                "stdout": "",
                "stderr": "",
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    loaded_store = ReviewJobStore(
        executor=lambda command, *, cwd, env: None,
        storage_dir=tmp_path,
    )
    loaded = loaded_store.get(stale_id)

    assert loaded.status == "failed"
    assert loaded.error == "Web 服务重启前任务未完成"


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


def test_inline_preview_payload_builds_comment_preview_from_json_report() -> None:
    report = {
        "pr": {"url": "https://github.com/org/repo/pull/123", "title": "Risky PR"},
        "riskOverview": {"critical": 0, "high": 1, "medium": 0, "low": 0, "blocking": 1},
        "findings": [
            {
                "path": "src/app.py",
                "line": 2,
                "severity": "high",
                "category": "security",
                "confidence": 0.91,
                "evidence": ['+query = f"select * from users where id={user_id}"'],
                "problem": "SQL 拼接可能导致注入。",
                "suggestion": "使用参数化查询。",
                "blocking": True,
            },
            {
                "path": "src/app.py",
                "line": 4,
                "severity": "medium",
                "category": "maintainability",
                "confidence": 0.8,
                "evidence": ["+name = 'x'"],
                "problem": "普通维护性问题。",
                "suggestion": "整理命名。",
                "blocking": False,
            },
        ],
    }
    raw_diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 def handler(user_id):
+    query = f"select * from users where id={user_id}"
     return db.query(query)
"""

    payload = inline_preview_payload(json.dumps(report), raw_diff)

    assert payload["commentableCount"] == 1
    assert payload["skippedCount"] == 1
    assert payload["comments"][0]["path"] == "src/app.py"
    assert payload["comments"][0]["line"] == 2
    assert payload["comments"][0]["severity"] == "high"
    assert payload["comments"][0]["confidence"] == 0.91
    assert payload["limitations"] == [
        "已跳过 1 条低风险、低置信度或非阻塞 finding 的 inline comment"
    ]


def test_inline_preview_payload_returns_parse_error_for_markdown_report() -> None:
    payload = inline_preview_payload("# AI PR Review\n\n## 风险总览", "")

    assert payload == {
        "comments": [],
        "commentableCount": 0,
        "skippedCount": 0,
        "limitations": ["当前报告不是 JSON 输出，无法生成结构化 inline 预览"],
    }


def test_doctor_payload_returns_config_status_without_secret_values() -> None:
    config = ReviewConfig()

    payload = doctor_payload(
        config=config,
        github_token="ghp_secret",
        openai_api_key="sk_secret",
        openai_base_url="https://one-api.example.com/v1",
        api_mode="chat",
        model_profile="balanced",
        smoke=True,
        smoke_tester=lambda **_: (True, None, []),
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["ok"] is True
    assert payload["githubTokenConfigured"] is True
    assert payload["openaiApiKeyConfigured"] is True
    assert payload["apiMode"] == "chat"
    assert "ghp_secret" not in serialized
    assert "sk_secret" not in serialized
    assert "one-api.example.com" not in serialized


def test_quality_evaluation_payload_returns_all_fixture_results() -> None:
    payload = quality_evaluation_payload("all")

    assert payload["total"] == 4
    assert payload["passed"] == 4
    assert payload["falsePositives"] == 0
    assert payload["falseNegatives"] == 0
    assert {result["kind"] for result in payload["results"]} == {
        "high_quality",
        "low_quality",
        "harmful",
        "clean",
    }


def test_quality_evaluation_payload_can_run_one_fixture() -> None:
    payload = quality_evaluation_payload("harmful_pr")

    assert payload["total"] == 1
    assert payload["passed"] == 1
    assert payload["results"][0]["fixtureId"] == "harmful_pr"


def test_quality_snapshot_payloads_save_list_and_compare(tmp_path) -> None:
    store = QualitySnapshotStore(tmp_path)
    baseline = quality_snapshot_save_payload(store, fixture_id="all", label="baseline")
    target_report = evaluate_builtin_fixtures()
    target_snapshot = store.save(target_report, label="same-result")

    list_payload = quality_snapshot_list_payload(store)
    comparison = quality_snapshot_compare_payload(
        store,
        base_id=baseline["id"],
        target_id=target_snapshot.id,
    )

    assert list_payload["snapshots"][0]["label"] == "same-result"
    assert list_payload["snapshots"][1]["label"] == "baseline"
    assert comparison["baseId"] == baseline["id"]
    assert comparison["targetId"] == target_snapshot.id
    assert comparison["deltaPassed"] == 0


def _write_history_job(
    directory,
    *,
    job_id: str,
    pr_url: str,
    status: str,
    created_at: str = "2026-05-31T00:00:00+00:00",
    stdout: str = "",
    stderr: str = "",
) -> None:
    (directory / f"{job_id}.json").write_text(
        json.dumps(
            {
                "id": job_id,
                "status": status,
                "command": f"ai-pr-review {pr_url}",
                "request": {"prUrl": pr_url},
                "createdAt": created_at,
                "startedAt": created_at,
                "finishedAt": created_at,
                "exitCode": 0 if status == "succeeded" else 1,
                "stdout": stdout,
                "stderr": stderr,
                "error": None,
                "progress": [],
            }
        ),
        encoding="utf-8",
    )
