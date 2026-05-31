<script setup>
import { computed, onBeforeUnmount, reactive, ref } from "vue";
import { FileText, History, Play, SearchCode, Settings2, ShieldCheck } from "@lucide/vue";

import AppShell from "./components/AppShell.vue";
import CommandModal from "./components/CommandModal.vue";
import HelpPanel from "./components/HelpPanel.vue";
import HistoryPanel from "./components/HistoryPanel.vue";
import RepoBrowser from "./components/RepoBrowser.vue";
import ReportViewer from "./components/ReportViewer.vue";
import ReviewRunner from "./components/ReviewRunner.vue";
import SettingsPanel from "./components/SettingsPanel.vue";

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
const historyJobs = ref([]);
const historyError = ref("");
const loadingHistory = ref(false);
const pollingTimer = ref(null);
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
  { id: "report", label: "报告结果", icon: FileText },
  { id: "history", label: "历史记录", icon: History },
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
  { title: "--debug-chunks", body: "在报告中展示 chunk 排序和选择原因，方便调试分析覆盖。" }
];

const isRunning = computed(() => ["queued", "running"].includes(job.value?.status));
const isBrowsing = computed(() => loadingRepos.value || loadingPulls.value);
const selectedRepo = computed(() => repos.value.find((repo) => repo.name === explorer.repo));
const selectedPull = computed(() => pulls.value.find((pull) => pull.url === explorer.pullUrl));
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
  form.debugChunks = Boolean(request.debugChunks);
}

async function runReview() {
  if (urlError.value || isRunning.value) {
    return;
  }
  runError.value = "";
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

async function viewHistoryJob(historyJob) {
  historyError.value = "";
  try {
    const response = await fetch(`/api/reviews/${historyJob.id}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "读取历史报告失败");
    }
    job.value = payload;
    activeView.value = "report";
  } catch (error) {
    historyError.value = error.message;
  }
}

function rerunHistoryJob(historyJob) {
  applyRequest(historyJob.request);
  activeView.value = "review";
}

function navigate(view) {
  activeView.value = view;
  if (view === "history") {
    loadHistory();
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
});
</script>

<template>
  <AppShell
    :active-view="activeView"
    :is-running="isRunning"
    :nav-items="navItems"
    :selected-pr-label="selectedPrLabel"
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
      @apply-selected-pull="applySelectedPull"
      @load-pulls="loadPullRequests"
      @load-repositories="loadRepositories"
      @proceed-review="proceedToReview"
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

    <ReportViewer
      v-else-if="activeView === 'report'"
      :job="job"
      :output-text="outputText"
      :run-error="runError"
      @go-runner="activeView = 'review'"
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
