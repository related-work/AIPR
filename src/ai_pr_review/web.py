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
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ai_pr_review.config import load_config, resolve_github_token
from ai_pr_review.github import GitHubAPIError, GitHubClient, PRUrlError, parse_pr_url


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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
    ) -> None:
        self._executor = executor
        self._cwd = cwd or Path.cwd()
        self._python_executable = python_executable or sys.executable
        self._jobs: dict[str, ReviewJob] = {}
        self._lock = threading.Lock()

    def start(self, request: ReviewRunRequest) -> ReviewJob:
        job = ReviewJob(
            id=uuid.uuid4().hex,
            status="queued",
            command=display_command(request),
            request=request,
            createdAt=_now(),
        )
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job.id,), daemon=True)
        thread.start()
        return self.get(job.id)

    def get(self, job_id: str) -> ReviewJob:
        with self._lock:
            job = self._jobs[job_id]
            return job.model_copy(deep=True)

    def _replace(self, job: ReviewJob) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        job.status = "running"
        job.started_at = _now()
        self._replace(job)
        command = [self._python_executable, "-m", "ai_pr_review", *build_cli_args(job.request)]
        try:
            result = self._executor(command, cwd=self._cwd, env=_build_env())
        except Exception as exc:  # pragma: no cover - defensive process boundary
            job = self.get(job_id)
            job.status = "failed"
            job.finished_at = _now()
            job.error = str(exc)
            self._replace(job)
            return

        job = self.get(job_id)
        job.status = "succeeded" if result.returncode == 0 else "failed"
        job.finished_at = _now()
        job.exit_code = result.returncode
        job.stdout = result.stdout
        job.stderr = result.stderr
        self._replace(job)


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

        def log_message(self, format: str, *args: object) -> None:
            return

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

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    return Handler


def run_web_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    frontend_dir: str | Path | None = None,
) -> int:
    root = Path(__file__).resolve().parents[2]
    static_dir = Path(frontend_dir) if frontend_dir else root / "frontend" / "dist"
    store = ReviewJobStore(cwd=root)
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
