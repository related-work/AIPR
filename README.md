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
ai-pr-review https://github.com/org/repo/pull/123 --no-llm
ai-pr-review https://github.com/org/repo/pull/123 --post-comment
```

Default behavior prints a report to the terminal and does not write back to GitHub. `--post-comment` is required to create a PR comment.

## Environment

```bash
export GITHUB_TOKEN=ghp_xxx
export OPENAI_API_KEY=sk_xxx
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_MODE=auto
export OPENAI_FAST_MODEL=gpt-5.4-mini
export OPENAI_STRONG_MODEL=gpt-5.5
```

`GITHUB_TOKEN` is optional for public repositories, but unauthenticated requests have stricter rate limits. If `OPENAI_API_KEY` is missing, the CLI still runs and returns a rules-only report with an analysis limitation. `OPENAI_MODEL` sets one model for both fast and strong analysis; `OPENAI_FAST_MODEL` and `OPENAI_STRONG_MODEL` override it when set. `OPENAI_API_MODE` can be `auto`, `responses`, or `chat`.

## Configuration

Optional committed team config `.ai-pr-review.yml`:

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

Local credentials can be stored in `.ai-pr-review.local.yml`, which is ignored by git:

```bash
cp .ai-pr-review.example.yml .ai-pr-review.local.yml
```

Then edit `.ai-pr-review.local.yml`:

```yaml
credentials:
  github_token: ghp_xxx

openai:
  api_key: sk_xxx
  model: gpt-5.4-mini
  base_url: https://api.openai.com/v1
  api_mode: auto
  timeout_seconds: 45
```

Credential priority is:

```text
environment variables > .ai-pr-review.local.yml > .ai-pr-review.yml
```

OpenAI model priority is:

```text
OPENAI_FAST_MODEL / OPENAI_STRONG_MODEL > OPENAI_MODEL > openai.model > models.fast / models.strong
```

OpenAI API mode:

```text
auto      Try Responses API first, then fallback to Chat Completions.
responses Use only Responses API with structured outputs.
chat      Use only Chat Completions, useful for OpenAI-compatible gateways.
```

For slow OpenAI-compatible gateways, prefer:

```yaml
openai:
  api_mode: chat
  timeout_seconds: 30
```

## Development

```bash
conda activate aipr
python -m pytest -q
```
