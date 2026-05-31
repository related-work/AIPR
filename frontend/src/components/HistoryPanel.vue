<script setup>
import { Download, History, RefreshCw, Search, Trash2 } from "@lucide/vue";

defineProps({
  historyFilters: { type: Object, required: true },
  historyJobs: { type: Array, required: true },
  loadingHistory: { type: Boolean, default: false },
  historyError: { type: String, default: "" }
});

const emit = defineEmits([
  "clear",
  "delete-job",
  "export-job",
  "refresh",
  "update-filter",
  "view-job",
  "rerun-job"
]);

function latestProgress(job) {
  const progress = job.progress || [];
  return progress.length ? progress[progress.length - 1] : null;
}

function updateFilter(key, event) {
  emit("update-filter", { key, value: event.target.value });
}

function canDelete(job) {
  return !["queued", "running"].includes(job.status);
}
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <History aria-hidden="true" :size="22" />
      <div>
        <h2>历史记录</h2>
        <p>管理本地持久化的 Review 运行结果。</p>
      </div>
    </div>

    <section class="panel history-panel">
      <div class="report-toolbar">
        <strong>{{ historyJobs.length }} 条记录</strong>
        <div class="history-toolbar-actions">
          <button class="ghost-button" type="button" :disabled="loadingHistory" @click="emit('refresh')">
            <RefreshCw v-if="loadingHistory" aria-hidden="true" class="spin" :size="17" />
            <RefreshCw v-else aria-hidden="true" :size="17" />
            <span>{{ loadingHistory ? "刷新中" : "刷新" }}</span>
          </button>
          <button class="danger-button" type="button" :disabled="loadingHistory || !historyJobs.length" @click="emit('clear')">
            <Trash2 aria-hidden="true" :size="16" />
            <span>清空已完成</span>
          </button>
        </div>
      </div>

      <div class="history-filters">
        <label class="field">
          搜索
          <input
            :value="historyFilters.query"
            placeholder="PR、输出、状态"
            @input="updateFilter('query', $event)"
            @keydown.enter="emit('refresh')"
          />
        </label>
        <label class="field">
          仓库
          <input
            :value="historyFilters.repo"
            placeholder="owner/repo"
            @input="updateFilter('repo', $event)"
            @keydown.enter="emit('refresh')"
          />
        </label>
        <label class="field">
          状态
          <select :value="historyFilters.status" @change="updateFilter('status', $event)">
            <option value="">全部</option>
            <option value="queued">queued</option>
            <option value="running">running</option>
            <option value="succeeded">succeeded</option>
            <option value="failed">failed</option>
          </select>
        </label>
        <label class="field">
          开始日期
          <input type="date" :value="historyFilters.from" @input="updateFilter('from', $event)" />
        </label>
        <label class="field">
          结束日期
          <input type="date" :value="historyFilters.to" @input="updateFilter('to', $event)" />
        </label>
        <button class="primary-button" type="button" :disabled="loadingHistory" @click="emit('refresh')">
          <Search aria-hidden="true" :size="17" />
          <span>筛选</span>
        </button>
      </div>

      <p v-if="historyError" class="field-error">{{ historyError }}</p>
      <div v-if="!historyJobs.length && !loadingHistory" class="empty-state">还没有 Review 运行记录</div>

      <div v-else class="history-list">
        <article v-for="job in historyJobs" :key="job.id" class="history-item">
          <div>
            <div class="history-title">
              <span :class="['status-dot', job.status]"></span>
              <strong>{{ job.request.prUrl }}</strong>
            </div>
            <p>{{ job.outputPreview || job.command }}</p>
            <small>
              {{ job.createdAt }} · {{ job.status }} · exit {{ job.exitCode ?? "-" }}
              <template v-if="latestProgress(job)"> · {{ latestProgress(job).label }}</template>
            </small>
          </div>
          <div class="history-actions">
            <button class="ghost-button" type="button" @click="emit('view-job', job)">查看报告</button>
            <button class="ghost-button" type="button" @click="emit('rerun-job', job)">重新运行</button>
            <button class="ghost-button icon-action" type="button" title="导出 Markdown" @click="emit('export-job', job, 'markdown')">
              <Download aria-hidden="true" :size="16" />
              <span>MD</span>
            </button>
            <button class="ghost-button icon-action" type="button" title="导出 JSON" @click="emit('export-job', job, 'json')">
              <Download aria-hidden="true" :size="16" />
              <span>JSON</span>
            </button>
            <button
              class="danger-button icon-action"
              type="button"
              :disabled="!canDelete(job)"
              title="删除历史"
              @click="emit('delete-job', job)"
            >
              <Trash2 aria-hidden="true" :size="16" />
              <span>删除</span>
            </button>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
