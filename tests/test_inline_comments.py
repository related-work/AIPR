from __future__ import annotations

from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.inline_comments import build_inline_review_comments
from ai_pr_review.schemas import Finding


RAW_DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 def handler(user_id):
-    return db.query("select * from users where id=" + user_id)
+    query = f"select * from users where id={user_id}"
+    return db.query(query)
 
 def ok():
"""


def finding(**overrides) -> Finding:
    data = {
        "path": "src/app.py",
        "line": 2,
        "severity": "high",
        "category": "security",
        "confidence": 0.91,
        "evidence": ['+    query = f"select * from users where id={user_id}"'],
        "problem": "SQL 拼接可能导致注入。",
        "suggestion": "使用参数化查询。",
        "blocking": True,
        "source": "llm",
    }
    data.update(overrides)
    return Finding(**data)


def test_build_inline_review_comments_maps_high_confidence_added_lines() -> None:
    diff_files = parse_diff(RAW_DIFF)

    comments, limitations = build_inline_review_comments([finding()], diff_files)

    assert limitations == []
    assert comments == [
        {
            "path": "src/app.py",
            "line": 2,
            "side": "RIGHT",
            "body": (
                "**AI PR Review: high security**\n\n"
                "SQL 拼接可能导致注入。\n\n"
                "**证据**\n"
                "- `+    query = f\"select * from users where id={user_id}\"`\n\n"
                "**建议**\n"
                "使用参数化查询。\n\n"
                "置信度：0.91；阻塞合并：是。"
            ),
        }
    ]


def test_build_inline_review_comments_skips_lines_not_added_in_diff() -> None:
    diff_files = parse_diff(RAW_DIFF)

    comments, limitations = build_inline_review_comments([finding(line=4)], diff_files)

    assert comments == []
    assert "已跳过 1 条无法映射到 diff 新增行的 inline comment" in limitations


def test_build_inline_review_comments_only_posts_actionable_findings() -> None:
    diff_files = parse_diff(RAW_DIFF)
    findings = [
        finding(severity="medium", confidence=0.95),
        finding(confidence=0.7),
        finding(blocking=False),
    ]

    comments, limitations = build_inline_review_comments(findings, diff_files)

    assert comments == []
    assert limitations == ["已跳过 3 条低风险、低置信度或非阻塞 finding 的 inline comment"]
