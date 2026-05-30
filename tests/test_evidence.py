from __future__ import annotations

from ai_pr_review.context import RetrievedContext
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.evidence import verify_finding_evidence
from ai_pr_review.schemas import Finding


RAW_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 def get_user(user_id):
-    return db.get_user(user_id)
+    query = f"SELECT * FROM users WHERE id = {user_id}"
"""


def test_evidence_verifier_keeps_llm_blocker_with_diff_evidence() -> None:
    finding = Finding(
        path="src/app.py",
        line=3,
        severity="high",
        category="security",
        confidence=0.9,
        evidence=['+    query = f"SELECT * FROM users WHERE id = {user_id}"'],
        problem="SQL 通过字符串插值构造，存在注入风险。",
        suggestion="使用参数化查询。",
        blocking=True,
        source="llm",
    )

    verified, limitations = verify_finding_evidence(
        [finding],
        diff_files=parse_diff(RAW_DIFF),
        context=RetrievedContext(),
    )

    assert verified == [finding]
    assert limitations == []


def test_evidence_verifier_drops_llm_finding_only_supported_by_comments() -> None:
    finding = Finding(
        path="src/app.py",
        line=None,
        severity="medium",
        category="compatibility",
        confidence=0.85,
        evidence=["Copilot 行内评论指出其他接口仍返回旧错误文案"],
        problem="根据已有评论，接口错误文案不一致。",
        suggestion="按评论更新其他接口。",
        blocking=False,
        source="llm",
    )

    verified, limitations = verify_finding_evidence(
        [finding],
        diff_files=parse_diff(RAW_DIFF),
        context=RetrievedContext(),
    )

    assert verified == []
    assert limitations == ["已丢弃 1 条缺少 diff 或上下文代码证据的 LLM finding"]


def test_evidence_verifier_ignores_background_evidence_even_with_matching_code() -> None:
    finding = Finding(
        path="src/app.py",
        line=None,
        severity="low",
        category="compatibility",
        confidence=0.7,
        evidence=['相关背景信息提到新增了 `query = f"SELECT * FROM users WHERE id = {user_id}"`'],
        problem="根据背景信息推断存在兼容性问题。",
        suggestion="检查其他接口。",
        blocking=False,
        source="llm",
    )

    verified, limitations = verify_finding_evidence(
        [finding],
        diff_files=parse_diff(RAW_DIFF),
        context=RetrievedContext(),
    )

    assert verified == []
    assert limitations == ["已丢弃 1 条缺少 diff 或上下文代码证据的 LLM finding"]


def test_evidence_verifier_drops_low_confidence_llm_findings() -> None:
    finding = Finding(
        path="src/app.py",
        line=1,
        severity="low",
        category="test",
        confidence=0.5,
        evidence=['+    query = f"SELECT * FROM users WHERE id = {user_id}"'],
        problem="低置信度测试建议。",
        suggestion="检查测试。",
        blocking=False,
        source="llm",
    )

    verified, limitations = verify_finding_evidence(
        [finding],
        diff_files=parse_diff(RAW_DIFF),
        context=RetrievedContext(),
    )

    assert verified == []
    assert limitations == ["已丢弃 1 条低置信度 LLM finding"]


def test_evidence_verifier_downgrades_blocker_without_diff_but_with_context() -> None:
    finding = Finding(
        path="src/app.py",
        line=None,
        severity="high",
        category="logic",
        confidence=0.9,
        evidence=["helper_requires_transaction"],
        problem="上下文显示调用方需要事务，但 diff 未直接证明会破坏事务。",
        suggestion="补充事务边界。",
        blocking=True,
        source="llm",
    )
    context = RetrievedContext(files={"src/helpers.py": "def helper_requires_transaction(): pass"})

    verified, limitations = verify_finding_evidence(
        [finding],
        diff_files=parse_diff(RAW_DIFF),
        context=context,
    )

    assert len(verified) == 1
    assert verified[0].severity == "medium"
    assert verified[0].confidence == 0.65
    assert verified[0].blocking is False
    assert limitations == ["已降级 1 条缺少 diff 证据的阻塞候选"]


def test_evidence_verifier_preserves_rule_findings() -> None:
    finding = Finding(
        path="pyproject.toml",
        line=None,
        severity="medium",
        category="compatibility",
        confidence=0.76,
        evidence=["changed manifest(s): pyproject.toml"],
        problem="依赖 manifest 已变更，但未看到 lockfile 变更。",
        suggestion="确认 lockfile 是否需要更新。",
        blocking=False,
        source="rule",
        rule_id="manifest_without_lockfile",
    )

    verified, limitations = verify_finding_evidence(
        [finding],
        diff_files=parse_diff(RAW_DIFF),
        context=RetrievedContext(),
    )

    assert verified == [finding]
    assert limitations == []
