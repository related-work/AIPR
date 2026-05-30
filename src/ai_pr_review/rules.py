from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import PurePosixPath

from ai_pr_review.config import ReviewConfig
from ai_pr_review.diff_parser import DiffFile, DiffLine, is_lockfile, is_manifest
from ai_pr_review.schemas import Finding


SECRET_RE = re.compile(
    r"(?i)\b[\w-]*(api[_-]?key|secret|token|password|private[_-]?key)[\w-]*\b\s*[:=]\s*[\"'][^\"']{3,}[\"']"
)
SQL_RE = re.compile(
    r"(?i)(select|insert|update|delete)\s+.*(\+|\{[^}]+\}|%\s*\(|\.format\()"
)
AUTH_RE = re.compile(r"(?i)(require_admin|authorize|authenticate|permission|is_admin|check_auth)")
MODEL_COLUMN_RE = re.compile(r"\b(Column|Field|models\.)\b")


def run_rules(
    github_files: list[dict],
    diff_files: list[DiffFile],
    config: ReviewConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    changed_paths = [str(file.get("filename", "")) for file in github_files]
    diff_by_path = {file.path: file for file in diff_files}

    for diff_file in diff_files:
        findings.extend(_scan_file(diff_file))

    findings.extend(_scan_manifest_lock_consistency(changed_paths))
    findings.extend(_scan_migration_risk(changed_paths, diff_by_path))
    findings.extend(_scan_required_tests(changed_paths, config))
    return findings


def _scan_file(diff_file: DiffFile) -> list[Finding]:
    findings: list[Finding] = []
    all_lines = [line for hunk in diff_file.hunks for line in hunk.lines]
    added = [line for line in all_lines if line.kind == "add"]
    removed = [line for line in all_lines if line.kind == "remove"]
    non_removed = [line for line in all_lines if line.kind != "remove"]

    for line in non_removed:
        if SECRET_RE.search(line.content):
            findings.append(
                _finding(
                    rule_id="possible_secret",
                    path=diff_file.path,
                    line=line.new_line_no,
                    severity="critical",
                    category="security",
                    confidence=0.9,
                    evidence=[line.content.strip()],
                    problem="疑似密钥或敏感凭据出现在 PR 变更上下文中。",
                    suggestion="移除硬编码凭据，改用安全的密钥管理或环境变量，并轮换已暴露的凭据。",
                )
            )
            break

    for line in added:
        if SQL_RE.search(line.content):
            findings.append(
                _finding(
                    rule_id="sql_string_interpolation",
                    path=diff_file.path,
                    line=line.new_line_no,
                    severity="high",
                    category="security",
                    confidence=0.82,
                    evidence=[line.content.strip()],
                    problem="SQL 语句疑似通过字符串拼接或插值构造，存在注入风险。",
                    suggestion="改用参数化查询或 ORM 提供的安全绑定接口。",
                )
            )
            break

    if _has_weakened_assertion(removed, added):
        line_no = next((line.new_line_no for line in added if "assert" in line.content), None)
        findings.append(
            _finding(
                rule_id="test_assertion_weakened",
                path=diff_file.path,
                line=line_no,
                severity="medium",
                category="test",
                confidence=0.78,
                evidence=[
                    *(line.content.strip() for line in removed if "assert" in line.content),
                    *(line.content.strip() for line in added if "assert" in line.content),
                ][:4],
                problem="测试断言可能被削弱，原先的精确断言被替换为更宽松的条件。",
                suggestion="确认断言变更是否必要；如果行为改变是预期的，应补充覆盖新旧边界的测试。",
            )
        )

    for line in removed:
        if AUTH_RE.search(line.content):
            findings.append(
                _finding(
                    rule_id="auth_check_removed",
                    path=diff_file.path,
                    line=line.old_line_no,
                    severity="high",
                    category="security",
                    confidence=0.82,
                    evidence=[line.content.strip()],
                    problem="鉴权或权限检查相关代码被删除，可能扩大访问权限。",
                    suggestion="确认是否有等价鉴权逻辑迁移到其他位置；否则恢复权限校验并增加未授权访问测试。",
                )
            )
            break

    return findings


def _has_weakened_assertion(removed: list[DiffLine], added: list[DiffLine]) -> bool:
    removed_asserts = [line.content for line in removed if "assert" in line.content]
    added_asserts = [line.content for line in added if "assert" in line.content]
    if not removed_asserts or not added_asserts:
        return False
    for old in removed_asserts:
        for new in added_asserts:
            if _assertion_strength(new) < _assertion_strength(old):
                return True
    return False


def _assertion_strength(assertion: str) -> int:
    text = assertion.strip()
    if re.search(r"\bassert\s+.+\s+==\s+.+", text):
        return 3
    if re.search(r"\bassert\s+.+\s+in\s+.+", text):
        return 2
    if re.search(r"\bassert\s+.+\s+!=\s+.+", text):
        return 1
    if re.search(r"\bassert\s+not\s+", text):
        return 1
    return 1


def _scan_manifest_lock_consistency(changed_paths: list[str]) -> list[Finding]:
    manifest_changed = [path for path in changed_paths if is_manifest(path)]
    lock_changed = any(is_lockfile(path) for path in changed_paths)
    if not manifest_changed or lock_changed:
        return []
    return [
        _finding(
            rule_id="manifest_without_lockfile",
            path=manifest_changed[0],
            line=None,
            severity="medium",
            category="compatibility",
            confidence=0.76,
            evidence=[f"changed manifest(s): {', '.join(manifest_changed)}"],
            problem="依赖 manifest 已变更，但未看到对应 lockfile 变更。",
            suggestion="确认依赖解析结果是否需要提交 lockfile，避免 CI 或生产环境安装到不同版本。",
            blocking=False,
        )
    ]


def _scan_migration_risk(
    changed_paths: list[str],
    diff_by_path: dict[str, DiffFile],
) -> list[Finding]:
    migration_changed = any("migration" in path.lower() for path in changed_paths)
    if migration_changed:
        return []
    for path, diff_file in diff_by_path.items():
        lowered = path.lower()
        if not (
            "/model" in lowered
            or lowered.startswith("models/")
            or "/schema" in lowered
            or "schema" in lowered
        ):
            continue
        added_lines = [
            line
            for hunk in diff_file.hunks
            for line in hunk.lines
            if line.kind == "add" and MODEL_COLUMN_RE.search(line.content)
        ]
        if added_lines:
            return [
                _finding(
                    rule_id="migration_risk",
                    path=path,
                    line=added_lines[0].new_line_no,
                    severity="high",
                    category="compatibility",
                    confidence=0.78,
                    evidence=[added_lines[0].content.strip(), "未看到 migration 文件变更"],
                    problem="数据模型或 schema 发生变化，但 PR 中未看到对应 migration。",
                    suggestion="补充数据库迁移，或说明该字段无需迁移的原因，并增加兼容性测试。",
                )
            ]
    return []


def _scan_required_tests(changed_paths: list[str], config: ReviewConfig) -> list[Finding]:
    if not config.rules.require_tests_for:
        return []
    test_changed = any(_is_test_path(path) for path in changed_paths)
    if test_changed:
        return []
    findings: list[Finding] = []
    for path in changed_paths:
        if _is_test_path(path):
            continue
        if any(fnmatch(path, pattern) for pattern in config.rules.require_tests_for):
            findings.append(
                _finding(
                    rule_id="missing_required_tests",
                    path=path,
                    line=None,
                    severity="high",
                    category="test",
                    confidence=0.8,
                    evidence=[
                        f"{path} 匹配 require_tests_for 规则，但本次 PR 未包含测试文件变更"
                    ],
                    problem="高风险路径发生变更，但未看到测试文件同步更新。",
                    suggestion="补充覆盖该变更行为的单元测试、集成测试或在 PR 中说明无需测试的理由。",
                )
            )
    return findings


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        lowered.startswith("test/")
        or lowered.startswith("tests/")
        or "/test/" in lowered
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.tsx")
    )


def _finding(
    *,
    rule_id: str,
    path: str,
    line: int | None,
    severity,
    category,
    confidence: float,
    evidence: list[str],
    problem: str,
    suggestion: str,
    blocking: bool | None = None,
) -> Finding:
    should_block = (
        severity in {"critical", "high"}
        and confidence >= 0.75
        and bool(evidence)
        if blocking is None
        else blocking
    )
    return Finding(
        path=path,
        line=line,
        severity=severity,
        category=category,
        confidence=confidence,
        evidence=evidence,
        problem=problem,
        suggestion=suggestion,
        blocking=should_block,
        source="rule",
        rule_id=rule_id,
    )
