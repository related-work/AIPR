<script setup>
import { FileText } from "@lucide/vue";
import MarkdownIt from "markdown-it";
import { computed, ref } from "vue";

const props = defineProps({
  job: { type: Object, default: null },
  runError: { type: String, default: "" },
  outputText: { type: String, required: true }
});

const emit = defineEmits(["go-runner"]);

const viewMode = ref("rendered");
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

      <div class="report-tabs" aria-label="报告展示方式">
        <button :class="{ active: viewMode === 'rendered' }" type="button" @click="viewMode = 'rendered'">
          渲染报告
        </button>
        <button :class="{ active: viewMode === 'raw' }" type="button" @click="viewMode = 'raw'">
          原始输出
        </button>
        <button :class="{ active: viewMode === 'json' }" type="button" @click="viewMode = 'json'">
          JSON
        </button>
      </div>

      <article
        v-if="viewMode === 'rendered' && renderedMarkdown"
        class="markdown-report"
        v-html="renderedMarkdown"
      ></article>
      <pre v-else-if="viewMode === 'json'" class="result-output report-output">{{ formattedJson || rawOutput }}</pre>
      <pre v-else class="result-output report-output">{{ rawOutput }}</pre>
    </section>
  </section>
</template>
