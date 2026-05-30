from __future__ import annotations

from ai_pr_review.comments import build_comment_context


def test_build_comment_context_counts_copilot_review_comments_and_reviews() -> None:
    context = build_comment_context(
        issue_comments=[
            {
                "user": {"login": "alice"},
                "body": "普通 PR 评论",
            }
        ],
        review_comments=[
            {
                "user": {"login": "Copilot"},
                "path": "src/app.py",
                "body": "Copilot 行内评论",
            },
            {
                "user": {"login": "bob"},
                "path": "tests/test_app.py",
                "body": "人工行内评论",
            },
        ],
        pull_reviews=[
            {
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "state": "COMMENTED",
                "body": "Copilot reviewed 2 files and generated comments.",
            }
        ],
    )

    assert context.issue_comments == 1
    assert context.review_comments == 2
    assert context.pull_reviews == 1
    assert context.copilot_issue_comments == 0
    assert context.copilot_review_comments == 1
    assert context.copilot_pull_reviews == 1


def test_comment_context_prompt_marks_comments_as_background_only() -> None:
    context = build_comment_context(
        issue_comments=[],
        review_comments=[
            {
                "user": {"login": "Copilot"},
                "path": "src/app.py",
                "body": "This endpoint may be risky.",
            }
        ],
        pull_reviews=[
            {
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "state": "COMMENTED",
                "body": "Review summary body",
            }
        ],
    )

    prompt_text = context.as_prompt_text()

    assert "仅作为背景" in prompt_text
    assert "review_comments=1" in prompt_text
    assert "pull_reviews=1" in prompt_text
    assert "Copilot" in prompt_text
    assert "Review summary body" in prompt_text


def test_comment_context_prompt_filters_review_comments_by_path() -> None:
    context = build_comment_context(
        issue_comments=[],
        review_comments=[
            {
                "user": {"login": "Copilot"},
                "path": "src/app.py",
                "body": "app comment",
            },
            {
                "user": {"login": "Copilot"},
                "path": "src/db.py",
                "body": "db comment",
            },
        ],
        pull_reviews=[
            {
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "state": "COMMENTED",
                "body": "global summary",
            }
        ],
    )

    prompt_text = context.as_prompt_text(path="src/app.py")

    assert "app comment" in prompt_text
    assert "db comment" not in prompt_text
    assert "global summary" in prompt_text
