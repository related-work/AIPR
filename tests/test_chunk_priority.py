from __future__ import annotations

from ai_pr_review.chunk_priority import prioritize_chunks
from ai_pr_review.diff_parser import DiffChunk, FileClassification


def _chunk(path: str, patch: str, *, new_start: int = 1) -> DiffChunk:
    return DiffChunk(
        path=path,
        patch=patch,
        old_start=new_start,
        new_start=new_start,
        old_length=3,
        new_length=3,
        classification=FileClassification(path=path),
    )


def test_prioritize_chunks_orders_high_risk_chunks_first() -> None:
    low_risk = _chunk("src/ui.py", "+label = 'Save'")
    auth_risk = _chunk("src/app/main.py", "-from .auth import require_admin")
    sql_risk = _chunk(
        "src/app/users.py",
        '+query = f"SELECT * FROM users WHERE id = {user_id}"',
    )

    selected, debug, limitations = prioritize_chunks(
        [low_risk, auth_risk, sql_risk],
        max_chunks=2,
    )

    assert [chunk.path for chunk in selected] == ["src/app/users.py", "src/app/main.py"]
    assert [item.path for item in debug] == [
        "src/app/users.py",
        "src/app/main.py",
        "src/ui.py",
    ]
    assert debug[0].selected is True
    assert debug[1].selected is True
    assert debug[2].selected is False
    assert "sql" in debug[0].reasons
    assert "auth" in debug[1].reasons
    assert limitations == ["LLM 分析已按风险优先选择前 2 个 chunk，跳过 1 个 chunk"]


def test_prioritize_chunks_keeps_original_order_for_equal_score() -> None:
    first = _chunk("src/a.py", "+value = 1", new_start=10)
    second = _chunk("src/b.py", "+value = 2", new_start=20)

    selected, debug, limitations = prioritize_chunks([first, second], max_chunks=None)

    assert selected == [first, second]
    assert [item.path for item in debug] == ["src/a.py", "src/b.py"]
    assert all(item.selected for item in debug)
    assert limitations == []
