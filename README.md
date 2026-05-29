# AI PR Review

AI PR Review is a Python CLI MVP for reviewing GitHub Pull Requests. It fetches PR metadata, changed files, commits, comments, raw diff, applies lightweight deterministic rules, optionally calls OpenAI for structured review findings, and prints a Markdown or JSON report.

## Install

```bash
conda activate aipr
pip install -e .
```

Required runtime dependencies are declared in `pyproject.toml`.

## Usage

```bash
ai-pr-review https://github.com/org/repo/pull/123
ai-pr-review https://github.com/org/repo/pull/123 --format json
ai-pr-review https://github.com/org/repo/pull/123 --fail-on high
ai-pr-review https://github.com/org/repo/pull/123 --with-context
ai-pr-review https://github.com/org/repo/pull/123 --post-comment
```

Default behavior prints a report to the terminal and does not write back to GitHub. `--post-comment` is required to create a PR comment.

## Environment

```bash
export GITHUB_TOKEN=ghp_xxx
export OPENAI_API_KEY=sk_xxx
export OPENAI_FAST_MODEL=gpt-5.4-mini
export OPENAI_STRONG_MODEL=gpt-5.5
```

`GITHUB_TOKEN` is optional for public repositories, but unauthenticated requests have stricter rate limits. If `OPENAI_API_KEY` is missing, the CLI still runs and returns a rules-only report with an analysis limitation.

## Configuration

Optional `.ai-pr-review.yml`:

```yaml
models:
  fast: gpt-5.4-mini
  strong: gpt-5.5

review:
  fail_on: high
  ignore_paths:
    - "dist/**"
    - "generated/**"
  high_risk_paths:
    - "src/auth/**"
    - "src/payment/**"
    - "migrations/**"

rules:
  require_tests_for:
    - "src/payment/**"
    - "src/api/**"
```

## Development

```bash
conda activate aipr
python -m pytest -q
```
