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
ai-pr-review https://github.com/org/repo/pull/123 --llm-max-chunks 2
ai-pr-review https://github.com/org/repo/pull/123 --post-comment
ai-pr-review https://github.com/org/repo/pull/123 --post-inline-comments
```

Default behavior prints a report to the terminal and does not write back to GitHub. `--post-comment` is required to create a PR summary comment. `--post-inline-comments` creates GitHub inline review comments only for high/critical, blocking, high-confidence findings that can be mapped to newly added diff lines.

### Local Web Console

The project also includes a Vue command generator and local review runner.

```bash
cd frontend
npm install
npm run build
cd ..
PYTHONPATH=src python -m ai_pr_review web
```

Open `http://127.0.0.1:8765`.

The page supports two workflows:

- Generate a copyable CLI command from PR URL and options.
- Run the review through the local Python API and view the report in the browser.
- Enter a GitHub user or organization, load repositories, select a repository, and auto-fill an open PR.

The browser never receives `GITHUB_TOKEN`, `OPENAI_API_KEY`, or local config secrets. The local Python process reads credentials from environment variables or `.ai-pr-review.local.yml`, then runs the same CLI review path used by the terminal command.

GitHub browsing uses the same local GitHub token resolution as the CLI. Public repositories can be browsed without a token, but GitHub applies stricter anonymous rate limits.

Useful web server options:

```bash
PYTHONPATH=src python -m ai_pr_review web --host 127.0.0.1 --port 8765
PYTHONPATH=src python -m ai_pr_review web --frontend-dir frontend/dist
```

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

Speed controls:

```yaml
review:
  max_llm_chunks: 4
```

```bash
ai-pr-review PR_URL --no-llm
ai-pr-review PR_URL --llm-max-chunks 2
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
