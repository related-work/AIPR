from __future__ import annotations

import json
import mimetypes
import os
import re
import shlex
import subprocess
import sys
import threading
import uuid
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ai_pr_review.config import (
    ReviewConfig,
    load_config,
    resolve_github_token,
    resolve_openai_api_key,
    resolve_openai_api_mode,
    resolve_openai_base_url,
)
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.doctor import SmokeTester, run_doctor as run_doctor_report
from ai_pr_review.github import GitHubAPIError, GitHubClient, PRUrlError, parse_pr_url
from ai_pr_review.inline_comments import build_inline_review_comments
from ai_pr_review.progress import PROGRESS_FILE_ENV, ProgressEvent, ProgressStatus, read_progress_events
from ai_pr_review.schemas import Finding


JobStatus = Literal["queued", "running", "succeeded", "failed"]
Executor = Callable[[list[str], Path, dict[str, str]], subprocess.CompletedProcess[str]]
OWNER_REPO_PATTERN = r"^[A-Za-z0-9_.-]+$"


class ReviewRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pr_url: str = Field(alias="prUrl")
    output_format: Literal["markdown", "json"] = Field(default="markdown", alias="format")
    post_comment: bool = Field(default=False, alias="postComment")
    post_inline_comments: bool = Field(default=False, alias="postInlineComments")
    fail_on: Literal["critical", "high", "medium", "low"] | None = Field(
        default=None,
        alias="failOn",
    )
    model_profile: Literal["fast", "balanced", "accurate"] = Field(
        default="balanced",
        alias="model",
    )
    changed_only: bool = Field(default=False, alias="changedOnly")
    with_context: bool = Field(default=False, alias="withContext")
    no_llm: bool = Field(default=False, alias="noLlm")
    llm_max_chunks: int | None = Field(default=None, ge=1, le=50, alias="llmMaxChunks")
    debug_chunks: bool = Field(default=False, alias="debugChunks")

    @field_validator("pr_url")
    @classmethod
    def validate_pr_url(cls, value: str) -> str:
        try:
            parse_pr_url(value)
        except PRUrlError as exc:
            raise ValueError(str(exc)) from exc
        return value


class ReviewJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: JobStatus
    command: str
    request: ReviewRunRequest
    created_at: str = Field(alias="createdAt")
    started_at: str | None = Field(default=None, alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    exit_code: int | None = Field(default=None, alias="exitCode")
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    progress: list[ProgressEvent] = Field(default_factory=list)


def build_cli_args(request: ReviewRunRequest) -> list[str]:
    args = [
        request.pr_url,
        "--format",
        request.output_format,
        "--model",
        request.model_profile,
    ]
    if request.post_comment:
        args.append("--post-comment")
    if request.post_inline_comments:
        args.append("--post-inline-comments")
    if request.fail_on:
        args.extend(["--fail-on", request.fail_on])
    if request.changed_only:
        args.append("--changed-only")
    if request.with_context:
        args.append("--with-context")
    if request.no_llm:
        args.append("--no-llm")
    if request.llm_max_chunks is not None:
        args.extend(["--llm-max-chunks", str(request.llm_max_chunks)])
    if request.debug_chunks:
        args.append("--debug-chunks")
    return args


def display_command(request: ReviewRunRequest) -> str:
    return "ai-pr-review " + " ".join(shlex.quote(arg) for arg in build_cli_args(request))


def github_repos_payload(owner: str, github: object) -> dict:
    repos = []
    for repo in github.list_owner_repositories(owner):  # type: ignore[attr-defined]
        repos.append(
            {
                "name": str(repo.get("name") or ""),
                "fullName": str(repo.get("full_name") or ""),
                "private": bool(repo.get("private")),
                "archived": bool(repo.get("archived")),
                "defaultBranch": str(repo.get("default_branch") or ""),
                "openIssues": int(repo.get("open_issues_count") or 0),
                "updatedAt": str(repo.get("updated_at") or ""),
                "url": str(repo.get("html_url") or ""),
            }
        )
    repos.sort(key=lambda item: (item["archived"], item["updatedAt"]), reverse=False)
    repos.sort(key=lambda item: item["updatedAt"], reverse=True)
    repos.sort(key=lambda item: item["archived"])
    return {"owner": owner, "repos": repos}


def github_pulls_payload(owner: str, repo: str, state: str, github: object) -> dict:
    pulls = []
    for pull in github.list_repository_pulls(owner, repo, state=state):  # type: ignore[attr-defined]
        user = pull.get("user") if isinstance(pull.get("user"), dict) else {}
        pulls.append(
            {
                "number": int(pull.get("number") or 0),
                "title": str(pull.get("title") or ""),
                "url": str(pull.get("html_url") or ""),
                "author": str(user.get("login") or ""),
                "state": str(pull.get("state") or ""),
                "updatedAt": str(pull.get("updated_at") or ""),
            }
        )
    return {"owner": owner, "repo": repo, "state": state, "pulls": pulls}


def inline_preview_payload(report_output: str, raw_diff: str) -> dict:
    try:
        payload = json.loads(report_output)
    except ValueError:
        return _empty_inline_preview("当前报告不是 JSON 输出，无法生成结构化 inline 预览")
    if not isinstance(payload, dict):
        return _empty_inline_preview("当前报告 JSON 结构无效，无法生成 inline 预览")
    findings_payload = payload.get("findings")
    if not isinstance(findings_payload, list):
        return _empty_inline_preview("当前报告缺少 findings，无法生成 inline 预览")

    findings: list[Finding] = []
    for item in findings_payload:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(Finding.model_validate(item))
        except ValidationError:
            continue

    comments, limitations = build_inline_review_comments(findings, parse_diff(raw_diff))
    preview_comments = []
    for comment in comments:
        finding = _finding_for_comment(findings, comment)
        preview_comments.append(
            {
                "path": comment["path"],
                "line": comment["line"],
                "side": comment["side"],
                "body": comment["body"],
                "severity": finding.severity,
                "category": finding.category,
                "confidence": finding.confidence,
            }
        )
    return {
        "comments": preview_comments,
        "commentableCount": len(comments),
        "skippedCount": max(0, len(findings) - len(comments)),
        "limitations": limitations,
    }


def _empty_inline_preview(message: str) -> dict:
    return {
        "comments": [],
        "commentableCount": 0,
        "skippedCount": 0,
        "limitations": [message],
    }


def _finding_for_comment(findings: list[Finding], comment: dict) -> Finding:
    for finding in findings:
        if finding.path == comment["path"] and finding.line == comment["line"]:
            return finding
    raise ValueError("inline comment does not match a finding")


def doctor_payload(
    *,
    config: ReviewConfig,
    github_token: str | None,
    openai_api_key: str | None,
    openai_base_url: str | None,
    api_mode: str,
    model_profile: str,
    smoke: bool,
    smoke_tester: SmokeTester | None = None,
) -> dict:
    report = run_doctor_report(
        config=config,
        github_token=github_token,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        api_mode=api_mode,
        model_profile=model_profile,
        smoke=smoke,
        smoke_tester=smoke_tester,
    )
    return {
        "ok": report.ok,
        "githubTokenConfigured": report.github_token_configured,
        "openaiApiKeyConfigured": report.openai_api_key_configured,
        "openaiBaseUrlConfigured": report.openai_base_url_configured,
        "openaiBaseUrlStatus": report.openai_base_url_status,
        "apiMode": report.api_mode,
        "fastModel": report.fast_model,
        "strongModel": report.strong_model,
        "smokeOk": report.smoke_ok,
        "smokeError": report.smoke_error,
        "warnings": report.warnings,
        "limitations": report.limitations,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _progress_event(
    stage: str,
    label: str,
    status: ProgressStatus,
    message: str | None = None,
    *,
    timestamp: str | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        stage=stage,
        label=label,
        status=status,
        timestamp=timestamp or _now(),
        message=message,
    )


def _subprocess_executor(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    src_dir = Path(__file__).resolve().parents[1]
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{current}" if current else str(src_dir)
    return env


class ReviewJobStore:
    def __init__(
        self,
        *,
        executor: Executor = _subprocess_executor,
        cwd: Path | None = None,
        python_executable: str | None = None,
        max_jobs: int = 30,
        storage_dir: Path | None = None,
    ) -> None:
        self._executor = executor
        self._cwd = cwd or Path.cwd()
        self._python_executable = python_executable or sys.executable
        self._max_jobs = max_jobs
        self._storage_dir = storage_dir
        self._jobs: dict[str, ReviewJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._load_from_disk()

    def start(self, request: ReviewRunRequest) -> ReviewJob:
        created_at = _now()
        job = ReviewJob(
            id=uuid.uuid4().hex,
            status="queued",
            command=display_command(request),
            request=request,
            createdAt=created_at,
            progress=[
                _progress_event(
                    "queued",
                    "任务已入队",
                    "completed",
                    timestamp=created_at,
                )
            ],
        )
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._persist_locked(job)
        thread = threading.Thread(target=self._run, args=(job.id,), daemon=True)
        thread.start()
        return self.get(job.id)

    def get(self, job_id: str) -> ReviewJob:
        with self._lock:
            job = self._jobs[job_id]
            return job.model_copy(deep=True)

    def list_recent(
        self,
        *,
        query: str = "",
        status: JobStatus | None = None,
        repository: str = "",
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict]:
        with self._lock:
            jobs = []
            for job_id in reversed(self._order):
                job = self._jobs[job_id]
                if not _matches_history_filters(
                    job,
                    query=query,
                    status=status,
                    repository=repository,
                    created_from=created_from,
                    created_to=created_to,
                ):
                    continue
                jobs.append(job.model_copy(deep=True))
                if len(jobs) >= self._max_jobs:
                    break
        return [_job_summary(job) for job in jobs]

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {"queued", "running"}:
                raise ValueError("运行中的 Review 任务不能删除")
            del self._jobs[job_id]
            self._order = [current_id for current_id in self._order if current_id != job_id]
            self._delete_files_locked(job_id)
            return True

    def clear_finished(self) -> int:
        with self._lock:
            deletable_ids = [
                job_id
                for job_id in self._order
                if self._jobs[job_id].status not in {"queued", "running"}
            ]
            for job_id in deletable_ids:
                del self._jobs[job_id]
                self._delete_files_locked(job_id)
            deleted_ids = set(deletable_ids)
            self._order = [job_id for job_id in self._order if job_id not in deleted_ids]
            return len(deletable_ids)

    def export(self, job_id: str, output_format: Literal["markdown", "json"]) -> str:
        job = self.get(job_id)
        if output_format == "json":
            return json.dumps(job.model_dump(by_alias=True), ensure_ascii=False, indent=2)
        output = job.stdout or job.stderr or job.error
        if output:
            return output
        return f"# AI PR Review\n\n任务状态：{job.status}\n"

    def _replace(self, job: ReviewJob) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._persist_locked(job)

    def _load_from_disk(self) -> None:
        if self._storage_dir is None or not self._storage_dir.exists():
            return
        for path in sorted(self._storage_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                job = ReviewJob.model_validate(payload)
            except (OSError, ValueError, ValidationError):
                continue
            if job.status in {"queued", "running"}:
                job.status = "failed"
                job.finished_at = job.finished_at or _now()
                job.error = job.error or "Web 服务重启前任务未完成"
                job.progress.append(
                    _progress_event(
                        "process_error",
                        "服务重启前任务中断",
                        "failed",
                        job.error,
                        timestamp=job.finished_at,
                    )
                )
                try:
                    path.write_text(job.model_dump_json(by_alias=True), encoding="utf-8")
                except OSError:
                    pass
            self._jobs[job.id] = job
            self._order.append(job.id)

    def _persist_locked(self, job: ReviewJob) -> None:
        if self._storage_dir is None:
            return
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        target = self._storage_dir / f"{job.id}.json"
        target.write_text(job.model_dump_json(by_alias=True), encoding="utf-8")

    def _delete_files_locked(self, job_id: str) -> None:
        if self._storage_dir is None:
            return
        for suffix in (".json", ".progress.jsonl"):
            try:
                (self._storage_dir / f"{job_id}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        job.status = "running"
        job.started_at = _now()
        job.progress.append(
            _progress_event(
                "process_start",
                "启动 Review 进程",
                "completed",
                timestamp=job.started_at,
            )
        )
        self._replace(job)
        command = [self._python_executable, "-m", "ai_pr_review", *build_cli_args(job.request)]
        env = _build_env()
        progress_path = self._progress_path(job.id)
        stop_monitor = threading.Event()
        monitor_thread: threading.Thread | None = None
        if progress_path is not None:
            env[PROGRESS_FILE_ENV] = str(progress_path)
            monitor_thread = threading.Thread(
                target=self._monitor_progress_file,
                args=(job.id, progress_path, stop_monitor),
                daemon=True,
            )
            monitor_thread.start()
        try:
            result = self._executor(command, cwd=self._cwd, env=env)
        except Exception as exc:  # pragma: no cover - defensive process boundary
            stop_monitor.set()
            if monitor_thread is not None:
                monitor_thread.join(timeout=0.5)
            if progress_path is not None:
                self._refresh_progress_from_file(job_id, progress_path)
            job = self.get(job_id)
            job.status = "failed"
            job.finished_at = _now()
            job.error = str(exc)
            job.progress.append(
                _progress_event(
                    "process_error",
                    "Review 进程异常退出",
                    "failed",
                    str(exc),
                    timestamp=job.finished_at,
                )
            )
            self._replace(job)
            return

        stop_monitor.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=0.5)
        if progress_path is not None:
            self._refresh_progress_from_file(job_id, progress_path)

        job = self.get(job_id)
        job.status = "succeeded" if result.returncode == 0 else "failed"
        job.finished_at = _now()
        job.exit_code = result.returncode
        job.stdout = result.stdout
        job.stderr = result.stderr
        job.progress.append(
            _progress_event(
                "process_exit",
                "Review 进程完成" if result.returncode == 0 else "Review 进程失败",
                "completed" if result.returncode == 0 else "failed",
                f"exit {result.returncode}",
                timestamp=job.finished_at,
            )
        )
        self._replace(job)

    def _progress_path(self, job_id: str) -> Path | None:
        if self._storage_dir is None:
            return None
        return self._storage_dir / f"{job_id}.progress.jsonl"

    def _monitor_progress_file(
        self,
        job_id: str,
        path: Path,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.wait(0.25):
            self._refresh_progress_from_file(job_id, path)
        self._refresh_progress_from_file(job_id, path)

    def _refresh_progress_from_file(self, job_id: str, path: Path) -> None:
        raw_events = read_progress_events(path)
        if not raw_events:
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            existing = {_progress_key(event) for event in job.progress}
            changed = False
            for raw_event in raw_events:
                try:
                    event = ProgressEvent.model_validate(raw_event)
                except ValidationError:
                    continue
                key = _progress_key(event)
                if key in existing:
                    continue
                job.progress.append(event)
                existing.add(key)
                changed = True
            if changed:
                self._persist_locked(job)


def create_handler(
    *,
    store: ReviewJobStore,
    frontend_dir: Path,
) -> type[BaseHTTPRequestHandler]:
    static_root = frontend_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "AIPrReviewWeb/0.1"

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                self._send_json({"ok": True})
                return
            if path == "/api/doctor":
                self._handle_doctor()
                return
            if path == "/api/reviews":
                self._handle_review_list()
                return
            if path.startswith("/api/reviews/") and path.endswith("/export"):
                self._handle_review_export(path)
                return
            if path.startswith("/api/reviews/") and path.endswith("/inline-preview"):
                job_id = path.split("/")[-2]
                try:
                    job = store.get(job_id)
                except KeyError:
                    self._send_json({"error": "review job not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(_inline_preview_for_job(job))
                return
            if path == "/api/github/repos":
                self._handle_github_repos()
                return
            if path.startswith("/api/github/repos/") and path.endswith("/pulls"):
                self._handle_github_pulls(path)
                return
            if path.startswith("/api/reviews/"):
                job_id = path.rsplit("/", 1)[-1]
                try:
                    job = store.get(job_id)
                except KeyError:
                    self._send_json({"error": "review job not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(_job_payload(job))
                return
            if path.startswith("/api/"):
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._serve_static(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/reviews":
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return

            try:
                payload = self._read_json()
                request = ReviewRunRequest.model_validate(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except ValidationError as exc:
                self._send_json({"error": "invalid review request", "details": exc.errors()}, status=422)
                return

            job = store.start(request)
            self._send_json(_job_payload(job), status=HTTPStatus.ACCEPTED)

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/reviews":
                deleted = store.clear_finished()
                self._send_json({"deleted": deleted})
                return
            if path.startswith("/api/reviews/"):
                job_id = path.rsplit("/", 1)[-1]
                try:
                    deleted = store.delete(job_id)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
                    return
                if not deleted:
                    self._send_json({"error": "review job not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"deleted": 1})
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_review_list(self) -> None:
            params = parse_qs(urlparse(self.path).query)
            status = (params.get("status") or [""])[0].strip() or None
            if status is not None and status not in {"queued", "running", "succeeded", "failed"}:
                self._send_json(
                    {"error": "status 只能是 queued、running、succeeded 或 failed"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                jobs = store.list_recent(
                    query=(params.get("query") or [""])[0],
                    status=status,
                    repository=(params.get("repo") or [""])[0],
                    created_from=(params.get("from") or [None])[0],
                    created_to=(params.get("to") or [None])[0],
                )
            except ValueError:
                self._send_json(
                    {"error": "日期格式必须是 YYYY-MM-DD"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"jobs": jobs})

        def _handle_review_export(self, path: str) -> None:
            job_id = path.split("/")[-2]
            params = parse_qs(urlparse(self.path).query)
            output_format = (params.get("format") or ["markdown"])[0].strip() or "markdown"
            if output_format not in {"markdown", "json"}:
                self._send_json(
                    {"error": "format 只能是 markdown 或 json"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            export_format: Literal["markdown", "json"] = (
                "json" if output_format == "json" else "markdown"
            )
            try:
                content = store.export(job_id, export_format)
            except KeyError:
                self._send_json({"error": "review job not found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = (
                "application/json; charset=utf-8"
                if output_format == "json"
                else "text/markdown; charset=utf-8"
            )
            extension = "json" if output_format == "json" else "md"
            self._send_text(
                content,
                content_type=content_type,
                filename=f"ai-pr-review-{job_id}.{extension}",
            )

        def _handle_doctor(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            smoke = (query.get("smoke") or ["false"])[0].lower() == "true"
            model_profile = (query.get("model") or ["balanced"])[0]
            if model_profile not in {"fast", "balanced", "accurate"}:
                self._send_json(
                    {"error": "model 只能是 fast、balanced 或 accurate"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                config = load_config()
                payload = doctor_payload(
                    config=config,
                    github_token=resolve_github_token(config),
                    openai_api_key=resolve_openai_api_key(config),
                    openai_base_url=resolve_openai_base_url(config),
                    api_mode=resolve_openai_api_mode(config),
                    model_profile=model_profile,
                    smoke=smoke,
                )
            except (ValueError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(payload)

        def _handle_github_repos(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            owner = (query.get("owner") or [""])[0].strip()
            if not _valid_owner_or_repo(owner):
                self._send_json(
                    {"error": "请输入有效的 GitHub 用户名或组织名"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                with _github_client() as github:
                    self._send_json(github_repos_payload(owner, github))
            except GitHubAPIError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)

        def _handle_github_pulls(self, path: str) -> None:
            parts = [part for part in path.split("/") if part]
            if len(parts) != 6:
                self._send_json({"error": "invalid pulls path"}, status=HTTPStatus.NOT_FOUND)
                return
            owner = unquote(parts[3]).strip()
            repo = unquote(parts[4]).strip()
            query = parse_qs(urlparse(self.path).query)
            state = (query.get("state") or ["open"])[0].strip() or "open"
            if not _valid_owner_or_repo(owner) or not _valid_owner_or_repo(repo):
                self._send_json(
                    {"error": "请输入有效的 owner 和 repo"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            if state not in {"open", "closed", "all"}:
                self._send_json(
                    {"error": "state 只能是 open、closed 或 all"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                with _github_client() as github:
                    self._send_json(github_pulls_payload(owner, repo, state, github))
            except GitHubAPIError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or "0")
            if length > 1024 * 1024:
                raise ValueError("request body is too large")
            body = self.rfile.read(length)
            if not body:
                return {}
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ValueError("request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _serve_static(self, path: str) -> None:
            if not static_root.exists():
                self._send_json(
                    {
                        "error": "frontend build not found",
                        "hint": "run: cd frontend && npm install && npm run build",
                    },
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            rel_path = unquote(path.lstrip("/")) or "index.html"
            target = (static_root / rel_path).resolve()
            if not _is_relative_to(target, static_root):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.exists() or target.is_dir():
                target = static_root / "index.html"
            if not target.exists():
                self._send_json(
                    {"error": "frontend index.html not found"},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(
            self,
            content: str,
            *,
            content_type: str,
            filename: str | None = None,
            status: int = HTTPStatus.OK,
        ) -> None:
            data = content.encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

    return Handler


def run_web_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    frontend_dir: str | Path | None = None,
) -> int:
    root = Path(__file__).resolve().parents[2]
    static_dir = Path(frontend_dir) if frontend_dir else root / "frontend" / "dist"
    store = ReviewJobStore(cwd=root, storage_dir=root / ".ai-pr-review" / "runs")
    handler = create_handler(store=store, frontend_dir=static_dir)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"AI PR Review Web 正在运行：http://{host}:{port}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止 AI PR Review Web。")
    finally:
        server.server_close()
    return 0


def _job_payload(job: ReviewJob) -> dict:
    return job.model_dump(by_alias=True)


def _progress_key(event: ProgressEvent) -> tuple[str, str, str, str, str | None]:
    return (event.stage, event.status, event.timestamp, event.label, event.message)


def _job_summary(job: ReviewJob) -> dict:
    output = job.stdout or job.stderr or job.error or ""
    return {
        "id": job.id,
        "status": job.status,
        "command": job.command,
        "request": job.request.model_dump(by_alias=True),
        "createdAt": job.created_at,
        "startedAt": job.started_at,
        "finishedAt": job.finished_at,
        "exitCode": job.exit_code,
        "outputPreview": output[:180],
        "progress": [event.model_dump(exclude_none=True) for event in job.progress],
    }


def _matches_history_filters(
    job: ReviewJob,
    *,
    query: str,
    status: JobStatus | None,
    repository: str,
    created_from: str | None,
    created_to: str | None,
) -> bool:
    if status and job.status != status:
        return False

    repository_filter = repository.strip().lower()
    repository_slug = _job_repository(job)
    if repository_filter and repository_filter not in repository_slug.lower():
        return False

    created_date = _job_created_date(job)
    from_date = _parse_history_date(created_from)
    to_date = _parse_history_date(created_to)
    if from_date and (created_date is None or created_date < from_date):
        return False
    if to_date and (created_date is None or created_date > to_date):
        return False

    keyword = query.strip().lower()
    if not keyword:
        return True
    haystack = "\n".join(
        [
            job.id,
            job.status,
            job.command,
            job.request.pr_url,
            repository_slug,
            job.stdout,
            job.stderr,
            job.error or "",
        ]
    ).lower()
    return keyword in haystack


def _job_repository(job: ReviewJob) -> str:
    try:
        ref = parse_pr_url(job.request.pr_url)
    except PRUrlError:
        return ""
    return f"{ref.owner}/{ref.repo}"


def _job_created_date(job: ReviewJob) -> date | None:
    try:
        return datetime.fromisoformat(job.created_at.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_history_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _inline_preview_for_job(job: ReviewJob) -> dict:
    ref = parse_pr_url(job.request.pr_url)
    with _github_client() as github:
        raw_diff = github.get_pr_diff(ref)
    return inline_preview_payload(job.stdout, raw_diff)


class _GitHubClientContext:
    def __init__(self) -> None:
        config = load_config()
        self._client = GitHubClient(token=resolve_github_token(config))

    def __enter__(self) -> GitHubClient:
        return self._client

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._client.close()


def _github_client() -> _GitHubClientContext:
    return _GitHubClientContext()


def _valid_owner_or_repo(value: str) -> bool:
    return bool(value) and bool(re.match(OWNER_REPO_PATTERN, value))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
