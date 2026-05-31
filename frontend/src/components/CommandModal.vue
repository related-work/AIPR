<script setup>
import { Check, Copy, Terminal } from "@lucide/vue";

defineProps({
  generatedCommand: { type: String, required: true },
  commandMode: { type: String, required: true },
  copied: { type: Boolean, default: false }
});

const emit = defineEmits(["copy", "close", "update:command-mode"]);
</script>

<template>
  <div class="command-overlay" role="dialog" aria-modal="true" aria-label="生成命令">
    <section class="command-modal">
      <div class="panel-heading">
        <Terminal aria-hidden="true" :size="20" />
        <div>
          <h2>生成命令</h2>
          <p>根据当前表单生成，不会自动运行。</p>
        </div>
      </div>

      <div class="mode-switch" aria-label="命令运行方式">
        <button
          :class="{ active: commandMode === 'module' }"
          type="button"
          @click="emit('update:command-mode', 'module')"
        >
          源码模式
        </button>
        <button
          :class="{ active: commandMode === 'binary' }"
          type="button"
          @click="emit('update:command-mode', 'binary')"
        >
          安装命令
        </button>
      </div>

      <div class="command-box">
        <code>{{ generatedCommand }}</code>
        <button type="button" @click="emit('copy')">
          <Check v-if="copied" aria-hidden="true" :size="17" />
          <Copy v-else aria-hidden="true" :size="17" />
          <span>{{ copied ? "已复制" : "复制" }}</span>
        </button>
      </div>

      <div class="modal-actions">
        <button class="ghost-button" type="button" @click="emit('close')">关闭</button>
      </div>
    </section>
  </div>
</template>
