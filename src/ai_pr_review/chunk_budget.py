from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ai_pr_review.chunk_priority import prioritize_chunks
from ai_pr_review.diff_parser import DiffChunk, classify_file
from ai_pr_review.schemas import (
    AnalysisCoverage,
    AnalysisFileCoverage,
    BudgetLimits,
    ChunkSummary,
    SkippedReason,
)


HIGH_RISK_UNREVIEWED_THRESHOLD = 40


class ReviewBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_files: int | None = None
    max_chunks: int | None = None
    max_llm_chunks: int | None = None
    max_context_files: int | None = None
    max_patch_lines_per_chunk: int | None = None
    large_pr_file_threshold: int = 30
    large_pr_line_threshold: int = 3000

    @property
    def limits(self) -> BudgetLimits:
        return BudgetLimits(
            max_files=self.max_files,
            max_chunks=self.max_chunks,
            max_llm_chunks=self.max_llm_chunks,
            max_context_files=self.max_context_files,
            max_patch_lines_per_chunk=self.max_patch_lines_per_chunk,
        )


@dataclass(frozen=True)
class ChunkBudgetSelection:
    candidate_chunks: list[DiffChunk]
    llm_chunks: list[DiffChunk]
    chunk_debug: list[ChunkSummary]
    limitations: list[str]


def apply_chunk_budget(chunks: list[DiffChunk], budget: ReviewBudget) -> ChunkBudgetSelection:
    ranked_chunks, ranked_debug, _ = prioritize_chunks(chunks, max_chunks=None)
    candidates: list[DiffChunk] = []
    selected_files: set[str] = set()
    skipped_by_file_budget: set[str] = set()
    skipped_by_chunk_budget = 0

    for chunk in ranked_chunks:
        is_new_file = chunk.path not in selected_files
        if (
            budget.max_files is not None
            and budget.max_files >= 0
            and is_new_file
            and len(selected_files) >= budget.max_files
        ):
            skipped_by_file_budget.add(chunk.path)
            continue
        if (
            budget.max_chunks is not None
            and budget.max_chunks >= 0
            and len(candidates) >= budget.max_chunks
        ):
            skipped_by_chunk_budget += 1
            continue
        candidates.append(chunk)
        selected_files.add(chunk.path)

    llm_limit = len(candidates)
    if budget.max_llm_chunks is not None and budget.max_llm_chunks >= 0:
        llm_limit = budget.max_llm_chunks
    llm_chunks = candidates[:llm_limit]
    llm_ids = {id(chunk) for chunk in llm_chunks}
    debug = [
        item.model_copy(update={"selected": id(chunk) in llm_ids})
        for item, chunk in zip(ranked_debug, ranked_chunks, strict=True)
    ]

    limitations: list[str] = []
    if skipped_by_file_budget:
        limitations.append(
            f"文件预算已限制为前 {budget.max_files} 个高优先级文件，"
            f"跳过 {len(skipped_by_file_budget)} 个文件"
        )
    if skipped_by_chunk_budget:
        limitations.append(
            f"chunk 预算已限制为前 {budget.max_chunks} 个高优先级 chunk，"
            f"跳过 {skipped_by_chunk_budget} 个 chunk"
        )
    if len(candidates) > len(llm_chunks):
        limitations.append(
            f"LLM 分析已按风险优先选择前 {len(llm_chunks)} 个 chunk，"
            f"跳过 {len(candidates) - len(llm_chunks)} 个 chunk"
        )
    return ChunkBudgetSelection(
        candidate_chunks=candidates,
        llm_chunks=llm_chunks,
        chunk_debug=debug,
        limitations=limitations,
    )


def build_analysis_coverage(
    *,
    github_files: list[dict],
    chunks: list[DiffChunk],
    llm_chunks: list[DiffChunk],
    budget: ReviewBudget,
    llm_enabled: bool,
) -> AnalysisCoverage:
    changed_files = len(github_files)
    selected_paths = {chunk.path for chunk in llm_chunks}
    chunk_paths = {chunk.path for chunk in chunks}
    risk_by_path = _risk_by_path(chunks)
    skipped_counts: dict[str, int] = {}
    file_coverage: list[AnalysisFileCoverage] = []
    rules_scanned_files = 0

    for github_file in github_files:
        path = str(github_file.get("filename") or "")
        classification = classify_file(path, github_file)
        if not classification.is_binary:
            rules_scanned_files += 1

        reason: str | None = None
        if path in selected_paths:
            file_coverage.append(
                _file_coverage(
                    path=path,
                    status="analyzed",
                    reason="llm_analyzed",
                    risk_by_path=risk_by_path,
                )
            )
            continue
        if classification.is_binary:
            reason = "binary_file"
        elif classification.is_generated:
            reason = "generated_file"
        elif classification.is_lockfile:
            reason = "lockfile"
        elif classification.is_documentation:
            reason = "documentation"
        elif path not in chunk_paths:
            reason = "no_diff_chunk"
        elif not llm_enabled:
            reason = "llm_disabled"
        else:
            reason = "over_budget_low_risk"
        skipped_counts[reason] = skipped_counts.get(reason, 0) + 1
        file_coverage.append(
            _file_coverage(
                path=path,
                status="skipped" if classification.is_binary else "rule_only",
                reason=reason,
                risk_by_path=risk_by_path,
            )
        )

    analyzed_files = len(selected_paths)
    skipped_files = max(0, changed_files - analyzed_files)
    patch_lines = _patch_line_count(github_files)
    coverage_ratio = round(analyzed_files / changed_files, 2) if changed_files else 1.0
    skipped_reasons = [
        SkippedReason(reason=reason, count=count)
        for reason, count in sorted(skipped_counts.items())
    ]
    return AnalysisCoverage(
        large_pr=(
            changed_files >= budget.large_pr_file_threshold
            or patch_lines >= budget.large_pr_line_threshold
        ),
        changed_files=changed_files,
        analyzed_files=analyzed_files,
        skipped_files=skipped_files,
        total_chunks=len(chunks),
        llm_analyzed_chunks=len(llm_chunks),
        rules_scanned_files=rules_scanned_files,
        coverage_ratio=coverage_ratio,
        budget_limits=budget.limits,
        skipped_reasons=skipped_reasons,
        file_coverage=sorted(
            file_coverage,
            key=lambda item: (
                not item.high_risk_unreviewed,
                {"analyzed": 0, "rule_only": 1, "skipped": 2}[item.status],
                -item.risk_score,
                item.path,
            ),
        ),
    )


def _risk_by_path(chunks: list[DiffChunk]) -> dict[str, ChunkSummary]:
    _, debug, _ = prioritize_chunks(chunks, max_chunks=None)
    best: dict[str, ChunkSummary] = {}
    for item in debug:
        current = best.get(item.path)
        if current is None or item.score > current.score:
            best[item.path] = item
    return best


def _file_coverage(
    *,
    path: str,
    status: str,
    reason: str,
    risk_by_path: dict[str, ChunkSummary],
) -> AnalysisFileCoverage:
    risk = risk_by_path.get(path)
    risk_score = risk.score if risk else 0
    reasons = risk.reasons if risk else [reason]
    return AnalysisFileCoverage(
        path=path,
        status=status,
        reason=reason,
        risk_score=risk_score,
        reasons=reasons,
        high_risk_unreviewed=(
            status != "analyzed" and risk_score >= HIGH_RISK_UNREVIEWED_THRESHOLD
        ),
    )


def budget_from_settings(
    *,
    max_files: int | None,
    max_chunks: int | None,
    max_llm_chunks: int | None,
    max_context_files: int | None,
    max_patch_lines_per_chunk: int | None,
    large_pr_file_threshold: int,
    large_pr_line_threshold: int,
) -> ReviewBudget:
    return ReviewBudget(
        max_files=max_files,
        max_chunks=max_chunks,
        max_llm_chunks=max_llm_chunks,
        max_context_files=max_context_files,
        max_patch_lines_per_chunk=max_patch_lines_per_chunk,
        large_pr_file_threshold=large_pr_file_threshold,
        large_pr_line_threshold=large_pr_line_threshold,
    )


def _patch_line_count(github_files: list[dict]) -> int:
    total = 0
    for github_file in github_files:
        additions = github_file.get("additions")
        deletions = github_file.get("deletions")
        if isinstance(additions, int) or isinstance(deletions, int):
            total += int(additions or 0) + int(deletions or 0)
            continue
        patch = github_file.get("patch")
        if isinstance(patch, str):
            total += sum(
                1
                for line in patch.splitlines()
                if line.startswith("+") or line.startswith("-")
            )
    return total
