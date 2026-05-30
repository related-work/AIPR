from __future__ import annotations

from ai_pr_review.diff_parser import DiffChunk
from ai_pr_review.schemas import ChunkSummary


PATH_REASON_RULES: tuple[tuple[str, int, str], ...] = (
    ("auth", 50, "auth"),
    ("permission", 45, "auth"),
    ("security", 45, "security_path"),
    ("user", 20, "api_or_user"),
    ("admin", 35, "admin"),
    ("payment", 35, "payment"),
    ("billing", 35, "payment"),
    ("db", 30, "db"),
    ("database", 30, "db"),
    ("migration", 35, "migration"),
    ("route", 20, "api"),
    ("api", 20, "api"),
    ("test", 25, "test"),
)

PATCH_REASON_RULES: tuple[tuple[str, int, str], ...] = (
    ("select ", 70, "sql"),
    ("insert ", 60, "sql"),
    ("update ", 60, "sql"),
    ("delete ", 60, "sql"),
    ("require_admin", 70, "auth"),
    ("authorization", 60, "auth"),
    ("permission", 50, "auth"),
    ("depends(", 35, "api"),
    ("@app.", 35, "api"),
    ("httpexception", 25, "api"),
    ("assert ", 25, "test"),
    ("status_code", 20, "test"),
    ("migration", 35, "migration"),
    ("transaction", 35, "transaction"),
    ("lock", 25, "concurrency"),
)


def prioritize_chunks(
    chunks: list[DiffChunk],
    *,
    max_chunks: int | None,
) -> tuple[list[DiffChunk], list[ChunkSummary], list[str]]:
    scored = [
        (_score_chunk(chunk), index, chunk)
        for index, chunk in enumerate(chunks)
    ]
    scored.sort(key=lambda item: (-item[0].score, item[1]))
    selected_limit = len(scored) if max_chunks is None or max_chunks < 0 else max_chunks
    selected_ids = {id(chunk) for _, _, chunk in scored[:selected_limit]}
    selected_chunks = [chunk for _, _, chunk in scored[:selected_limit]]
    debug = [
        summary.model_copy(update={"selected": id(chunk) in selected_ids})
        for summary, _, chunk in scored
    ]
    limitations: list[str] = []
    if max_chunks is not None and max_chunks >= 0 and len(scored) > max_chunks:
        limitations.append(
            f"LLM 分析已按风险优先选择前 {max_chunks} 个 chunk，跳过 {len(scored) - max_chunks} 个 chunk"
        )
    return selected_chunks, debug, limitations


def _score_chunk(chunk: DiffChunk) -> ChunkSummary:
    score = 0
    reasons: list[str] = []
    path = chunk.path.lower()
    patch = chunk.patch.lower()
    for needle, weight, reason in PATH_REASON_RULES:
        if needle in path:
            score += weight
            reasons.append(reason)
    for needle, weight, reason in PATCH_REASON_RULES:
        if needle in patch:
            score += weight
            reasons.append(reason)
    if not reasons:
        reasons.append("default")
    return ChunkSummary(
        path=chunk.path,
        old_start=chunk.old_start,
        new_start=chunk.new_start,
        score=score,
        reasons=_unique(reasons),
        selected=False,
    )


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
