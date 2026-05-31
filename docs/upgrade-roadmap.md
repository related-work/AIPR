# AI PR Review Upgrade Roadmap

## Current Baseline

The project currently provides:

- Python CLI for GitHub PR review.
- Local Python web backend serving Vue assets and API endpoints.
- GitHub owner/repository/PR browser.
- Review runner with Markdown/JSON output.
- Structured report UI for JSON output, including risk cards, merge recommendation, severity grouping,
  evidence, confidence, blocking flag, suggestions, and raw Markdown/JSON tabs.
- GitHub summary comment and guarded inline review comments.
- Inline comment preview before writing comments back to GitHub.
- Process-local and persisted review history under `.ai-pr-review/runs/`.
- CLI-to-Web review progress events with a report-page timeline.
- Local history management with filtering, deletion, clearing, and Markdown/JSON export.
- Settings doctor page for local GitHub/OpenAI configuration checks without exposing secrets.
- Deterministic `ai-pr-review eval` fixtures for high-quality, low-quality, harmful, and clean PR examples.
- Web quality evaluation view backed by the same deterministic local fixtures.
- Local quality evaluation snapshots and baseline comparison.
- Large PR and batch PR handling design in `docs/large-and-batch-pr-handling.md`.
- Large PR budgets for files, chunks, LLM chunks, context files, patch lines, and report-level
  `analysisCoverage`.
- Large PR per-file coverage transparency with analyzed/rule-only/skipped status and high-risk unreviewed
  file highlighting.
- Process-local Batch Review overview for selected repository PRs, with sequential per-PR jobs and
  independent report links.

The backend is local-first. It reads credentials from environment variables or `.ai-pr-review.local.yml`; secrets are not sent to the browser.

## Upgrade Status

## Completed Upgrade Slices

The following slices from the original roadmap are already implemented:

- Structured Report UI.
- Inline Comment Preview.
- Doctor Page Integration.
- Review Progress Events.
- History Management.
- Review Quality Evaluation Set.
- Large PR Analysis Coverage.
- Large PR Skipped-File Transparency.
- Batch PR Review Overview.

CI quality gates are intentionally not the next default slice. The project is still a local-first review
assistant, and a CI gate would duplicate existing test/eval commands without improving the day-to-day review
experience yet. It can be revisited after the evaluation set is larger and has real-world baselines.

## Open Upgrade Priorities

### 1. Batch PR History Management

Problem: batch runs are process-local and visible while the Web server is running, but not yet persisted as
their own batch history.

Target:

- Persist batch run summaries under `.ai-pr-review/batches/`.
- Reopen a batch run after Web restart.
- Retry only failed batch items.
- Export batch overview as Markdown/JSON.

Reason:

Per-PR reports are already persisted through review history, but maintainers also need the batch-level triage
record.

Reference: `docs/large-and-batch-pr-handling.md`.

### 2. Finding Triage Workspace

Problem: the report page can show structured findings, but it does not yet support reviewer workflow states.

Target:

- Let users mark findings as accepted, false positive, ignored, or fixed locally.
- Filter findings by severity, blocking flag, source, file, and confidence.
- Add one-click copy for a single finding as a GitHub-ready comment.
- Persist triage state under `.ai-pr-review/runs/` without writing to GitHub.

Reason:

This turns the report from a static output into a reviewer workbench, while keeping writeback opt-in.

### 3. Context Transparency

Problem: users cannot easily see why the tool reached a conclusion or whether enough code context was available.

Target:

- Show analyzed chunks, skipped files, generated/lock/doc classifications, and context files used.
- Show LLM chunk limits, truncation reasons, and rules that fired.
- Add a compact "analysis limitations" panel per run.

Reason:

Trust depends on knowing what evidence the tool actually saw, especially for large PRs.

### 4. Prompt And Rule Calibration

Problem: quality evaluation currently covers deterministic rules well, but not enough LLM/verifier behavior.

Target:

- Add fixtures that exercise LLM-only reasoning, verifier rejection, and comment-context handling.
- Track expected categories and severities without requiring exact wording.
- Compare current output against saved quality snapshots.
- Keep tests network-free by using fake LLM outputs.

Reason:

This improves accuracy without forcing CI adoption or depending on live model calls.

### 5. Review Run Comparison

Problem: users cannot compare two runs of the same PR after changing config, prompt, model, or context options.

Target:

- Compare findings added/removed/changed between two history runs.
- Compare merge recommendation, risk counts, model settings, and limitations.
- Highlight whether an upgrade reduced noise or missed important findings.

Reason:

This makes iterative prompt/rule tuning measurable on real PRs.

### 6. Repository Review Profile

Problem: `.ai-pr-review.yml` supports team rules, but Web users still need to edit it manually.

Target:

- Add a Web editor for non-secret local/team review settings.
- Manage ignore paths, high-risk paths, required-test paths, and preferred model mode.
- Validate config before saving.
- Keep secrets in environment variables or `.ai-pr-review.local.yml` only.

Reason:

This makes the tool easier to tune per repository without weakening secret handling.

## Recommended Next Slice

Implement:

1. Batch PR history management.
2. Finding triage workspace.

Scope constraints:

- Do not add a database.
- Keep fixture tests deterministic and network-free.
- Do not write back to GitHub unless the user explicitly clicks or passes a writeback flag.
- Persist local-only state under `.ai-pr-review/runs/`.
- Keep all secrets backend-only.
- Preserve current single-PR workflow as the default path.

Expected commits:

```text
feat: persist batch review history
feat: add finding triage workspace
```
