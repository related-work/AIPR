<script setup>
import { Clipboard, Play, RefreshCw, Settings2, Terminal } from "@lucide/vue";

defineProps({
  form: { type: Object, required: true },
  templates: { type: Array, required: true },
  selectedPull: { type: Object, default: null },
  urlError: { type: String, default: "" },
  contextNotice: { type: String, default: "" },
  isRunning: { type: Boolean, default: false },
  isBrowsing: { type: Boolean, default: false }
});

const emit = defineEmits(["run", "apply-template", "open-command", "go-browse"]);
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <Settings2 aria-hidden="true" :size="22" />
      <div>
        <h2>Review 运行</h2>
        <p>确认 PR 和分析策略，然后启动本地 Review。</p>
      </div>
    </div>

    <section class="panel runner-panel">
      <div class="selected-pr">
        <span>已选择 PR</span>
        <strong v-if="selectedPull">#{{ selectedPull.number }} {{ selectedPull.title }}</strong>
        <strong v-else>手动输入 PR URL</strong>
        <button class="ghost-button" type="button" @click="emit('go-browse')">重新选择</button>
      </div>

      <label class="field wide-field">
        <span>PR URL</span>
        <input v-model="form.prUrl" type="url" placeholder="https://github.com/org/repo/pull/123" />
        <small v-if="urlError" class="field-error">{{ urlError }}</small>
      </label>

      <div class="template-row" aria-label="场景模板">
        <button v-for="template in templates" :key="template.name" type="button" @click="emit('apply-template', template)">
          <Clipboard aria-hidden="true" :size="16" />
          <span>{{ template.name }}</span>
        </button>
      </div>

      <div class="field-grid main-options">
        <label class="field">
          <span>输出格式</span>
          <select v-model="form.format">
            <option value="markdown">Markdown</option>
            <option value="json">JSON</option>
          </select>
        </label>

        <label class="field">
          <span>模型档位</span>
          <select v-model="form.model">
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="accurate">Accurate</option>
          </select>
        </label>

        <label class="field">
          <span>LLM chunk 上限</span>
          <input v-model.number="form.llmMaxChunks" min="1" max="50" type="number" />
        </label>
      </div>

      <div class="toggle-grid">
        <label class="toggle-row">
          <input v-model="form.changedOnly" type="checkbox" />
          <span>
            <strong>仅分析 diff</strong>
            <small>速度更快，适合日常小 PR。</small>
          </span>
        </label>
        <label class="toggle-row">
          <input v-model="form.noLlm" type="checkbox" />
          <span>
            <strong>只跑规则引擎</strong>
            <small>不调用模型，响应最快。</small>
          </span>
        </label>
      </div>

      <details class="advanced-settings">
        <summary>高级设置</summary>
        <div class="field-grid">
          <label class="field">
            <span>CI 阈值</span>
            <select v-model="form.failOn">
              <option value="">不设置</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>

          <label class="toggle-row inline-toggle">
            <input v-model="form.withContext" type="checkbox" />
            <span>
              <strong>检索相关上下文</strong>
              <small>适合复杂 PR。</small>
            </span>
          </label>

          <label class="toggle-row inline-toggle">
            <input v-model="form.debugChunks" type="checkbox" />
            <span>
              <strong>显示 chunk 调试信息</strong>
              <small>查看选择原因。</small>
            </span>
          </label>

          <label class="toggle-row inline-toggle danger-row">
            <input v-model="form.postComment" type="checkbox" />
            <span>
              <strong>写回 GitHub 评论</strong>
              <small>确认后再开启。</small>
            </span>
          </label>

          <label class="toggle-row inline-toggle danger-row">
            <input v-model="form.postInlineComments" type="checkbox" />
            <span>
              <strong>写回行内评论</strong>
              <small>只评论高置信阻塞问题。</small>
            </span>
          </label>
        </div>
      </details>

      <p v-if="contextNotice" class="notice">{{ contextNotice }}</p>

      <div class="action-row">
        <button class="primary-button" type="button" :disabled="Boolean(urlError) || isRunning || isBrowsing" @click="emit('run')">
          <RefreshCw v-if="isRunning || isBrowsing" aria-hidden="true" class="spin" :size="18" />
          <Play v-else aria-hidden="true" :size="18" />
          <span>{{ isRunning ? "正在运行" : isBrowsing ? "正在读取" : "运行 Review" }}</span>
        </button>
        <button class="secondary-wide-button" type="button" @click="emit('open-command')">
          <Terminal aria-hidden="true" :size="18" />
          <span>生成命令</span>
        </button>
      </div>
    </section>
  </section>
</template>
