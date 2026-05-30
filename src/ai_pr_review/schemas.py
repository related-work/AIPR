from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["critical", "high", "medium", "low"]
Category = Literal[
    "logic",
    "security",
    "performance",
    "concurrency",
    "compatibility",
    "test",
    "maintainability",
    "edge_case",
]
MergeRecommendation = Literal["merge", "merge_with_suggestions", "do_not_merge"]
FindingSource = Literal["rule", "llm", "verifier"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    line: int | None = None
    severity: Severity
    category: Category
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    problem: str
    suggestion: str
    blocking: bool = False
    source: FindingSource = "llm"
    rule_id: str | None = None


class ChunkAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)


class ScopeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    files: int
    description: str


class ChunkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    old_start: int | None = None
    new_start: int | None = None
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    selected: bool = False


class RiskOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    blocking: int = 0


class CommentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_comments: int = 0
    review_comments: int = 0
    pull_reviews: int = 0
    copilot_issue_comments: int = 0
    copilot_review_comments: int = 0
    copilot_pull_reviews: int = 0
    prompt_text: str = ""
    path_prompt_texts: dict[str, str] = Field(default_factory=dict, exclude=True)

    def as_prompt_text(self, path: str | None = None) -> str:
        if path and path in self.path_prompt_texts:
            return self.path_prompt_texts[path]
        if self.prompt_text:
            return self.prompt_text
        return (
            "已有评论上下文（仅作为背景，不能作为 finding 证据）：\n"
            f"issue_comments={self.issue_comments}, "
            f"review_comments={self.review_comments}, "
            f"pull_reviews={self.pull_reviews}, "
            f"copilot_issue_comments={self.copilot_issue_comments}, "
            f"copilot_review_comments={self.copilot_review_comments}, "
            f"copilot_pull_reviews={self.copilot_pull_reviews}\n"
            "无评论正文摘要。"
        )


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pr_url: str
    title: str
    summary: str
    scope: list[ScopeItem] = Field(default_factory=list)
    risk_overview: RiskOverview = Field(default_factory=RiskOverview)
    findings: list[Finding] = Field(default_factory=list)
    comment_context: CommentContext = Field(default_factory=CommentContext)
    chunk_debug: list[ChunkSummary] = Field(default_factory=list)
    test_suggestions: list[str] = Field(default_factory=list)
    merge_recommendation: MergeRecommendation
    limitations: list[str] = Field(default_factory=list)
