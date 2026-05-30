from __future__ import annotations

from typing import Any

from ai_pr_review.schemas import CommentContext


MAX_COMMENT_ITEMS = 12
MAX_COMMENT_BODY_CHARS = 300


def build_comment_context(
    *,
    issue_comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    pull_reviews: list[dict[str, Any]],
) -> CommentContext:
    issue_copilot = sum(1 for item in issue_comments if _is_copilot(item))
    review_copilot = sum(1 for item in review_comments if _is_copilot(item))
    pull_review_copilot = sum(1 for item in pull_reviews if _is_copilot(item))
    review_paths = sorted(
        {
            str(item.get("path"))
            for item in review_comments
            if isinstance(item.get("path"), str) and item.get("path")
        }
    )
    prompt_text = _build_prompt_text(
        issue_comments=issue_comments,
        review_comments=review_comments,
        pull_reviews=pull_reviews,
        issue_copilot=issue_copilot,
        review_copilot=review_copilot,
        pull_review_copilot=pull_review_copilot,
        path=None,
    )
    path_prompt_texts = {
        path: _build_prompt_text(
            issue_comments=issue_comments,
            review_comments=review_comments,
            pull_reviews=pull_reviews,
            issue_copilot=issue_copilot,
            review_copilot=review_copilot,
            pull_review_copilot=pull_review_copilot,
            path=path,
        )
        for path in review_paths
    }
    return CommentContext(
        issue_comments=len(issue_comments),
        review_comments=len(review_comments),
        pull_reviews=len(pull_reviews),
        copilot_issue_comments=issue_copilot,
        copilot_review_comments=review_copilot,
        copilot_pull_reviews=pull_review_copilot,
        prompt_text=prompt_text,
        path_prompt_texts=path_prompt_texts,
    )


def _build_prompt_text(
    *,
    issue_comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    pull_reviews: list[dict[str, Any]],
    issue_copilot: int,
    review_copilot: int,
    pull_review_copilot: int,
    path: str | None,
) -> str:
    prompt_review_comments = [
        comment
        for comment in review_comments
        if path is None or str(comment.get("path") or "") == path
    ]
    lines = [
        "已有评论上下文（仅作为背景，不能作为 finding 证据）：",
        (
            f"issue_comments={len(issue_comments)}, "
            f"review_comments={len(review_comments)}, "
            f"pull_reviews={len(pull_reviews)}, "
            f"copilot_issue_comments={issue_copilot}, "
            f"copilot_review_comments={review_copilot}, "
            f"copilot_pull_reviews={pull_review_copilot}"
        ),
    ]
    snippets = [
        *_comment_snippets("issue", issue_comments),
        *_comment_snippets("review_comment", prompt_review_comments),
        *_comment_snippets("pull_review", pull_reviews),
    ]
    if not snippets:
        lines.append("无评论正文摘要。")
    else:
        lines.extend(snippets[:MAX_COMMENT_ITEMS])
    return "\n".join(lines)


def _comment_snippets(kind: str, comments: list[dict[str, Any]]) -> list[str]:
    snippets: list[str] = []
    for comment in comments:
        body = str(comment.get("body") or "").strip()
        if not body:
            continue
        author = _author_login(comment)
        copilot = "Copilot" if _is_copilot(comment) else "human"
        path = str(comment.get("path") or "")
        state = str(comment.get("state") or "")
        location = f" path={path}" if path else ""
        review_state = f" state={state}" if state else ""
        clipped = " ".join(body.split())[:MAX_COMMENT_BODY_CHARS]
        snippets.append(f"- [{kind} {copilot} author={author}{location}{review_state}] {clipped}")
    return snippets


def _is_copilot(comment: dict[str, Any]) -> bool:
    login = _author_login(comment).lower()
    return "copilot" in login


def _author_login(comment: dict[str, Any]) -> str:
    user = comment.get("user")
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login:
            return login
    return "unknown"
