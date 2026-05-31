# AI PR Review Upgrade Roadmap

## Current Baseline

The project currently provides:

- Python CLI for GitHub PR review.
- Local Python web backend serving Vue assets and API endpoints.
- GitHub owner/repository/PR browser.
- Review runner with Markdown/JSON output.
- Markdown report rendering in the browser.
- GitHub summary comment and guarded inline review comments.
- Process-local and persisted review history under `.ai-pr-review/runs/`.
- CLI-to-Web review progress events with a report-page timeline.
- Local history management with filtering, deletion, clearing, and Markdown/JSON export.

The backend is local-first. It reads credentials from environment variables or `.ai-pr-review.local.yml`; secrets are not sent to the browser.

## Upgrade Priorities

### 1. Structured Report UI

Problem: the report page renders Markdown but does not expose the report as inspectable product UI.

Target:

- Parse JSON reports when available.
- Show risk overview cards.
- Show merge recommendation.
- Show findings grouped by severity and file.
- Show evidence, confidence, blocking flag, and suggestion per finding.
- Keep raw Markdown/JSON tabs for auditability.

Reason:

This improves review speed and makes the tool feel like a product instead of a terminal wrapper.

### 2. Inline Comment Preview

Problem: `--post-inline-comments` can write to GitHub, but the user cannot preview the exact comments first.

Target:

- Add backend preview endpoint for inline comments.
- Show which findings are commentable and which were skipped.
- Display path, line, severity, body, and limitations.
- Keep actual posting opt-in only.

Reason:

Inline comments are high impact. Preview reduces accidental noise and builds trust.

### 3. Doctor Page Integration

Problem: the settings page only explains local config; it does not run `doctor`.

Target:

- Add `/api/doctor`.
- Show GitHub token configured status.
- Show OpenAI key/base URL/model/API mode.
- Support smoke test.
- Never display secret values.

Reason:

Most user setup issues are environment/config issues. A UI health check shortens debugging.

### 4. Review Progress Events

Problem: long runs show only coarse job status.

Target:

- Track stages: GitHub fetch, diff parse, rules, LLM, verification, aggregation, writeback.
- Show stage timeline in the report page.

Reason:

The user needs to know whether work is slow, blocked on GitHub, or blocked on the model.

### 5. History Management

Problem: history is persisted but not manageable.

Target:

- Delete one run.
- Clear all history.
- Search/filter by PR URL, status, repository, or date.
- Export Markdown/JSON.

Reason:

Persistent local data needs management once the tool is used repeatedly.

### 6. Review Quality Evaluation Set

Problem: quality improvements are currently manual and PR-by-PR.

Target:

- Store fixture diffs and expected findings.
- Add regression tests for high-quality, low-quality, harmful, and clean PRs.
- Track false positives and false negatives.

Reason:

This turns prompt/rule/model changes into measurable engineering work.

## Recommended Next Slice

Implement:

1. Review quality evaluation fixtures.
2. Regression scoring for prompt/rule/model changes.

Scope constraints:

- Do not add a database.
- Keep fixture tests deterministic and network-free.
- Cover high-quality, low-quality, harmful, and clean PR examples.
- Track expected findings without requiring exact model wording.
- Keep all secrets backend-only.

Expected commits:

```text
test: add review quality fixture set
feat: add review quality regression runner
```
