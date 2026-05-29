from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class PRUrlError(ValueError):
    """Raised when a GitHub PR URL cannot be parsed."""


class GitHubAPIError(RuntimeError):
    """Raised for user-facing GitHub API failures."""


@dataclass(frozen=True)
class PRReference:
    owner: str
    repo: str
    number: int

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"


def parse_pr_url(url: str) -> PRReference:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise PRUrlError("请输入形如 https://github.com/org/repo/pull/123 的 GitHub PR URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "pull":
        raise PRUrlError("URL 路径必须包含 /owner/repo/pull/number")
    try:
        number = int(parts[3])
    except ValueError as exc:
        raise PRUrlError("PR number 必须是整数") from exc
    return PRReference(owner=parts[0], repo=parts[1], number=number)


class GitHubClient:
    def __init__(self, token: str | None = None, *, timeout: float = 30.0) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-pr-review/0.1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=httpx.Timeout(timeout),
        )

    def close(self) -> None:
        self._client.close()

    def get_pr(self, ref: PRReference) -> dict[str, Any]:
        return self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")

    def list_pr_files(self, ref: PRReference) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/files")

    def list_pr_commits(self, ref: PRReference) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/commits")

    def list_issue_comments(self, ref: PRReference) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments")

    def list_review_comments(self, ref: PRReference) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/comments")

    def get_pr_diff(self, ref: PRReference) -> str:
        response = self._request(
            "GET",
            f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}",
            headers={"Accept": "application/vnd.github.diff"},
        )
        return response.text

    def create_issue_comment(self, ref: PRReference, body: str) -> dict[str, Any]:
        return self._post(
            f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments",
            json={"body": body},
        )

    def get_file_text(self, ref: PRReference, path: str, git_ref: str) -> str | None:
        response = self._request(
            "GET",
            f"/repos/{ref.owner}/{ref.repo}/contents/{path}",
            params={"ref": git_ref},
            allow_not_found=True,
        )
        if response is None:
            return None
        data = response.json()
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        content = str(data.get("content", ""))
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except ValueError:
            return None

    def _get(self, path: str) -> dict[str, Any]:
        response = self._request("GET", path)
        return response.json()

    def _post(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", path, json=json)
        return response.json()

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                path,
                params={"per_page": 100, "page": page},
            )
            batch = response.json()
            if not isinstance(batch, list):
                raise GitHubAPIError(f"GitHub API 返回了非列表分页数据: {path}")
            if not batch:
                break
            items.extend(batch)
            page += 1
        return items

    def _request(
        self,
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        **kwargs: Any,
    ) -> httpx.Response | None:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubAPIError(f"GitHub API 请求超时: {path}") from exc
        except httpx.RequestError as exc:
            raise GitHubAPIError(f"GitHub API 请求失败: {path}: {exc}") from exc

        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code >= 400:
            message = _extract_error_message(response)
            raise GitHubAPIError(
                f"GitHub API 请求失败: {method} {path} -> HTTP {response.status_code}: {message}"
            )
        return response


def _extract_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(data, dict):
        return str(data.get("message") or data)[:300]
    return str(data)[:300]
