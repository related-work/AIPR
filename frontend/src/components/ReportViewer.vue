<script setup>
import { Code2, FileText, RefreshCw } from "@lucide/vue";
import MarkdownIt from "markdown-it";
import { computed, nextTick, ref, watch } from "vue";

const props = defineProps({
  job: { type: Object, default: null },
  runError: { type: String, default: "" },
  outputText: { type: String, required: true },
  relatedReports: { type: Array, default: () => [] },
  reportCollectionTitle: { type: String, default: "" }
});

const emit = defineEmits(["go-batch", "go-runner", "select-report"]);

const viewMode = ref("rendered");
const preview = ref(null);
const previewError = ref("");
const loadingPreview = ref(false);
const diffPreview = ref(null);
const diffError = ref("");
const loadingDiff = ref(false);
const expandedDiffFiles = ref(new Set());
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true
});

const looksLikeJson = computed(() => {
  const value = props.outputText.trim();
  return value.startsWith("{") || value.startsWith("[");
});
const renderedMarkdown = computed(() => {
  if (!props.outputText || looksLikeJson.value) {
    return "";
  }
  return markdown.render(props.outputText);
});
const formattedJson = computed(() => {
  if (!looksLikeJson.value) {
    return "";
  }
  try {
    return JSON.stringify(JSON.parse(props.outputText), null, 2);
  } catch {
    return props.outputText;
  }
});
const rawOutput = computed(() => (looksLikeJson.value ? formattedJson.value : props.outputText));
const parsedReport = computed(() => {
  if (!looksLikeJson.value) {
    return null;
  }
  try {
    const parsed = JSON.parse(props.outputText);
    return parsed && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
});
const findingsBySeverity = computed(() => {
  const groups = { critical: [], high: [], medium: [], low: [] };
  for (const finding of parsedReport.value?.findings || []) {
    if (groups[finding.severity]) {
      groups[finding.severity].push(finding);
    }
  }
  return groups;
});
const analysisCoverage = computed(() => parsedReport.value?.analysisCoverage || null);
const highRiskUnreviewedFiles = computed(() =>
  (analysisCoverage.value?.fileCoverage || []).filter((item) => item.highRiskUnreviewed)
);
const progressEvents = computed(() => props.job?.progress || []);
const diffFiles = computed(() => diffPreview.value?.files || []);

watch(
  () => props.job?.id,
  () => {
    preview.value = null;
    previewError.value = "";
    diffPreview.value = null;
    diffError.value = "";
    expandedDiffFiles.value = new Set();
    viewMode.value = "rendered";
  }
);

async function loadInlinePreview() {
  if (!props.job?.id || loadingPreview.value) {
    return;
  }
  previewError.value = "";
  loadingPreview.value = true;
  try {
    const response = await fetch(`/api/reviews/${props.job.id}/inline-preview`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取 inline 预览失败");
    }
    preview.value = payload;
  } catch (error) {
    previewError.value = error.message;
  } finally {
    loadingPreview.value = false;
  }
}

async function loadDiffPreview(force = false) {
  if (!props.job?.id || loadingDiff.value || (diffPreview.value && !force)) {
    return;
  }
  diffError.value = "";
  loadingDiff.value = true;
  try {
    const response = await fetch(`/api/reviews/${props.job.id}/diff`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取变更代码失败");
    }
    diffPreview.value = payload;
    if (!expandedDiffFiles.value.size) {
      const filesWithFindings = (payload.files || [])
        .filter((file) => file.hunks?.some((hunk) => hunk.lines?.some((line) => line.findings?.length)))
        .map((file) => file.path);
      const defaultExpanded = filesWithFindings.length ? filesWithFindings : (payload.files || []).slice(0, 1).map((file) => file.path);
      expandedDiffFiles.value = new Set(defaultExpanded);
    }
  } catch (error) {
    diffError.value = error.message;
  } finally {
    loadingDiff.value = false;
  }
}

function showDiffView() {
  viewMode.value = "diff";
  loadDiffPreview();
}

function isDiffFileExpanded(path) {
  return expandedDiffFiles.value.has(path);
}

function toggleDiffFile(path) {
  const next = new Set(expandedDiffFiles.value);
  if (next.has(path)) {
    next.delete(path);
  } else {
    next.add(path);
  }
  expandedDiffFiles.value = next;
}

function lineAnchor(path, line) {
  if (!path || !line) {
    return "";
  }
  return `diff-${encodeURIComponent(path).replace(/[^a-zA-Z0-9]/g, "-")}-${line}`;
}

async function openFinding(finding) {
  if (!finding?.path) {
    return;
  }
  viewMode.value = "diff";
  await loadDiffPreview();
  expandedDiffFiles.value = new Set([...expandedDiffFiles.value, finding.path]);
  await nextTick();
  const target = document.getElementById(lineAnchor(finding.path, finding.line));
  target?.scrollIntoView({ behavior: "smooth", block: "center" });
}
</script>

<template>
  <section class="view-stack report-view">
    <div class="page-title">
      <FileText aria-hidden="true" :size="22" />
      <div>
        <h2>报告结果</h2>
        <p>Review 输出会在这里独立展示。</p>
      </div>
    </div>

    <section class="panel report-panel">
      <div class="report-toolbar">
        <div class="run-status">
          <span :class="['status-dot', job?.status || 'idle']"></span>
          <span>{{ job?.status || "idle" }}</span>
          <span v-if="job?.exitCode !== null && job?.exitCode !== undefined">exit {{ job.exitCode }}</span>
        </div>
        <button class="ghost-button" type="button" @click="emit('go-runner')">返回运行配置</button>
      </div>

      <p v-if="runError" class="field-error">{{ runError }}</p>

      <section v-if="relatedReports.length" class="report-collection-panel">
        <div class="report-toolbar">
          <div>
            <h3>{{ reportCollectionTitle || "批量报告" }}</h3>
            <p>直接切换本次批量任务生成的报告，不需要回历史记录逐个打开。</p>
          </div>
          <button class="ghost-button" type="button" @click="emit('go-batch')">返回批量结果</button>
        </div>
        <div class="report-switch-list">
          <button
            v-for="report in relatedReports"
            :key="report.id"
            :class="{ active: report.id === job?.id }"
            type="button"
            @click="emit('select-report', report.id)"
          >
            <span :class="['status-dot', report.status]"></span>
            <strong>
              #{{ report.batchItem?.number || "-" }}
              {{ report.batchItem?.title || report.batchItem?.prUrl || report.request?.prUrl }}
            </strong>
            <small>
              {{ report.status }} · {{ report.batchItem?.mergeRecommendation || "等待结果" }}
              · blocking {{ report.batchItem?.blockingFindings ?? 0 }}
            </small>
          </button>
        </div>
      </section>

      <section v-if="progressEvents.length" class="progress-timeline" aria-label="Review 进度">
        <div class="progress-heading">
          <h3>运行进度</h3>
          <span>{{ progressEvents.length }} 个事件</span>
        </div>
        <ol>
          <li v-for="event in progressEvents" :key="`${event.stage}:${event.status}:${event.timestamp}:${event.label}`">
            <span :class="['progress-marker', event.status]"></span>
            <div>
              <strong>{{ event.label }}</strong>
              <small>{{ event.stage }} · {{ event.status }} · {{ event.timestamp }}</small>
              <p v-if="event.message">{{ event.message }}</p>
            </div>
          </li>
        </ol>
      </section>

      <div class="report-tabs" aria-label="报告展示方式">
        <button :class="{ active: viewMode === 'rendered' }" type="button" @click="viewMode = 'rendered'">
          {{ parsedReport ? "结构化报告" : "渲染报告" }}
        </button>
        <button :class="{ active: viewMode === 'raw' }" type="button" @click="viewMode = 'raw'">
          原始输出
        </button>
        <button :class="{ active: viewMode === 'json' }" type="button" @click="viewMode = 'json'">
          JSON
        </button>
        <button :class="{ active: viewMode === 'diff' }" type="button" @click="showDiffView">
          变更代码
        </button>
      </div>

      <section v-if="viewMode === 'rendered' && parsedReport" class="structured-report">
        <div class="risk-grid">
          <article v-for="key in ['critical', 'high', 'medium', 'low']" :key="key" class="risk-card">
            <span>{{ key }}</span>
            <strong>{{ parsedReport.riskOverview?.[key] ?? 0 }}</strong>
          </article>
          <article class="risk-card">
            <span>blocking</span>
            <strong>{{ parsedReport.riskOverview?.blocking ?? 0 }}</strong>
          </article>
          <article class="risk-card wide-risk">
            <span>merge</span>
            <strong>{{ parsedReport.mergeRecommendation }}</strong>
          </article>
        </div>

        <section v-if="analysisCoverage" class="coverage-panel">
          <div class="report-toolbar">
            <div>
              <h3>分析覆盖率</h3>
              <p>大 PR 会优先分析高风险 chunk，未深度分析的范围会在这里明确展示。</p>
            </div>
            <span :class="['coverage-badge', analysisCoverage.largePr ? 'warning' : 'ok']">
              {{ analysisCoverage.largePr ? "大 PR" : "常规 PR" }}
            </span>
          </div>
          <div class="coverage-grid">
            <article>
              <span>深度分析文件</span>
              <strong>{{ analysisCoverage.analyzedFiles }} / {{ analysisCoverage.changedFiles }}</strong>
            </article>
            <article>
              <span>LLM chunk</span>
              <strong>{{ analysisCoverage.llmAnalyzedChunks }} / {{ analysisCoverage.totalChunks }}</strong>
            </article>
            <article>
              <span>规则扫描文件</span>
              <strong>{{ analysisCoverage.rulesScannedFiles }}</strong>
            </article>
            <article>
              <span>覆盖率</span>
              <strong>{{ Number(analysisCoverage.coverageRatio || 0).toFixed(2) }}</strong>
            </article>
          </div>
          <div v-if="analysisCoverage.budgetLimits" class="coverage-budget">
            <code v-if="analysisCoverage.budgetLimits.maxFiles">max_files={{ analysisCoverage.budgetLimits.maxFiles }}</code>
            <code v-if="analysisCoverage.budgetLimits.maxChunks">max_chunks={{ analysisCoverage.budgetLimits.maxChunks }}</code>
            <code v-if="analysisCoverage.budgetLimits.maxLlmChunks">max_llm_chunks={{ analysisCoverage.budgetLimits.maxLlmChunks }}</code>
            <code v-if="analysisCoverage.budgetLimits.maxContextFiles">max_context_files={{ analysisCoverage.budgetLimits.maxContextFiles }}</code>
            <code v-if="analysisCoverage.budgetLimits.maxPatchLinesPerChunk">
              max_patch_lines_per_chunk={{ analysisCoverage.budgetLimits.maxPatchLinesPerChunk }}
            </code>
          </div>
          <div v-if="analysisCoverage.skippedReasons?.length" class="coverage-reasons">
            <span v-for="item in analysisCoverage.skippedReasons" :key="item.reason">
              {{ item.reason }}：{{ item.count }}
            </span>
          </div>
          <div v-if="highRiskUnreviewedFiles.length" class="coverage-file-section">
            <h4>高风险未深度分析文件</h4>
            <div class="coverage-file-list">
              <article v-for="item in highRiskUnreviewedFiles" :key="item.path" class="coverage-file-item warning">
                <strong>{{ item.path }}</strong>
                <span>{{ item.status }} · {{ item.reason }} · risk {{ item.riskScore }}</span>
                <small>{{ item.reasons?.join(", ") }}</small>
              </article>
            </div>
          </div>
          <details v-if="analysisCoverage.fileCoverage?.length" class="coverage-file-section">
            <summary>文件覆盖明细</summary>
            <div class="coverage-file-list">
              <article v-for="item in analysisCoverage.fileCoverage" :key="item.path" class="coverage-file-item">
                <strong>{{ item.path }}</strong>
                <span>{{ item.status }} · {{ item.reason }} · risk {{ item.riskScore }}</span>
                <small>{{ item.highRiskUnreviewed ? "高风险未深度分析" : item.reasons?.join(", ") }}</small>
              </article>
            </div>
          </details>
        </section>

        <section class="finding-section" v-for="severity in ['critical', 'high', 'medium', 'low']" :key="severity">
          <h3>{{ severity }}</h3>
          <div v-if="!findingsBySeverity[severity].length" class="empty-state compact-empty">无</div>
          <article v-for="finding in findingsBySeverity[severity]" :key="`${finding.path}:${finding.line}:${finding.problem}`" class="finding-card">
            <header>
              <strong>{{ finding.path }}{{ finding.line ? `:${finding.line}` : "" }}</strong>
              <span>{{ finding.category }} · 置信度 {{ Number(finding.confidence).toFixed(2) }} · {{ finding.blocking ? "阻塞" : "非阻塞" }}</span>
              <button class="inline-link-button" type="button" @click="openFinding(finding)">查看代码</button>
            </header>
            <p>{{ finding.problem }}</p>
            <div class="evidence-list">
              <code v-for="item in finding.evidence || []" :key="item">{{ item }}</code>
            </div>
            <p class="suggestion-line">{{ finding.suggestion }}</p>
          </article>
        </section>

        <section class="inline-preview-panel">
          <div class="report-toolbar">
            <div>
              <h3>Inline 评论预览</h3>
              <p>只预览可映射到 diff 新增行的高置信阻塞问题。</p>
            </div>
            <button class="ghost-button" type="button" :disabled="loadingPreview" @click="loadInlinePreview">
              <RefreshCw v-if="loadingPreview" aria-hidden="true" class="spin" :size="17" />
              <span>{{ loadingPreview ? "生成中" : "生成预览" }}</span>
            </button>
          </div>
          <p v-if="previewError" class="field-error">{{ previewError }}</p>
          <div v-if="preview" class="preview-summary">
            <span>可评论：{{ preview.commentableCount }}</span>
            <span>跳过：{{ preview.skippedCount }}</span>
          </div>
          <article v-for="comment in preview?.comments || []" :key="`${comment.path}:${comment.line}`" class="preview-comment">
            <strong>{{ comment.path }}:{{ comment.line }}</strong>
            <span>{{ comment.severity }} · {{ comment.category }} · {{ Number(comment.confidence).toFixed(2) }}</span>
            <pre>{{ comment.body }}</pre>
          </article>
          <ul v-if="preview?.limitations?.length" class="preview-limitations">
            <li v-for="item in preview.limitations" :key="item">{{ item }}</li>
          </ul>
        </section>
      </section>
      <section v-else-if="viewMode === 'diff'" class="diff-preview-panel">
        <div class="report-toolbar">
          <div>
            <h3>变更代码</h3>
            <p>按文件展示 PR diff，并在对应新增行标出 Review finding。</p>
          </div>
          <button class="ghost-button" type="button" :disabled="loadingDiff" @click="loadDiffPreview(true)">
            <RefreshCw v-if="loadingDiff" aria-hidden="true" class="spin" :size="17" />
            <Code2 v-else aria-hidden="true" :size="17" />
            <span>{{ loadingDiff ? "加载中" : "刷新 diff" }}</span>
          </button>
        </div>

        <p v-if="diffError" class="field-error">{{ diffError }}</p>
        <div v-if="diffPreview" class="diff-summary">
          <span>{{ diffPreview.fileCount }} 个文件</span>
          <span class="diff-add">+{{ diffPreview.totalAdditions }}</span>
          <span class="diff-remove">-{{ diffPreview.totalDeletions }}</span>
          <span>{{ diffPreview.findingsMapped }} 条 finding 已映射</span>
        </div>
        <div v-if="loadingDiff && !diffPreview" class="empty-state">正在加载变更代码</div>
        <div v-else-if="diffPreview && !diffFiles.length" class="empty-state">没有可展示的 diff</div>

        <div v-if="diffFiles.length" class="diff-file-list">
          <article v-for="file in diffFiles" :key="file.path" class="diff-file-card">
            <button class="diff-file-header" type="button" @click="toggleDiffFile(file.path)">
              <span>{{ isDiffFileExpanded(file.path) ? "▾" : "▸" }}</span>
              <strong>{{ file.path }}</strong>
              <small v-if="file.oldPath && file.oldPath !== file.path">{{ file.oldPath }} → {{ file.path }}</small>
              <em>{{ file.status }}</em>
              <code class="diff-add">+{{ file.additions }}</code>
              <code class="diff-remove">-{{ file.deletions }}</code>
            </button>

            <div v-if="isDiffFileExpanded(file.path)" class="diff-hunk-list">
              <section v-for="hunk in file.hunks" :key="`${file.path}:${hunk.oldStart}:${hunk.newStart}`" class="diff-hunk">
                <div class="diff-hunk-header">
                  @@ -{{ hunk.oldStart }},{{ hunk.oldLength }} +{{ hunk.newStart }},{{ hunk.newLength }} @@
                  <span v-if="hunk.sectionHeader">{{ hunk.sectionHeader }}</span>
                </div>
                <div class="diff-lines">
                  <div
                    v-for="(line, index) in hunk.lines"
                    :id="line.newLine ? lineAnchor(file.path, line.newLine) : null"
                    :key="`${file.path}:${hunk.newStart}:${index}`"
                    :class="['diff-line', line.kind, { 'has-finding': line.findings?.length }]"
                  >
                    <span class="line-no old">{{ line.oldLine ?? "" }}</span>
                    <span class="line-no new">{{ line.newLine ?? "" }}</span>
                    <code>{{ line.content }}</code>
                    <div v-if="line.findings?.length" class="diff-line-findings">
                      <span v-for="finding in line.findings" :key="`${finding.severity}:${finding.problem}`">
                        {{ finding.severity }} · {{ finding.category }} · {{ Number(finding.confidence).toFixed(2) }}
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </article>
        </div>
      </section>
      <article
        v-else-if="viewMode === 'rendered' && renderedMarkdown"
        class="markdown-report"
        v-html="renderedMarkdown"
      ></article>
      <pre v-else-if="viewMode === 'json'" class="result-output report-output">{{ formattedJson || rawOutput }}</pre>
      <pre v-else class="result-output report-output">{{ rawOutput }}</pre>
    </section>
  </section>
</template>
