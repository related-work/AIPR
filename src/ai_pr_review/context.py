from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ai_pr_review.diff_parser import DiffChunk
from ai_pr_review.github import GitHubClient, PRReference


MAX_CONTEXT_CHARS = 24_000
MAX_FILE_CHARS = 4_000
CONFIG_CANDIDATES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    ".github/workflows/ci.yml",
    ".github/workflows/test.yml",
]


@dataclass
class RetrievedContext:
    files: dict[str, str] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def as_prompt_text(self) -> str:
        if not self.files:
            return "未检索到额外上下文。"
        parts: list[str] = []
        total = 0
        for path, content in self.files.items():
            clipped = content[:MAX_FILE_CHARS]
            block = f"### {path}\n```\n{clipped}\n```"
            if total + len(block) > MAX_CONTEXT_CHARS:
                self.limitations.append("上下文达到大小限制，后续文件已省略")
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts)


def retrieve_context(
    github: GitHubClient,
    ref: PRReference,
    pr: dict,
    chunks: list[DiffChunk],
    *,
    enabled: bool,
) -> RetrievedContext:
    context = RetrievedContext()
    if not enabled:
        context.limitations.append("未启用上下文检索，仅基于 diff 和规则进行分析")
        return context

    git_ref = _head_sha(pr)
    if not git_ref:
        context.limitations.append("未能识别 PR head sha，无法检索额外文件上下文")
        return context

    paths = _candidate_paths(chunks)
    for path in paths:
        text = github.get_file_text(ref, path, git_ref)
        if text is None:
            continue
        context.files[path] = text[:MAX_FILE_CHARS]
        if sum(len(value) for value in context.files.values()) >= MAX_CONTEXT_CHARS:
            context.limitations.append("上下文达到大小限制，停止继续检索")
            break
    return context


def _head_sha(pr: dict) -> str | None:
    head = pr.get("head")
    if isinstance(head, dict):
        sha = head.get("sha")
        if isinstance(sha, str):
            return sha
    return None


def _candidate_paths(chunks: list[DiffChunk]) -> list[str]:
    candidates: list[str] = []
    for chunk in chunks:
        candidates.append(chunk.path)
        candidates.extend(_test_candidates(chunk.path))
        candidates.extend(_local_import_candidates(chunk.patch, chunk.path))
    candidates.extend(CONFIG_CANDIDATES)
    return _unique(candidates)


def _test_candidates(path: str) -> list[str]:
    pure = PurePosixPath(path)
    stem = pure.stem
    suffix = pure.suffix
    parent = str(pure.parent)
    if suffix == ".py":
        return [
            f"tests/test_{stem}.py",
            f"test/test_{stem}.py",
            f"{parent}/test_{stem}.py",
            f"{parent}/{stem}_test.py",
        ]
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        return [
            f"{parent}/{stem}.test{suffix}",
            f"{parent}/{stem}.spec{suffix}",
            f"tests/{stem}.test{suffix}",
            f"tests/{stem}.spec{suffix}",
        ]
    return []


def _local_import_candidates(patch: str, changed_path: str) -> list[str]:
    if PurePosixPath(changed_path).suffix != ".py":
        return []
    candidates: list[str] = []
    for match in re.finditer(r"^\+?\s*from\s+([a-zA-Z_][\w.]*)\s+import\s+", patch, re.MULTILINE):
        module = match.group(1)
        if module.startswith("."):
            continue
        candidates.append(module.replace(".", "/") + ".py")
    for match in re.finditer(r"^\+?\s*import\s+([a-zA-Z_][\w.]*)", patch, re.MULTILINE):
        module = match.group(1)
        candidates.append(module.replace(".", "/") + ".py")
    return candidates


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
