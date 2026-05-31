<script setup>
import { ExternalLink, ListChecks, Play, RefreshCw } from "@lucide/vue";

defineProps({
  batchError: { type: String, default: "" },
  batchJob: { type: Object, default: null },
  isRunning: { type: Boolean, default: false },
  loadingPulls: { type: Boolean, default: false },
  pulls: { type: Array, required: true },
  selectedRepo: { type: Object, default: null },
  selectedUrls: { type: Array, required: true }
});

const emit = defineEmits([
  "clear-selection",
  "go-browse",
  "open-batch-reports",
  "open-report",
  "run",
  "select-all",
  "toggle-pull"
]);
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <ListChecks aria-hidden="true" :size="22" />
      <div>
        <h2>批量 Review</h2>
        <p>选择多个 PR 后按队列逐个运行，每个 PR 会生成独立报告。</p>
      </div>
    </div>

    <section class="panel batch-panel">
      <div class="batch-heading">
        <div>
          <strong>{{ selectedRepo?.fullName || "尚未选择仓库" }}</strong>
          <span>{{ selectedUrls.length }} / {{ pulls.length }} 个 PR 已选择</span>
        </div>
        <div class="batch-actions">
          <button class="ghost-button" type="button" @click="emit('go-browse')">切换仓库</button>
          <button class="ghost-button" type="button" :disabled="!pulls.length" @click="emit('select-all')">全选</button>
          <button class="ghost-button" type="button" :disabled="!selectedUrls.length" @click="emit('clear-selection')">清空</button>
        </div>
      </div>

      <p v-if="batchError" class="field-error">{{ batchError }}</p>

      <div v-if="loadingPulls" class="empty-state">正在读取 PR...</div>
      <div v-else-if="!pulls.length" class="empty-state">请先在 PR 浏览页选择一个有 PR 的仓库</div>
      <div v-else class="batch-pull-list">
        <label v-for="pull in pulls" :key="pull.url" class="batch-pull-item">
          <input
            type="checkbox"
            :checked="selectedUrls.includes(pull.url)"
            @change="emit('toggle-pull', pull.url)"
          />
          <span>
            <strong>#{{ pull.number }} {{ pull.title }}</strong>
            <small>{{ pull.author }} · {{ pull.updatedAt }}</small>
          </span>
        </label>
      </div>

      <div class="action-row">
        <button class="primary-button" type="button" :disabled="!selectedUrls.length || isRunning" @click="emit('run')">
          <RefreshCw v-if="isRunning" aria-hidden="true" class="spin" :size="18" />
          <Play v-else aria-hidden="true" :size="18" />
          <span>{{ isRunning ? "批量运行中" : "运行选中 PR" }}</span>
        </button>
      </div>
    </section>

    <section v-if="batchJob" class="panel batch-panel">
      <div class="batch-heading">
        <div>
          <strong>批量任务</strong>
          <span>{{ batchJob.completed }} / {{ batchJob.total }} 完成 · {{ batchJob.failed }} 失败</span>
        </div>
        <div class="batch-actions">
          <button
            class="ghost-button"
            type="button"
            :disabled="!batchJob.items?.some((item) => item.jobId)"
            @click="emit('open-batch-reports')"
          >
            查看全部报告
          </button>
          <span :class="['history-status', batchJob.status]">{{ batchJob.status }}</span>
        </div>
      </div>

      <div class="batch-result-list">
        <article v-for="item in batchJob.items" :key="item.id" class="batch-result-item">
          <div>
            <strong>#{{ item.number || "-" }} {{ item.prUrl }}</strong>
            <small>
              {{ item.status }} · risk {{ item.risk }} · blocking {{ item.blockingFindings }}
              <template v-if="item.coverageRatio !== null && item.coverageRatio !== undefined">
                · coverage {{ Number(item.coverageRatio).toFixed(2) }}
              </template>
            </small>
            <p v-if="item.error" class="field-error">{{ item.error }}</p>
          </div>
          <div class="batch-item-actions">
            <span>{{ item.mergeRecommendation || "等待结果" }}</span>
            <button
              class="ghost-button icon-action"
              type="button"
              title="打开报告"
              :disabled="!item.jobId"
              @click="emit('open-report', item)"
            >
              <ExternalLink aria-hidden="true" :size="16" />
            </button>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
