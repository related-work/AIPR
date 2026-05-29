from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath
import re


DOCUMENTATION_EXTENSIONS = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".adoc",
}
IMAGE_BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".woff",
    ".woff2",
}
LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
}
MANIFESTS = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "composer.json",
}


@dataclass(frozen=True)
class DiffLine:
    kind: str
    content: str
    old_line_no: int | None
    new_line_no: int | None


@dataclass(frozen=True)
class DiffHunk:
    old_start: int
    old_length: int
    new_start: int
    new_length: int
    section_header: str
    lines: list[DiffLine]

    @property
    def patch(self) -> str:
        return "\n".join(line.content for line in self.lines)


@dataclass(frozen=True)
class DiffFile:
    path: str
    old_path: str | None
    status: str
    hunks: list[DiffHunk]
    patch: str


@dataclass(frozen=True)
class FileClassification:
    path: str
    is_documentation: bool = False
    is_generated: bool = False
    is_lockfile: bool = False
    is_manifest: bool = False
    is_binary: bool = False

    @property
    def should_skip_model(self) -> bool:
        return (
            self.is_documentation
            or self.is_generated
            or self.is_lockfile
            or self.is_binary
        )


@dataclass(frozen=True)
class DiffChunk:
    path: str
    patch: str
    old_start: int | None
    new_start: int | None
    old_length: int | None
    new_length: int | None
    classification: FileClassification
    context: str = ""


def parse_diff(raw_diff: str) -> list[DiffFile]:
    if not raw_diff.strip():
        return []
    files: list[DiffFile] = []

    current_path: str | None = None
    current_old_path: str | None = None
    current_status = "modified"
    current_hunks: list[DiffHunk] = []
    patch_parts: list[str] = []
    hunk_lines: list[DiffLine] | None = None
    hunk_old_start = hunk_old_length = hunk_new_start = hunk_new_length = 0
    hunk_header = ""
    old_line_no = new_line_no = 0

    def finish_hunk() -> None:
        nonlocal hunk_lines
        if hunk_lines is None:
            return
        current_hunks.append(
            DiffHunk(
                old_start=hunk_old_start,
                old_length=hunk_old_length,
                new_start=hunk_new_start,
                new_length=hunk_new_length,
                section_header=hunk_header,
                lines=hunk_lines,
            )
        )
        hunk_lines = None

    def finish_file() -> None:
        nonlocal current_path, current_old_path, current_status, current_hunks, patch_parts
        finish_hunk()
        if current_path is None:
            return
        files.append(
            DiffFile(
                path=current_path,
                old_path=current_old_path,
                status=current_status,
                hunks=current_hunks,
                patch="\n".join(patch_parts),
            )
        )
        current_path = None
        current_old_path = None
        current_status = "modified"
        current_hunks = []
        patch_parts = []

    hunk_re = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)")

    for raw_line in raw_diff.splitlines():
        if raw_line.startswith("diff --git "):
            finish_file()
            parts = raw_line.split()
            old = parts[2][2:] if len(parts) >= 4 and parts[2].startswith("a/") else None
            new = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else old
            current_old_path = old
            current_path = new
            continue
        if current_path is None:
            continue
        if raw_line.startswith("--- "):
            source = raw_line[4:]
            current_old_path = None if source == "/dev/null" else _strip_prefix(source)
            if source == "/dev/null":
                current_status = "added"
            continue
        if raw_line.startswith("+++ "):
            target = raw_line[4:]
            current_path = current_old_path if target == "/dev/null" else _strip_prefix(target)
            if target == "/dev/null":
                current_status = "removed"
            continue
        if raw_line.startswith("rename from "):
            current_old_path = raw_line.removeprefix("rename from ").strip()
            current_status = "renamed"
            continue
        if raw_line.startswith("rename to "):
            current_path = raw_line.removeprefix("rename to ").strip()
            current_status = "renamed"
            continue

        hunk_match = hunk_re.match(raw_line)
        if hunk_match:
            finish_hunk()
            hunk_old_start = int(hunk_match.group(1))
            hunk_old_length = int(hunk_match.group(2) or "1")
            hunk_new_start = int(hunk_match.group(3))
            hunk_new_length = int(hunk_match.group(4) or "1")
            hunk_header = hunk_match.group(5) or ""
            old_line_no = hunk_old_start
            new_line_no = hunk_new_start
            hunk_lines = []
            patch_parts.append(raw_line)
            continue

        if hunk_lines is None:
            continue
        if raw_line.startswith("\\ No newline"):
            patch_parts.append(raw_line)
            continue
        prefix = raw_line[:1]
        if prefix == "+":
            hunk_lines.append(
                DiffLine("add", raw_line, old_line_no=None, new_line_no=new_line_no)
            )
            new_line_no += 1
        elif prefix == "-":
            hunk_lines.append(
                DiffLine("remove", raw_line, old_line_no=old_line_no, new_line_no=None)
            )
            old_line_no += 1
        else:
            content = raw_line if prefix == " " else f" {raw_line}"
            hunk_lines.append(
                DiffLine(
                    "context",
                    content,
                    old_line_no=old_line_no,
                    new_line_no=new_line_no,
                )
            )
            old_line_no += 1
            new_line_no += 1
        patch_parts.append(raw_line)

    finish_file()
    return files


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def classify_file(path: str, github_file: dict | None = None) -> FileClassification:
    posix = path.replace("\\", "/")
    suffix = PurePosixPath(posix).suffix
    return FileClassification(
        path=posix,
        is_documentation=_is_documentation(posix, suffix),
        is_generated=is_generated_file(posix),
        is_lockfile=is_lockfile(posix),
        is_manifest=PurePosixPath(posix).name in MANIFESTS,
        is_binary=is_binary_file(github_file or {"filename": posix, "patch": "..."}),
    )


def _is_documentation(path: str, suffix: str) -> bool:
    return (
        suffix.lower() in DOCUMENTATION_EXTENSIONS
        or path.startswith("docs/")
        or path.startswith("doc/")
    )


def is_generated_file(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        ".generated." in lowered
        or name.endswith(".pb.go")
        or name.endswith(".g.dart")
        or name.endswith(".designer.cs")
        or "/generated/" in lowered
        or lowered.startswith("generated/")
        or lowered.startswith("dist/")
        or lowered.startswith("build/")
    )


def is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name in LOCKFILES


def is_manifest(path: str) -> bool:
    return PurePosixPath(path).name in MANIFESTS


def is_binary_file(github_file: dict) -> bool:
    filename = str(github_file.get("filename", ""))
    patch = github_file.get("patch")
    suffix = PurePosixPath(filename).suffix.lower()
    return patch is None or suffix in IMAGE_BINARY_EXTENSIONS


def build_chunks(
    diff_files: list[DiffFile],
    github_files: list[dict],
    *,
    changed_only: bool = False,
    ignore_paths: list[str] | None = None,
) -> tuple[list[DiffChunk], list[str]]:
    ignore_paths = ignore_paths or []
    github_by_path = {str(file.get("filename")): file for file in github_files}
    diff_by_path = {file.path: file for file in diff_files}
    paths = list(dict.fromkeys([*diff_by_path.keys(), *github_by_path.keys()]))
    chunks: list[DiffChunk] = []
    limitations: list[str] = []

    for path in paths:
        if any(fnmatch(path, pattern) for pattern in ignore_paths):
            limitations.append(f"已按配置忽略 {path}")
            continue
        github_file = github_by_path.get(path, {"filename": path, "patch": "..."})
        classification = classify_file(path, github_file)
        if classification.is_binary:
            limitations.append(f"跳过二进制文件 {path}")
            continue
        if classification.is_documentation:
            limitations.append(f"跳过文档文件 {path}")
            continue
        if classification.is_generated:
            limitations.append(f"跳过生成文件 {path}")
            continue
        if classification.is_lockfile:
            limitations.append(f"跳过 lockfile {path}，仅由规则引擎检查依赖一致性")
            continue

        diff_file = diff_by_path.get(path)
        if diff_file is None:
            continue
        for hunk in diff_file.hunks:
            chunks.append(
                DiffChunk(
                    path=path,
                    patch="\n".join([hunk.section_header, hunk.patch]).strip(),
                    old_start=hunk.old_start,
                    new_start=hunk.new_start,
                    old_length=hunk.old_length,
                    new_length=hunk.new_length,
                    classification=classification,
                )
            )

    return chunks, limitations
