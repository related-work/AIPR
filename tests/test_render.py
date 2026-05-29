from __future__ import annotations

import json

from ai_pr_review.render import render_json, render_markdown
from ai_pr_review.schemas import Finding, ReviewReport, RiskOverview, ScopeItem


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
    assert "## 分析限制" in markdown
    assert "src/auth/service.py:12" in markdown


def test_render_json_is_machine_readable() -> None:
    payload = json.loads(render_json(_report()))

    assert payload["mergeRecommendation"] == "do_not_merge"
    assert payload["riskOverview"]["blocking"] == 1
    assert payload["findings"][0]["path"] == "src/auth/service.py"
