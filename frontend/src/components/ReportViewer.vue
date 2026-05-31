<script setup>
import { FileText, RefreshCw } from "@lucide/vue";
import MarkdownIt from "markdown-it";
import { computed, ref } from "vue";

const props = defineProps({
  job: { type: Object, default: null },
  runError: { type: String, default: "" },
  outputText: { type: String, required: true }
});

const emit = defineEmits(["go-runner"]);

const viewMode = ref("rendered");
const preview = ref(null);
const previewError = ref("");
const loadingPreview = ref(false);
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
