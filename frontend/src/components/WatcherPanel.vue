<script setup>
import { Pause, Play, RefreshCw, SearchCode, Trash2 } from "@lucide/vue";

defineProps({
  creating: { type: Boolean, default: false },
  error: { type: String, default: "" },
  explorer: { type: Object, required: true },
  form: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  watchers: { type: Array, required: true }
});

const emit = defineEmits([
  "check",
  "create",
  "delete",
  "go-browse",
  "open-report",
  "pause",
  "refresh",
  "start"
]);
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <SearchCode aria-hidden="true" :size="22" />
      <div>
        <h2>PR 监控</h2>
        <p>持续关注一个仓库，发现新 PR 或新 commit 后自动创建本地 Review；配置会保存在本机，重启后需手动启动。</p>
      </div>
    </div>

    <section class="panel watcher-panel">
      <div class="watcher-form-grid">
        <label class="field">
          <span>Owner / Org</span>
          <input v-model="explorer.owner" autocomplete="off" placeholder="oldsheeppp" type="text" />
        </label>
        <label class="field">
          <span>Repository</span>
          <input v-model="explorer.repo" autocomplete="off" placeholder="aiprtest" type="text" />
        </label>
        <label class="field">
          <span>轮询间隔（秒）</span>
          <input v-model.number="form.intervalSeconds" min="10" max="86400" type="number" />
        </label>
        <label class="field">
          <span>模型档位</span>
          <select v-model="form.model">
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="accurate">Accurate</option>
          </select>
        </label>
      </div>

      <div class="toggle-grid">
        <label class="toggle-row">
          <input v-model="form.includeDrafts" type="checkbox" />
          <span>
            <strong>包含 Draft PR</strong>
            <small>默认跳过草稿，减少无效扫描。</small>
          </span>
        </label>
        <label class="toggle-row">
          <input v-model="form.noLlm" type="checkbox" />
          <span>
            <strong>只跑规则引擎</strong>
            <small>监控模式下可显著降低成本。</small>
          </span>
        </label>
      </div>

      <p v-if="error" class="field-error">{{ error }}</p>

      <div class="action-row">
        <button class="primary-button" type="button" :disabled="creating" @click="emit('create')">
          <RefreshCw v-if="creating" aria-hidden="true" class="spin" :size="18" />
          <Play v-else aria-hidden="true" :size="18" />
          <span>{{ creating ? "创建中" : "创建并启动监控" }}</span>
        </button>
        <button class="secondary-wide-button" type="button" :disabled="loading" @click="emit('refresh')">
          <RefreshCw aria-hidden="true" :class="{ spin: loading }" :size="18" />
          <span>刷新状态</span>
        </button>
        <button class="ghost-button" type="button" @click="emit('go-browse')">从 PR 浏览选择仓库</button>
      </div>
    </section>

    <section class="panel watcher-panel">
      <div class="batch-heading">
        <div>
          <strong>监控列表</strong>
          <span>{{ watchers.length }} 个 watcher</span>
        </div>
      </div>

      <div v-if="!watchers.length && !loading" class="empty-state">还没有监控任务</div>
      <div v-else class="watcher-list">
        <article v-for="watcher in watchers" :key="watcher.id" class="watcher-item">
          <div class="watcher-main">
            <div>
              <strong>{{ watcher.request.owner }}/{{ watcher.request.repo }}</strong>
              <span :class="['history-status', watcher.status]">{{ watcher.status }}</span>
            </div>
            <small>
              interval {{ watcher.request.intervalSeconds }}s · model {{ watcher.request.model }}
              · triggered {{ watcher.triggered }} · last {{ watcher.lastCheckedAt || "未检查" }}
            </small>
            <p v-if="watcher.lastError" class="field-error">{{ watcher.lastError }}</p>
          </div>

          <div class="watcher-actions">
            <button class="ghost-button icon-action" type="button" title="启动" @click="emit('start', watcher)">
              <Play aria-hidden="true" :size="16" />
            </button>
            <button class="ghost-button icon-action" type="button" title="暂停" @click="emit('pause', watcher)">
              <Pause aria-hidden="true" :size="16" />
            </button>
            <button class="ghost-button icon-action" type="button" title="立即检查" @click="emit('check', watcher)">
              <RefreshCw aria-hidden="true" :size="16" />
            </button>
            <button class="danger-button icon-action" type="button" title="删除" @click="emit('delete', watcher)">
              <Trash2 aria-hidden="true" :size="16" />
            </button>
          </div>

          <div v-if="watcher.recentReviews?.length" class="watcher-reviews">
            <article v-for="review in watcher.recentReviews" :key="`${review.prUrl}:${review.headSha}`">
              <div>
                <strong>#{{ review.prNumber }} {{ review.title || review.prUrl }}</strong>
                <small>{{ review.headSha }} · {{ review.triggeredAt }}</small>
              </div>
              <button
                class="ghost-button icon-action"
                type="button"
                :disabled="!review.jobId"
                @click="emit('open-report', review)"
              >
                打开
              </button>
            </article>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
