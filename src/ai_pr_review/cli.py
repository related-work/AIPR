from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from ai_pr_review.aggregate import aggregate_report, should_fail_ci
from ai_pr_review.config import (
    load_config,
    resolve_github_token,
    resolve_openai_api_key,
    resolve_openai_api_mode,
    resolve_openai_base_url,
)
from ai_pr_review.context import retrieve_context
from ai_pr_review.diff_parser import build_chunks, parse_diff
from ai_pr_review.github import GitHubAPIError, GitHubClient, PRUrlError, parse_pr_url
from ai_pr_review.llm import analyze_chunks, select_models, verify_high_risk_findings
from ai_pr_review.render import render_json, render_markdown
from ai_pr_review.rules import run_rules
from ai_pr_review.schemas import ReviewReport


Runner = Callable[..., ReviewReport]


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    run = runner or run_review
    try:
        report = run(
            pr_url=args.pr_url,
            output_format=args.output_format,
            post_comment=args.post_comment,
            fail_on=args.fail_on,
            model_profile=args.model_profile,
            changed_only=args.changed_only,
            with_context=args.with_context,
            no_llm=args.no_llm,
        )
    except (PRUrlError, GitHubAPIError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=stderr)
        return 2

    rendered = render_json(report) if args.output_format == "json" else render_markdown(report)
    print(rendered, end="", file=stdout)
    return 1 if should_fail_ci(report, args.fail_on) else 0


def run_review(
    *,
    pr_url: str,
    output_format: str,
    post_comment: bool,
    fail_on: str | None,
    model_profile: str,
    changed_only: bool,
    with_context: bool,
    no_llm: bool = False,
) -> ReviewReport:
    config = load_config()
    effective_fail_on = fail_on or config.review.fail_on
    ref = parse_pr_url(pr_url)
    github = GitHubClient(token=resolve_github_token(config))
    try:
        pr = github.get_pr(ref)
        files = github.list_pr_files(ref)
        commits = github.list_pr_commits(ref)
        issue_comments = github.list_issue_comments(ref)
        review_comments = github.list_review_comments(ref)
        raw_diff = github.get_pr_diff(ref)

        diff_files = parse_diff(raw_diff)
        chunks, limitations = build_chunks(
            diff_files,
            files,
            changed_only=changed_only,
            ignore_paths=config.review.ignore_paths,
        )
        context = retrieve_context(
            github,
            ref,
            pr,
            chunks,
            enabled=with_context and not changed_only,
        )
        limitations.extend(context.limitations)

        rule_findings = run_rules(files, diff_files, config)
        fast_model, strong_model = select_models(config, model_profile)
        openai_api_key = resolve_openai_api_key(config)
        openai_base_url = resolve_openai_base_url(config)
        openai_api_mode = resolve_openai_api_mode(config)
        pr_summary = _pr_summary(pr, files, commits)
        llm_findings, llm_limitations = analyze_chunks(
            chunks,
            pr_summary=pr_summary,
            context=context,
            comments_summary=_comments_summary(issue_comments + review_comments),
            model=fast_model,
            api_key=openai_api_key,
            base_url=openai_base_url,
            api_mode=openai_api_mode,
            timeout_seconds=config.openai.timeout_seconds,
            enabled=not no_llm,
        )
        limitations.extend(llm_limitations)

        verified_findings, verify_limitations = verify_high_risk_findings(
            [*rule_findings, *llm_findings],
            context=context,
            model=strong_model,
            api_key=openai_api_key,
            base_url=openai_base_url,
            api_mode=openai_api_mode,
            timeout_seconds=config.openai.timeout_seconds,
            enabled=not no_llm,
        )
        limitations.extend(verify_limitations)

        report = aggregate_report(
            pr=pr,
            files=files,
            commits=commits,
            comments=issue_comments + review_comments,
            findings=verified_findings,
            limitations=limitations,
        )

        if post_comment:
            rendered = render_json(report) if output_format == "json" else render_markdown(report)
            github.create_issue_comment(ref, rendered)
        return report
    finally:
        github.close()


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-pr-review",
        description="Analyze a GitHub Pull Request and print an AI-assisted review report.",
    )
    parser.add_argument("pr_url", help="GitHub Pull Request URL")
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "json"],
        default="markdown",
        help="Report output format",
    )
    parser.add_argument(
        "--post-comment",
        action="store_true",
        help="Post the rendered report as a GitHub PR comment",
    )
    parser.add_argument(
        "--fail-on",
        choices=["critical", "high", "medium", "low"],
        default=None,
        help="Return a non-zero exit code when blocking findings meet this threshold",
    )
    parser.add_argument(
        "--model",
        dest="model_profile",
        choices=["fast", "balanced", "accurate"],
        default="balanced",
        help="Model profile for LLM analysis",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Analyze only PR diff without fetching related file context",
    )
    parser.add_argument(
        "--with-context",
        action="store_true",
        help="Fetch heuristic related files for additional context",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM analysis and return a rules-only report",
    )
    return parser


def _pr_summary(pr: dict, files: list[dict], commits: list[dict]) -> str:
    title = str(pr.get("title") or "未命名 PR")
    body = str(pr.get("body") or "").strip()
    file_count = len(files)
    commit_count = len(commits)
    return f"{title}\n文件数：{file_count}\ncommit 数：{commit_count}\n描述：{body[:500] or '无'}"


def _comments_summary(comments: list[dict]) -> str:
    bodies = []
    for comment in comments[:10]:
        body = str(comment.get("body") or "").strip()
        if body:
            bodies.append(body[:300])
    return "\n---\n".join(bodies)
