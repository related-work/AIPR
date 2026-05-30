from __future__ import annotations

import json

from ai_pr_review.render import render_json, render_markdown
from ai_pr_review.schemas import (
    ChunkSummary,
    CommentContext,
    Finding,
    ReviewReport,
    RiskOverview,
    ScopeItem,
)


def _report() -> ReviewReport:
    return ReviewReport(
        pr_url="https://github.com/org/repo/pull/1",
        title="Auth change",
        summary="调整鉴权逻辑",
        scope=[ScopeItem(module="src/auth", files=1, description="认证模块")],
        risk_overview=RiskOverview(high=1, blocking=1),
        findings=[
            Finding(
                path="src/auth/service.py",
                line=12,
                severity="high",
                category="security",
                confidence=0.91,
                evidence=["removed require_admin"],
                problem="鉴权检查被删除",
                suggestion="恢复 require_admin",
                blocking=True,
                source="rule",
            )
        ],
        comment_context=CommentContext(
            review_comments=6,
            pull_reviews=1,
            copilot_review_comments=6,
            copilot_pull_reviews=1,
        ),
        chunk_debug=[
            ChunkSummary(
                path="src/auth/service.py",
                old_start=10,
                new_start=12,
                score=80,
                reasons=["auth", "security_path"],
                selected=True,
            ),
        ],
        test_suggestions=["增加无权限访问测试"],
        merge_recommendation="do_not_merge",
        limitations=["未运行测试套件"],
    )


def test_render_markdown_contains_required_sections() -> None:
    markdown = render_markdown(_report())

    assert "# AI PR Review" in markdown
    assert "## PR 总结" in markdown
    assert "## 改动范围" in markdown
    assert "## 风险总览" in markdown
    assert "## 重点问题列表" in markdown
    assert "## 文件级 Review 建议" in markdown
    assert "## 测试建议" in markdown
    assert "## 是否建议合并" in markdown
    assert "## 评论上下文" in markdown
    assert "行内评论：6（Copilot 6）" in markdown
    assert "Review 总结：1（Copilot 1）" in markdown
    assert "## Chunk 调试" in markdown
    assert "auth, security_path" in markdown
    assert "## 分析限制" in markdown
    assert "src/auth/service.py:12" in markdown


def test_render_json_is_machine_readable() -> None:
    payload = json.loads(render_json(_report()))

    assert payload["mergeRecommendation"] == "do_not_merge"
    assert payload["riskOverview"]["blocking"] == 1
    assert payload["findings"][0]["path"] == "src/auth/service.py"
    assert payload["commentContext"]["reviewComments"] == 6
    assert payload["commentContext"]["copilotPullReviews"] == 1
    assert payload["chunkDebug"][0]["path"] == "src/auth/service.py"
    assert payload["chunkDebug"][0]["selected"] is True
