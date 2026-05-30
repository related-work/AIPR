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


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pr_url: str
    title: str
    summary: str
    scope: list[ScopeItem] = Field(default_factory=list)
    risk_overview: RiskOverview = Field(default_factory=RiskOverview)
    findings: list[Finding] = Field(default_factory=list)
    chunk_debug: list[ChunkSummary] = Field(default_factory=list)
    test_suggestions: list[str] = Field(default_factory=list)
    merge_recommendation: MergeRecommendation
    limitations: list[str] = Field(default_factory=list)
