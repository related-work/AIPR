from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from ai_pr_review.aggregate import aggregate_report, should_fail_ci
from ai_pr_review.chunk_priority import prioritize_chunks
from ai_pr_review.comments import build_comment_context
from ai_pr_review.config import (
    load_config,
    resolve_github_token,
    resolve_openai_api_key,
    resolve_openai_api_mode,
    resolve_openai_base_url,
)
from ai_pr_review.context import retrieve_context
from ai_pr_review.diff_parser import build_chunks, parse_diff
from ai_pr_review.doctor import (
    DoctorReport,
    render_doctor_json,
    render_doctor_markdown,
    run_doctor as run_doctor_report,
)
from ai_pr_review.evidence import verify_finding_evidence
from ai_pr_review.github import GitHubAPIError, GitHubClient, PRUrlError, parse_pr_url
from ai_pr_review.inline_comments import build_inline_review_comments
from ai_pr_review.llm import analyze_chunks, select_models, verify_high_risk_findings
from ai_pr_review.progress import ProgressReporter
from ai_pr_review.quality_eval import (
    QualityEvaluationReport,
    evaluate_builtin_fixtures,
    render_quality_evaluation_json,
    render_quality_evaluation_markdown,
)
from ai_pr_review.render import render_json, render_markdown
from ai_pr_review.rules import run_rules
from ai_pr_review.schemas import ReviewReport


Runner = Callable[..., ReviewReport]
DoctorRunner = Callable[..., DoctorReport]
WebRunner = Callable[..., int]
EvalRunner = Callable[..., QualityEvaluationReport]


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    doctor_runner: DoctorRunner | None = None,
    web_runner: WebRunner | None = None,
    eval_runner: EvalRunner | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    if argv_list and argv_list[0] == "web":
        return _main_web(
            argv_list[1:],
            web_runner=web_runner,
            stdout=stdout,
            stderr=stderr,
        )
    if argv_list and argv_list[0] == "eval":
        return _main_eval(
            argv_list[1:],
            eval_runner=eval_runner,
            stdout=stdout,
            stderr=stderr,
        )
    if argv_list and argv_list[0] == "doctor":
        return _main_doctor(
            argv_list[1:],
            doctor_runner=doctor_runner,
            stdout=stdout,
            stderr=stderr,
        )

    parser = _build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code)

    run = runner or run_review
    try:
        report = run(
            pr_url=args.pr_url,
            output_format=args.output_format,
            post_comment=args.post_comment,
            post_inline_comments=args.post_inline_comments,
            fail_on=args.fail_on,
            model_profile=args.model_profile,
            changed_only=args.changed_only,
            with_context=args.with_context,
            no_llm=args.no_llm,
            llm_max_chunks=args.llm_max_chunks,
            debug_chunks=args.debug_chunks,
        )
    except (PRUrlError, GitHubAPIError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=stderr)
        return 2

    rendered = render_json(report) if args.output_format == "json" else render_markdown(report)
    print(rendered, end="", file=stdout)
    return 1 if should_fail_ci(report, args.fail_on) else 0


def _main_doctor(
    argv: Sequence[str],
    *,
    doctor_runner: DoctorRunner | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    parser = _build_doctor_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code)
    run = doctor_runner or run_doctor
    try:
        report = run(
            output_format=args.output_format,
            model_profile=args.model_profile,
            smoke=not args.no_smoke,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=stderr)
        return 2
    rendered = (
        render_doctor_json(report)
        if args.output_format == "json"
        else render_doctor_markdown(report)
    )
    print(rendered, end="", file=stdout)
    return 0 if report.ok else 2


def _main_eval(
    argv: Sequence[str],
    *,
    eval_runner: EvalRunner | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    parser = _build_eval_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code)
    run = eval_runner or run_quality_eval
    try:
        report = run(fixture_id=args.fixture_id)
    except ValueError as exc:
        print(f"错误：{exc}", file=stderr)
        return 2
    rendered = (
        render_quality_evaluation_json(report)
        if args.output_format == "json"
        else render_quality_evaluation_markdown(report)
    )
    print(rendered, end="", file=stdout)
    return 0 if report.failed == 0 else 1


def _main_web(
    argv: Sequence[str],
    *,
    web_runner: WebRunner | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    parser = _build_web_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code)
    run = web_runner or run_web
    try:
        return run(
            host=args.host,
            port=args.port,
            frontend_dir=args.frontend_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"错误：{exc}", file=stderr)
        return 2


def run_doctor(
    *,
    output_format: str,
    model_profile: str,
    smoke: bool,
) -> DoctorReport:
    config = load_config()
    return run_doctor_report(
        config=config,
        github_token=resolve_github_token(config),
        openai_api_key=resolve_openai_api_key(config),
        openai_base_url=resolve_openai_base_url(config),
        api_mode=resolve_openai_api_mode(config),
        model_profile=model_profile,
        smoke=smoke,
    )


def run_web(
    *,
    host: str,
    port: int,
    frontend_dir: str | None,
) -> int:
    from ai_pr_review.web import run_web_server

    return run_web_server(host=host, port=port, frontend_dir=frontend_dir)


def run_quality_eval(*, fixture_id: str) -> QualityEvaluationReport:
    return evaluate_builtin_fixtures(fixture_id=fixture_id)


def run_review(
    *,
    pr_url: str,
    output_format: str,
    post_comment: bool,
    post_inline_comments: bool,
    fail_on: str | None,
    model_profile: str,
    changed_only: bool,
    with_context: bool,
    no_llm: bool = False,
    llm_max_chunks: int | None = None,
    debug_chunks: bool = False,
) -> ReviewReport:
    progress = ProgressReporter.from_env()
    config = load_config()
    effective_fail_on = fail_on or config.review.fail_on
    ref = parse_pr_url(pr_url)
    github = GitHubClient(token=resolve_github_token(config))
    try:
        progress.emit("github_fetch", "获取 GitHub PR 数据", "running")
        pr = github.get_pr(ref)
        files = github.list_pr_files(ref)
        commits = github.list_pr_commits(ref)
        issue_comments = github.list_issue_comments(ref)
        review_comments = github.list_review_comments(ref)
        pull_reviews = github.list_pull_reviews(ref)
        raw_diff = github.get_pr_diff(ref)
        progress.emit("github_fetch", "GitHub PR 数据获取完成", "completed")

        progress.emit("diff_parse", "解析 PR diff", "running")
        comment_context = build_comment_context(
            issue_comments=issue_comments,
            review_comments=review_comments,
            pull_reviews=pull_reviews,
        )

        diff_files = parse_diff(raw_diff)
        chunks, limitations = build_chunks(
            diff_files,
            files,
            changed_only=changed_only,
            ignore_paths=config.review.ignore_paths,
        )
        progress.emit(
            "diff_parse",
            "PR diff 解析完成",
            "completed",
            f"{len(diff_files)} 个文件，{len(chunks)} 个分析块",
        )

        if with_context and not changed_only:
            progress.emit("context", "检索相关上下文", "running")
        context = retrieve_context(
            github,
            ref,
            pr,
            chunks,
            enabled=with_context and not changed_only,
        )
        limitations.extend(context.limitations)
        progress.emit(
            "context",
            "上下文检索完成" if with_context and not changed_only else "上下文检索已跳过",
            "completed" if with_context and not changed_only else "skipped",
        )

        progress.emit("rules", "运行规则引擎", "running")
        rule_findings = run_rules(files, diff_files, config)
        progress.emit("rules", "规则引擎扫描完成", "completed", f"{len(rule_findings)} 条规则 finding")

        fast_model, strong_model = select_models(config, model_profile)
        openai_api_key = resolve_openai_api_key(config)
        openai_base_url = resolve_openai_base_url(config)
        openai_api_mode = resolve_openai_api_mode(config)
        max_llm_chunks = (
            llm_max_chunks
            if llm_max_chunks is not None
            else config.review.max_llm_chunks
        )
        llm_chunks, chunk_debug, chunk_limitations = prioritize_chunks(
            chunks,
            max_chunks=max_llm_chunks,
        )
        limitations.extend(chunk_limitations)
        pr_summary = _pr_summary(pr, files, commits)
        progress.emit(
            "llm",
            "LLM 分块分析" if not no_llm else "LLM 分析已跳过",
            "running" if not no_llm else "skipped",
            f"{len(llm_chunks)} 个 chunk",
        )
        llm_findings, llm_limitations = analyze_chunks(
            llm_chunks,
            pr_summary=pr_summary,
            context=context,
            comments_summary=comment_context.as_prompt_text(),
            model=fast_model,
            comment_context=comment_context,
            api_key=openai_api_key,
            base_url=openai_base_url,
            api_mode=openai_api_mode,
            timeout_seconds=config.openai.timeout_seconds,
            max_chunks=None,
            enabled=not no_llm,
        )
        limitations.extend(llm_limitations)
        if not no_llm:
            progress.emit("llm", "LLM 分析完成", "completed", f"{len(llm_findings)} 条 LLM finding")

        progress.emit(
            "verification",
            "复核高风险 finding" if not no_llm else "高风险复核已跳过",
            "running" if not no_llm else "skipped",
        )
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
        if not no_llm:
            progress.emit("verification", "高风险复核完成", "completed", f"{len(verified_findings)} 条 finding")

        evidence_findings, evidence_limitations = verify_finding_evidence(
            verified_findings,
            diff_files=diff_files,
            context=context,
        )
        limitations.extend(evidence_limitations)

        progress.emit("aggregation", "聚合 Review 报告", "running")
        report = aggregate_report(
            pr=pr,
            files=files,
            commits=commits,
            comments=issue_comments + review_comments + pull_reviews,
            findings=evidence_findings,
            limitations=limitations,
            comment_context=comment_context,
            chunk_debug=chunk_debug if debug_chunks else [],
        )
        progress.emit("aggregation", "Review 报告聚合完成", "completed")

        if post_comment or post_inline_comments:
            progress.emit("writeback", "写回 GitHub 评论", "running")
        else:
            progress.emit("writeback", "GitHub 写回已跳过", "skipped")
        if post_comment:
            rendered = render_json(report) if output_format == "json" else render_markdown(report)
            github.create_issue_comment(ref, rendered)
        if post_inline_comments:
            comments, inline_limitations = build_inline_review_comments(report.findings, diff_files)
            report.limitations.extend(inline_limitations)
            if comments:
                github.create_pull_review(
                    ref,
                    body="AI PR Review inline comments",
                    comments=comments,
                )
        if post_comment or post_inline_comments:
            progress.emit("writeback", "GitHub 评论写回完成", "completed")
        return report
    except Exception as exc:
        progress.emit("failed", "Review 执行失败", "failed", str(exc))
        raise
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
        "--post-inline-comments",
        action="store_true",
        help="Post high-confidence blocking findings as GitHub inline review comments",
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
    parser.add_argument(
        "--llm-max-chunks",
        type=int,
        default=None,
        help="Maximum number of diff chunks to send to the LLM",
    )
    parser.add_argument(
        "--debug-chunks",
        action="store_true",
        help="Include chunk ranking and selection details in the report",
    )
    return parser


def _build_doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-pr-review doctor",
        description="Check local configuration and run a minimal LLM smoke test.",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "json"],
        default="markdown",
        help="Doctor output format",
    )
    parser.add_argument(
        "--model",
        dest="model_profile",
        choices=["fast", "balanced", "accurate"],
        default="balanced",
        help="Model profile for the smoke test",
    )
    parser.add_argument(
        "--no-smoke",
        action="store_true",
        help="Skip the LLM smoke test and only inspect local configuration",
    )
    return parser


def _build_eval_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-pr-review eval",
        description="Run deterministic local review-quality fixtures without network calls.",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "json"],
        default="markdown",
        help="Evaluation output format",
    )
    parser.add_argument(
        "--fixture",
        dest="fixture_id",
        default="all",
        help="Fixture id to run, or all",
    )
    return parser


def _build_web_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-pr-review web",
        description="Start the local Vue web UI and review runner API.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for the local web server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the local web server",
    )
    parser.add_argument(
        "--frontend-dir",
        default=None,
        help="Directory containing the built frontend assets",
    )
    return parser


def _pr_summary(pr: dict, files: list[dict], commits: list[dict]) -> str:
    title = str(pr.get("title") or "未命名 PR")
    body = str(pr.get("body") or "").strip()
    file_count = len(files)
    commit_count = len(commits)
    return f"{title}\n文件数：{file_count}\ncommit 数：{commit_count}\n描述：{body[:500] or '无'}"
