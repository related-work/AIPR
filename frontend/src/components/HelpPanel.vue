<script setup>
import { FileJson, ShieldAlert, Settings2 } from "@lucide/vue";

defineProps({
  optionDocs: { type: Array, required: true },
  templates: { type: Array, required: true }
});

const emit = defineEmits(["apply-template", "go-runner"]);
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <Settings2 aria-hidden="true" :size="22" />
      <div>
        <h2>帮助</h2>
        <p>参数说明和常用 Review 模式集中放在这里。</p>
      </div>
    </div>

    <section class="template-panel">
      <article v-for="template in templates" :key="template.name" class="info-card">
        <h3>{{ template.name }}</h3>
        <p>{{ template.description }}</p>
        <button
          class="ghost-button"
          type="button"
          @click="
            emit('apply-template', template);
            emit('go-runner');
          "
        >
          使用模板
        </button>
      </article>
    </section>

    <section class="docs-panel" aria-label="参数说明">
      <article v-for="item in optionDocs" :key="item.title" class="info-card">
        <FileJson v-if="item.title === '--format'" aria-hidden="true" :size="18" />
        <ShieldAlert v-else-if="item.title === '--fail-on'" aria-hidden="true" :size="18" />
        <Settings2 v-else aria-hidden="true" :size="18" />
        <h3>{{ item.title }}</h3>
        <p>{{ item.body }}</p>
      </article>
    </section>
  </section>
</template>
