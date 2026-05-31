<script setup>
import { computed, onBeforeUnmount, reactive, ref } from "vue";
import { Activity, FileText, History, ListChecks, Play, SearchCode, Settings2, ShieldCheck } from "@lucide/vue";

import AppShell from "./components/AppShell.vue";
import BatchReviewPanel from "./components/BatchReviewPanel.vue";
import CommandModal from "./components/CommandModal.vue";
import HelpPanel from "./components/HelpPanel.vue";
import HistoryPanel from "./components/HistoryPanel.vue";
import QualityEvalPanel from "./components/QualityEvalPanel.vue";
import RepoBrowser from "./components/RepoBrowser.vue";
import ReportViewer from "./components/ReportViewer.vue";
import ReviewRunner from "./components/ReviewRunner.vue";
import SettingsPanel from "./components/SettingsPanel.vue";
import WatcherPanel from "./components/WatcherPanel.vue";

const activeView = ref("browse");

const form = reactive({
  prUrl: "https://github.com/oldsheeppp/aiprtest/pull/4",
  format: "markdown",
  model: "balanced",
  failOn: "",
  postComment: false,
  postInlineComments: false,
  changedOnly: true,
  withContext: false,
  noLlm: false,
  llmMaxChunks: 2,
  maxFiles: 80,
  maxChunks: 40,
  maxContextFiles: 20,
  maxPatchLinesPerChunk: 400,
  debugChunks: true
});

const explorer = reactive({
  owner: "oldsheeppp",
  repo: "",
  pullUrl: "",
  state: "open"
});

const repos = ref([]);
const pulls = ref([]);
const repoFilter = ref("");
const browseError = ref("");
const loadingRepos = ref(false);
const loadingPulls = ref(false);
const commandMode = ref("module");
const showCommand = ref(false);
const copied = ref(false);
const job = ref(null);
const runError = ref("");
const batchJob = ref(null);
const batchError = ref("");
const batchPollingTimer = ref(null);
const reportCollection = ref({ title: "", jobs: [] });
const selectedBatchPullUrls = ref([]);
const watchers = ref([]);
const watcherError = ref("");
const loadingWatchers = ref(false);
const creatingWatcher = ref(false);
const watcherPollingTimer = ref(null);
const historyJobs = ref([]);
const historyError = ref("");
const loadingHistory = ref(false);
const pollingTimer = ref(null);
const qualityEvaluation = ref(null);
const qualityError = ref("");
const loadingQuality = ref(false);
const qualityFixture = ref("all");
const qualitySnapshots = ref([]);
const qualitySnapshotError = ref("");
const loadingQualitySnapshots = ref(false);
const savingQualitySnapshot = ref(false);
const qualitySnapshotLabel = ref("");
const qualityCompareBase = ref("");
const qualityCompareTarget = ref("");
const qualityComparison = ref(null);
const qualityComparisonError = ref("");
const watcherForm = reactive({
  intervalSeconds: 300,
  includeDrafts: false,
  model: "fast",
  changedOnly: true,
  withContext: false,
  noLlm: false,
  llmMaxChunks: 2,
  maxFiles: 80,
  maxChunks: 40,
  maxContextFiles: 20,
  maxPatchLinesPerChunk: 400
});
const historyFilters = reactive({
  query: "",
  status: "",
  repo: "",
  from: "",
  to: ""
});

const navItems = [
  { id: "browse", label: "PR 浏览", icon: SearchCode },
  { id: "review", label: "Review 运行", icon: Play },
  { id: "batch", label: "批量 Review", icon: ListChecks },
  { id: "watch", label: "PR 监控", icon: Activity },
  { id: "report", label: "报告结果", icon: FileText },
  { id: "history", label: "历史记录", icon: History },
  { id: "quality", label: "质量评测", icon: Activity },
  { id: "settings", label: "本地配置", icon: ShieldCheck },
  { id: "help", label: "帮助", icon: Settings2 }
];

const templates = [
  {
    name: "快速规则检查",
    description: "不调用模型，适合先扫明显安全和测试风险。",
    values: {
      format: "markdown",
      model: "fast",
      failOn: "",
      changedOnly: true,
      withContext: false,
      noLlm: true,
      llmMaxChunks: 2,
      maxFiles: 80,
      maxChunks: 40,
      maxContextFiles: 20,
      maxPatchLinesPerChunk: 400,
      debugChunks: true,
      postComment: false,
      postInlineComments: false
    }
  },
  {
    name: "日常 Review",
    description: "只看 diff，选择高风险 chunk 调模型。",
    values: {
      format: "markdown",
      model: "balanced",
      failOn: "",
      changedOnly: true,
      withContext: false,
      noLlm: false,
      llmMaxChunks: 2,
      maxFiles: 80,
      maxChunks: 40,
      maxContextFiles: 20,
      maxPatchLinesPerChunk: 400,
      debugChunks: true,
      postComment: false,
      postInlineComments: false
    }
  },
  {
    name: "完整上下文",
    description: "拉取相关文件上下文，适合复杂业务 PR。",
    values: {
      format: "markdown",
      model: "accurate",
      failOn: "",
      changedOnly: false,
      withContext: true,
      noLlm: false,
      llmMaxChunks: 6,
      maxFiles: 120,
      maxChunks: 80,
      maxContextFiles: 30,
      maxPatchLinesPerChunk: 400,
      debugChunks: true,
      postComment: false,
      postInlineComments: false
    }
  },
  {
    name: "CI 阻塞检查",
    description: "输出 JSON，遇到 high 及以上阻塞问题返回非零。",
    values: {
      format: "json",
      model: "balanced",
      failOn: "high",
      changedOnly: true,
      withContext: false,
      noLlm: false,
      llmMaxChunks: 2,
      maxFiles: 80,
      maxChunks: 40,
      maxContextFiles: 20,
      maxPatchLinesPerChunk: 400,
      debugChunks: false,
      postComment: false,
      postInlineComments: false
    }
  }
];

const optionDocs = [
  { title: "--format", body: "markdown 给人读，json 给 CI 或其他程序解析。" },
  { title: "--post-comment", body: "显式打开后才会写 GitHub PR 评论，需要 token 有评论权限。" },
  { title: "--post-inline-comments", body: "把 high/critical 且高置信的阻塞问题写成 GitHub 行内 review comment。" },
  { title: "--fail-on", body: "CI 阈值。比如 high 表示 high 和 critical 阻塞问题会让命令失败。" },
  { title: "--model", body: "fast 更快更省，balanced 默认平衡，accurate 更适合复杂 PR。" },
  { title: "--changed-only", body: "只分析 PR diff。速度快、成本低，但上下文理解更弱。" },
  { title: "--with-context", body: "检索同名测试、相邻模块、配置文件等上下文。changed-only 开启时不会生效。" },
  { title: "--no-llm", body: "跳过模型，只运行规则引擎，适合快速检查明确风险。" },
  { title: "--llm-max-chunks", body: "限制送入模型的 diff chunk 数量。越大越全面，也越慢越贵。" },
  { title: "--max-files", body: "限制进入深度分析的高优先级文件数，大 PR 用它控制范围。" },
  { title: "--max-chunks", body: "限制进入分析候选集的高优先级 chunk 数量。" },
  { title: "--max-context-files", body: "限制上下文检索文件数，避免复杂 PR 拉取过多无关文件。" },
  { title: "--max-patch-lines-per-chunk", body: "单个 chunk 的目标 patch 行数预算，报告会记录该预算。" },
  { title: "--debug-chunks", body: "在报告中展示 chunk 排序和选择原因，方便调试分析覆盖。" }
];

const isRunning = computed(() => ["queued", "running"].includes(job.value?.status));
const isBatchRunning = computed(() => ["queued", "running"].includes(batchJob.value?.status));
const isWatcherRunning = computed(() => watchers.value.some((watcher) => watcher.status === "running"));
const isBrowsing = computed(() => loadingRepos.value || loadingPulls.value);
const selectedRepo = computed(() => repos.value.find((repo) => repo.name === explorer.repo));
const selectedPull = computed(() => pulls.value.find((pull) => pull.url === explorer.pullUrl));
const selectedBatchPulls = computed(() => pulls.value.filter((pull) => selectedBatchPullUrls.value.includes(pull.url)));
const showPrContext = computed(() => ["review", "report"].includes(activeView.value));
const selectedPrLabel = computed(() => {
  if (selectedPull.value) {
    return `#${selectedPull.value.number} ${selectedPull.value.title}`;
  }
  return form.prUrl || "尚未选择 PR";
});
const filteredRepos = computed(() => {
  const keyword = repoFilter.value.trim().toLowerCase();
  if (!keyword) {
    return repos.value;
  }
  return repos.value.filter((repo) => repo.fullName.toLowerCase().includes(keyword));
});
const urlError = computed(() => {
  if (!form.prUrl.trim()) {
    return "请输入 GitHub PR URL";
  }
  return /^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+\/?$/.test(form.prUrl.trim())
    ? ""
    : "URL 格式应类似 https://github.com/org/repo/pull/123";
});
const contextNotice = computed(() =>
  form.changedOnly && form.withContext ? "changed-only 开启时，上下文检索不会生效。" : ""
);
const cliArgs = computed(() => {
  const args = [form.prUrl.trim(), "--format", form.format, "--model", form.model];
  if (form.postComment) args.push("--post-comment");
  if (form.postInlineComments) args.push("--post-inline-comments");
  if (form.failOn) args.push("--fail-on", form.failOn);
  if (form.changedOnly) args.push("--changed-only");
  if (form.withContext) args.push("--with-context");
  if (form.noLlm) args.push("--no-llm");
  if (form.llmMaxChunks) args.push("--llm-max-chunks", String(form.llmMaxChunks));
  if (form.maxFiles) args.push("--max-files", String(form.maxFiles));
  if (form.maxChunks) args.push("--max-chunks", String(form.maxChunks));
  if (form.maxContextFiles) args.push("--max-context-files", String(form.maxContextFiles));
  if (form.maxPatchLinesPerChunk) args.push("--max-patch-lines-per-chunk", String(form.maxPatchLinesPerChunk));
  if (form.debugChunks) args.push("--debug-chunks");
  return args;
});
const generatedCommand = computed(() => {
  const base = commandMode.value === "module" ? "PYTHONPATH=src python -m ai_pr_review" : "ai-pr-review";
  return `${base} ${cliArgs.value.map(shellQuote).join(" ")}`;
});
const outputText = computed(() => {
  if (!job.value) {
    return "暂无运行结果。";
  }
  if (job.value.stdout) {
    return job.value.stdout;
  }
  if (job.value.stderr) {
    return job.value.stderr;
  }
  return `任务状态：${job.value.status}`;
});

function shellQuote(value) {
  if (/^[A-Za-z0-9_./:=@+-]+$/.test(value)) {
    return value;
  }
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function applyTemplate(template) {
  Object.assign(form, template.values);
}

async function copyCommand() {
  await navigator.clipboard.writeText(generatedCommand.value);
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 1400);
}

async function loadRepositories() {
  if (!explorer.owner.trim() || loadingRepos.value) {
    return;
  }
  browseError.value = "";
  repos.value = [];
  pulls.value = [];
  selectedBatchPullUrls.value = [];
  explorer.repo = "";
  explorer.pullUrl = "";
  loadingRepos.value = true;
  try {
    const response = await fetch(`/api/github/repos?owner=${encodeURIComponent(explorer.owner.trim())}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取仓库失败");
    }
    repos.value = payload.repos || [];
    const firstRepo = repos.value.find((repo) => !repo.archived) || repos.value[0];
    if (firstRepo) {
      explorer.repo = firstRepo.name;
      await loadPullRequests();
    }
  } catch (error) {
    browseError.value = error.message;
  } finally {
    loadingRepos.value = false;
  }
}

async function loadPullRequests() {
  if (!explorer.owner.trim() || !explorer.repo || loadingPulls.value) {
    return;
  }
  browseError.value = "";
  pulls.value = [];
  selectedBatchPullUrls.value = [];
  explorer.pullUrl = "";
  loadingPulls.value = true;
  try {
    const url = `/api/github/repos/${encodeURIComponent(explorer.owner.trim())}/${encodeURIComponent(
      explorer.repo
    )}/pulls?state=${encodeURIComponent(explorer.state)}`;
    const response = await fetch(url);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取 PR 失败");
    }
    pulls.value = payload.pulls || [];
    if (pulls.value[0]) {
      explorer.pullUrl = pulls.value[0].url;
      applySelectedPull();
    }
  } catch (error) {
    browseError.value = error.message;
  } finally {
    loadingPulls.value = false;
  }
}

function applySelectedPull() {
  if (explorer.pullUrl) {
    form.prUrl = explorer.pullUrl;
  }
}

function proceedToReview() {
  applySelectedPull();
  activeView.value = "review";
}

function proceedToBatch() {
  activeView.value = "batch";
}

function requestPayload() {
  return {
    prUrl: form.prUrl.trim(),
    format: form.format,
    model: form.model,
    failOn: form.failOn || null,
    postComment: form.postComment,
    postInlineComments: form.postInlineComments,
    changedOnly: form.changedOnly,
    withContext: form.withContext,
    noLlm: form.noLlm,
    llmMaxChunks: form.llmMaxChunks || null,
    maxFiles: form.maxFiles || null,
    maxChunks: form.maxChunks || null,
    maxContextFiles: form.maxContextFiles || null,
    maxPatchLinesPerChunk: form.maxPatchLinesPerChunk || null,
    debugChunks: form.debugChunks
  };
}

function applyRequest(request) {
  form.prUrl = request.prUrl || form.prUrl;
  form.format = request.format || form.format;
  form.model = request.model || form.model;
  form.failOn = request.failOn || "";
  form.postComment = Boolean(request.postComment);
  form.postInlineComments = Boolean(request.postInlineComments);
  form.changedOnly = Boolean(request.changedOnly);
  form.withContext = Boolean(request.withContext);
  form.noLlm = Boolean(request.noLlm);
  form.llmMaxChunks = request.llmMaxChunks || form.llmMaxChunks;
  form.maxFiles = request.maxFiles || form.maxFiles;
  form.maxChunks = request.maxChunks || form.maxChunks;
  form.maxContextFiles = request.maxContextFiles || form.maxContextFiles;
  form.maxPatchLinesPerChunk = request.maxPatchLinesPerChunk || form.maxPatchLinesPerChunk;
  form.debugChunks = Boolean(request.debugChunks);
}

async function runReview() {
  if (urlError.value || isRunning.value) {
    return;
  }
  runError.value = "";
  reportCollection.value = { title: "", jobs: [] };
  job.value = null;
  activeView.value = "report";
  try {
    const response = await fetch("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload())
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "启动 Review 失败");
    }
    job.value = payload;
    pollJob(payload.id);
  } catch (error) {
    runError.value = error.message;
  }
}

function toggleBatchPull(url) {
  if (selectedBatchPullUrls.value.includes(url)) {
    selectedBatchPullUrls.value = selectedBatchPullUrls.value.filter((item) => item !== url);
    return;
  }
  selectedBatchPullUrls.value = [...selectedBatchPullUrls.value, url];
}

function selectAllBatchPulls() {
  selectedBatchPullUrls.value = pulls.value.map((pull) => pull.url);
}

function clearBatchSelection() {
  selectedBatchPullUrls.value = [];
}

async function runBatchReview() {
  if (isBatchRunning.value) {
    return;
  }
  if (!selectedBatchPulls.value.length) {
    batchError.value = "请先选择至少一个 PR";
    return;
  }
  batchError.value = "";
  reportCollection.value = { title: "", jobs: [] };
  batchJob.value = null;
  const requests = selectedBatchPulls.value.map((pull) => ({
    ...requestPayload(),
    prUrl: pull.url,
    format: "json",
    postComment: false,
    postInlineComments: false
  }));
  try {
    const response = await fetch("/api/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requests })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "启动批量 Review 失败");
    }
    batchJob.value = payload;
    pollBatch(payload.id);
  } catch (error) {
    batchError.value = error.message;
  }
}

function pollBatch(batchId) {
  window.clearInterval(batchPollingTimer.value);
  batchPollingTimer.value = window.setInterval(async () => {
    try {
      const response = await fetch(`/api/batches/${batchId}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "获取批量任务状态失败");
      }
      batchJob.value = payload;
      if (!["queued", "running"].includes(payload.status)) {
        window.clearInterval(batchPollingTimer.value);
        loadHistory();
      }
    } catch (error) {
      batchError.value = error.message;
      window.clearInterval(batchPollingTimer.value);
    }
  }, 900);
}

async function openBatchReport(item) {
  if (!item.jobId) {
    return;
  }
  await openBatchReports(item.jobId);
}

async function openBatchReports(selectedJobId = null) {
  const items = (batchJob.value?.items || []).filter((item) => item.jobId);
  if (!items.length) {
    batchError.value = "当前批量任务还没有可打开的报告";
    return;
  }
  batchError.value = "";
  runError.value = "";
  try {
    const jobs = await Promise.all(items.map(async (item) => {
      const response = await fetch(`/api/reviews/${item.jobId}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "读取批量报告失败");
      }
      return { ...payload, batchItem: item };
    }));
    reportCollection.value = {
      title: `批量报告 · ${jobs.length} 个 PR`,
      jobs
    };
    job.value = jobs.find((item) => item.id === selectedJobId) || jobs[0];
    activeView.value = "report";
  } catch (error) {
    batchError.value = error.message;
  }
}

function selectReportFromCollection(jobId) {
  const selected = reportCollection.value.jobs.find((item) => item.id === jobId);
  if (selected) {
    job.value = selected;
  }
}

function watcherPayload() {
  return {
    owner: explorer.owner.trim(),
    repo: explorer.repo.trim(),
    intervalSeconds: watcherForm.intervalSeconds,
    includeDrafts: watcherForm.includeDrafts,
    model: watcherForm.model,
    changedOnly: watcherForm.changedOnly,
    withContext: watcherForm.withContext,
    noLlm: watcherForm.noLlm,
    llmMaxChunks: watcherForm.llmMaxChunks,
    maxFiles: watcherForm.maxFiles,
    maxChunks: watcherForm.maxChunks,
    maxContextFiles: watcherForm.maxContextFiles,
    maxPatchLinesPerChunk: watcherForm.maxPatchLinesPerChunk
  };
}

async function loadWatchers() {
  watcherError.value = "";
  loadingWatchers.value = true;
  try {
    const response = await fetch("/api/watchers");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取监控状态失败");
    }
    watchers.value = payload.watchers || [];
  } catch (error) {
    watcherError.value = error.message;
  } finally {
    loadingWatchers.value = false;
  }
}

async function createWatcher() {
  if (creatingWatcher.value) {
    return;
  }
  if (!explorer.owner.trim() || !explorer.repo.trim()) {
    watcherError.value = "请输入 owner 和 repo";
    return;
  }
  watcherError.value = "";
  creatingWatcher.value = true;
  try {
    const response = await fetch("/api/watchers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(watcherPayload())
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "创建监控失败");
    }
    await loadWatchers();
  } catch (error) {
    watcherError.value = error.message;
  } finally {
    creatingWatcher.value = false;
  }
}

async function watcherAction(watcher, action) {
  watcherError.value = "";
  try {
    const response = await fetch(`/api/watchers/${encodeURIComponent(watcher.id)}/${action}`, {
      method: "POST"
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "监控操作失败");
    }
    await loadWatchers();
    loadHistory();
  } catch (error) {
    watcherError.value = error.message;
  }
}

async function deleteWatcher(watcher) {
  if (!window.confirm(`删除监控 ${watcher.request.owner}/${watcher.request.repo}？`)) {
    return;
  }
  watcherError.value = "";
  try {
    const response = await fetch(`/api/watchers/${encodeURIComponent(watcher.id)}`, {
      method: "DELETE"
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "删除监控失败");
    }
    await loadWatchers();
  } catch (error) {
    watcherError.value = error.message;
  }
}

async function openWatcherReport(review) {
  if (!review.jobId) {
    return;
  }
  watcherError.value = "";
  try {
    const response = await fetch(`/api/reviews/${review.jobId}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取监控报告失败");
    }
    reportCollection.value = { title: "", jobs: [] };
    job.value = payload;
    activeView.value = "report";
  } catch (error) {
    watcherError.value = error.message;
  }
}

function startWatcherPolling() {
  window.clearInterval(watcherPollingTimer.value);
  loadWatchers();
  watcherPollingTimer.value = window.setInterval(loadWatchers, 3000);
}

async function loadHistory() {
  historyError.value = "";
  loadingHistory.value = true;
  try {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(historyFilters)) {
      if (value) {
        params.set(key, value);
      }
    }
    const queryString = params.toString();
    const response = await fetch(`/api/reviews${queryString ? `?${queryString}` : ""}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取历史失败");
    }
    historyJobs.value = payload.jobs || [];
  } catch (error) {
    historyError.value = error.message;
  } finally {
    loadingHistory.value = false;
  }
}

async function deleteHistoryJob(historyJob) {
  if (!window.confirm(`删除这条 Review 历史？\n${historyJob.request.prUrl}`)) {
    return;
  }
  historyError.value = "";
  try {
    const response = await fetch(`/api/reviews/${encodeURIComponent(historyJob.id)}`, {
      method: "DELETE"
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "删除历史失败");
    }
    if (job.value?.id === historyJob.id) {
      job.value = null;
    }
    await loadHistory();
  } catch (error) {
    historyError.value = error.message;
  }
}

async function clearHistory() {
  if (!window.confirm("清空所有已完成的 Review 历史？运行中的任务会保留。")) {
    return;
  }
  historyError.value = "";
  try {
    const response = await fetch("/api/reviews", { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "清空历史失败");
    }
    await loadHistory();
  } catch (error) {
    historyError.value = error.message;
  }
}

function exportHistoryJob(historyJob, format) {
  const extension = format === "json" ? "json" : "md";
  const link = document.createElement("a");
  link.href = `/api/reviews/${encodeURIComponent(historyJob.id)}/export?format=${encodeURIComponent(format)}`;
  link.download = `ai-pr-review-${historyJob.id}.${extension}`;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function updateHistoryFilter({ key, value }) {
  if (Object.prototype.hasOwnProperty.call(historyFilters, key)) {
    historyFilters[key] = value;
  }
}

async function runQualityEvaluation() {
  if (loadingQuality.value) {
    return;
  }
  qualityError.value = "";
  loadingQuality.value = true;
  try {
    const response = await fetch(`/api/quality-evaluation?fixture=${encodeURIComponent(qualityFixture.value)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "运行质量评测失败");
    }
    qualityEvaluation.value = payload;
  } catch (error) {
    qualityError.value = error.message;
  } finally {
    loadingQuality.value = false;
  }
}

async function loadQualitySnapshots() {
  qualitySnapshotError.value = "";
  loadingQualitySnapshots.value = true;
  try {
    const response = await fetch("/api/quality-evaluation/snapshots");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取评测快照失败");
    }
    qualitySnapshots.value = payload.snapshots || [];
    if (!qualityCompareTarget.value && qualitySnapshots.value[0]) {
      qualityCompareTarget.value = qualitySnapshots.value[0].id;
    }
    if (!qualityCompareBase.value && qualitySnapshots.value[1]) {
      qualityCompareBase.value = qualitySnapshots.value[1].id;
    }
  } catch (error) {
    qualitySnapshotError.value = error.message;
  } finally {
    loadingQualitySnapshots.value = false;
  }
}

async function saveQualitySnapshot() {
  if (savingQualitySnapshot.value) {
    return;
  }
  qualitySnapshotError.value = "";
  savingQualitySnapshot.value = true;
  try {
    const response = await fetch("/api/quality-evaluation/snapshots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fixture: qualityFixture.value,
        label: qualitySnapshotLabel.value || null
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "保存评测快照失败");
    }
    qualitySnapshotLabel.value = "";
    await loadQualitySnapshots();
    qualityCompareTarget.value = payload.id;
  } catch (error) {
    qualitySnapshotError.value = error.message;
  } finally {
    savingQualitySnapshot.value = false;
  }
}

async function compareQualitySnapshots() {
  if (!qualityCompareBase.value || !qualityCompareTarget.value) {
    qualityComparisonError.value = "请选择两个快照";
    return;
  }
  qualityComparisonError.value = "";
  try {
    const response = await fetch(
      `/api/quality-evaluation/snapshots/compare?base=${encodeURIComponent(
        qualityCompareBase.value
      )}&target=${encodeURIComponent(qualityCompareTarget.value)}`
    );
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "比较评测快照失败");
    }
    qualityComparison.value = payload;
  } catch (error) {
    qualityComparisonError.value = error.message;
  }
}

function updateQualitySnapshotLabel(value) {
  qualitySnapshotLabel.value = value;
}

function updateQualityCompareBase(value) {
  qualityCompareBase.value = value;
}

function updateQualityCompareTarget(value) {
  qualityCompareTarget.value = value;
}

async function viewHistoryJob(historyJob) {
  historyError.value = "";
  try {
    const response = await fetch(`/api/reviews/${historyJob.id}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取历史报告失败");
    }
    reportCollection.value = { title: "", jobs: [] };
    job.value = payload;
    activeView.value = "report";
  } catch (error) {
    historyError.value = error.message;
  }
}

function rerunHistoryJob(historyJob) {
  reportCollection.value = { title: "", jobs: [] };
  applyRequest(historyJob.request);
  activeView.value = "review";
}

function navigate(view) {
  activeView.value = view;
  if (view !== "watch") {
    window.clearInterval(watcherPollingTimer.value);
  }
  if (view === "history") {
    loadHistory();
  }
  if (view === "quality" && !qualityEvaluation.value) {
    runQualityEvaluation();
  }
  if (view === "quality" && !qualitySnapshots.value.length) {
    loadQualitySnapshots();
  }
  if (view === "batch" && !pulls.value.length && explorer.repo) {
    loadPullRequests();
  }
  if (view === "watch") {
    startWatcherPolling();
  }
}

function pollJob(jobId) {
  window.clearInterval(pollingTimer.value);
  pollingTimer.value = window.setInterval(async () => {
    try {
      const response = await fetch(`/api/reviews/${jobId}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "获取任务状态失败");
      }
      job.value = payload;
      if (!["queued", "running"].includes(payload.status)) {
        window.clearInterval(pollingTimer.value);
        loadHistory();
      }
    } catch (error) {
      runError.value = error.message;
      window.clearInterval(pollingTimer.value);
    }
  }, 900);
}

onBeforeUnmount(() => {
  window.clearInterval(pollingTimer.value);
  window.clearInterval(batchPollingTimer.value);
  window.clearInterval(watcherPollingTimer.value);
});
</script>

<template>
  <AppShell
    :active-view="activeView"
    :is-running="isRunning || isBatchRunning || isWatcherRunning"
    :nav-items="navItems"
    :selected-pr-label="selectedPrLabel"
    :show-pr-context="showPrContext"
    @navigate="navigate"
    @open-command="showCommand = true"
  >
    <RepoBrowser
      v-if="activeView === 'browse'"
      v-model:repo-filter="repoFilter"
      :browse-error="browseError"
      :explorer="explorer"
      :filtered-repos="filteredRepos"
      :loading-pulls="loadingPulls"
      :loading-repos="loadingRepos"
      :pulls="pulls"
      :repos="repos"
      :selected-pull="selectedPull"
      :selected-repo="selectedRepo"
      :selected-urls="selectedBatchPullUrls"
      @apply-selected-pull="applySelectedPull"
      @clear-selection="clearBatchSelection"
      @load-pulls="loadPullRequests"
      @load-repositories="loadRepositories"
      @proceed-batch="proceedToBatch"
      @proceed-review="proceedToReview"
      @select-all="selectAllBatchPulls"
      @toggle-pull="toggleBatchPull"
    />

    <ReviewRunner
      v-else-if="activeView === 'review'"
      :context-notice="contextNotice"
      :form="form"
      :is-browsing="isBrowsing"
      :is-running="isRunning"
      :selected-pull="selectedPull"
      :templates="templates"
      :url-error="urlError"
      @apply-template="applyTemplate"
      @go-browse="activeView = 'browse'"
      @open-command="showCommand = true"
      @run="runReview"
    />

    <BatchReviewPanel
      v-else-if="activeView === 'batch'"
      :batch-error="batchError"
      :batch-job="batchJob"
      :is-running="isBatchRunning"
      :loading-pulls="loadingPulls"
      :pulls="pulls"
      :selected-repo="selectedRepo"
      :selected-urls="selectedBatchPullUrls"
      @clear-selection="clearBatchSelection"
      @go-browse="activeView = 'browse'"
      @open-batch-reports="openBatchReports"
      @open-report="openBatchReport"
      @run="runBatchReview"
      @select-all="selectAllBatchPulls"
      @toggle-pull="toggleBatchPull"
    />

    <WatcherPanel
      v-else-if="activeView === 'watch'"
      :creating="creatingWatcher"
      :error="watcherError"
      :explorer="explorer"
      :form="watcherForm"
      :loading="loadingWatchers"
      :watchers="watchers"
      @check="watcherAction($event, 'check')"
      @create="createWatcher"
      @delete="deleteWatcher"
      @go-browse="activeView = 'browse'"
      @open-report="openWatcherReport"
      @pause="watcherAction($event, 'pause')"
      @refresh="loadWatchers"
      @start="watcherAction($event, 'start')"
    />

    <ReportViewer
      v-else-if="activeView === 'report'"
      :job="job"
      :output-text="outputText"
      :related-reports="reportCollection.jobs"
      :report-collection-title="reportCollection.title"
      :run-error="runError"
      @go-batch="activeView = 'batch'"
      @go-runner="activeView = 'review'"
      @select-report="selectReportFromCollection"
    />

    <HistoryPanel
      v-else-if="activeView === 'history'"
      :history-filters="historyFilters"
      :history-error="historyError"
      :history-jobs="historyJobs"
      :loading-history="loadingHistory"
      @clear="clearHistory"
      @delete-job="deleteHistoryJob"
      @export-job="exportHistoryJob"
      @refresh="loadHistory"
      @rerun-job="rerunHistoryJob"
      @update-filter="updateHistoryFilter"
      @view-job="viewHistoryJob"
    />

    <QualityEvalPanel
      v-else-if="activeView === 'quality'"
      v-model:fixture="qualityFixture"
      :comparison="qualityComparison"
      :comparison-error="qualityComparisonError"
      :compare-base="qualityCompareBase"
      :compare-target="qualityCompareTarget"
      :evaluation="qualityEvaluation"
      :evaluation-error="qualityError"
      :loading-evaluation="loadingQuality"
      :loading-snapshots="loadingQualitySnapshots"
      :saving-snapshot="savingQualitySnapshot"
      :snapshot-error="qualitySnapshotError"
      :snapshot-label="qualitySnapshotLabel"
      :snapshots="qualitySnapshots"
      @compare-snapshots="compareQualitySnapshots"
      @refresh-snapshots="loadQualitySnapshots"
      @run="runQualityEvaluation"
      @save-snapshot="saveQualitySnapshot"
      @update:compare-base="updateQualityCompareBase"
      @update:compare-target="updateQualityCompareTarget"
      @update:snapshot-label="updateQualitySnapshotLabel"
    />

    <SettingsPanel
      v-else-if="activeView === 'settings'"
      @open-command="showCommand = true"
    />

    <HelpPanel
      v-else
      :option-docs="optionDocs"
      :templates="templates"
      @apply-template="applyTemplate"
      @go-runner="activeView = 'review'"
    />
  </AppShell>

  <CommandModal
    v-if="showCommand"
    :command-mode="commandMode"
    :copied="copied"
    :generated-command="generatedCommand"
    @close="showCommand = false"
    @copy="copyCommand"
    @update:command-mode="commandMode = $event"
  />
</template>
