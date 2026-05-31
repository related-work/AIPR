from __future__ import annotations

import json

from ai_pr_review.render import render_json, render_markdown
from ai_pr_review.schemas import (
    AnalysisCoverage,
    AnalysisFileCoverage,
    BudgetLimits,
    ChunkSummary,
    CommentContext,
    Finding,
    ReviewReport,
    RiskOverview,
    ScopeItem,
    SkippedReason,
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
            ChunkSummary(
                path="src/ui.py",
                old_start=1,
                new_start=1,
                score=0,
                reasons=["default"],
                selected=False,
            ),
        ],
        analysis_coverage=AnalysisCoverage(
            large_pr=True,
            changed_files=12,
            analyzed_files=3,
            skipped_files=9,
            total_chunks=8,
            llm_analyzed_chunks=2,
            rules_scanned_files=11,
            coverage_ratio=0.25,
            budget_limits=BudgetLimits(
                max_files=10,
                max_chunks=8,
                max_llm_chunks=2,
                max_context_files=5,
                max_patch_lines_per_chunk=200,
            ),
            skipped_reasons=[
                SkippedReason(reason="over_budget_low_risk", count=6),
                SkippedReason(reason="documentation", count=3),
            ],
            file_coverage=[
                AnalysisFileCoverage(
                    path="src/auth/service.py",
                    status="analyzed",
                    reason="llm_analyzed",
                    risk_score=80,
                    reasons=["auth", "security_path"],
                    high_risk_unreviewed=False,
                ),
                AnalysisFileCoverage(
                    path="src/payment/service.py",
                    status="rule_only",
                    reason="over_budget_low_risk",
                    risk_score=70,
                    reasons=["payment"],
                    high_risk_unreviewed=True,
                ),
                AnalysisFileCoverage(
                    path="assets/logo.png",
                    status="skipped",
                    reason="binary_file",
                    risk_score=0,
                    reasons=["binary_file"],
                    high_risk_unreviewed=False,
                ),
            ],
        ),
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
    assert "## Chunk 调试" in markdown
    assert "src/auth/service.py:12" in markdown
    assert "auth, security_path" in markdown
    assert "行内评论：6（Copilot 6）" in markdown
    assert "Review 总结：1（Copilot 1）" in markdown
    assert "## 分析覆盖率" in markdown
    assert "大 PR：是" in markdown
    assert "LLM 分析 chunk：2 / 8" in markdown
    assert "over_budget_low_risk：6" in markdown
    assert "### 高风险未深度分析文件" in markdown
    assert "src/payment/service.py" in markdown
    assert "### 文件覆盖明细" in markdown
    assert "| src/auth/service.py | analyzed | llm_analyzed | 80 | 否 |" in markdown
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
    assert payload["analysisCoverage"]["largePr"] is True
    assert payload["analysisCoverage"]["budgetLimits"]["maxLlmChunks"] == 2
    assert payload["analysisCoverage"]["skippedReasons"][0]["reason"] == "over_budget_low_risk"
    assert payload["analysisCoverage"]["fileCoverage"][1]["highRiskUnreviewed"] is True
