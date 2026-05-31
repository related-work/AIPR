<script setup>
import { Terminal } from "@lucide/vue";

defineProps({
  activeView: { type: String, required: true },
  navItems: { type: Array, required: true },
  selectedPrLabel: { type: String, required: true },
  isRunning: { type: Boolean, default: false },
  showPrContext: { type: Boolean, default: false }
});

const emit = defineEmits(["navigate", "open-command"]);
</script>

<template>
  <div class="workspace-shell">
    <aside class="sidebar">
      <div class="brand-block">
        <p class="eyebrow">Local Console</p>
        <h1>AI PR Review</h1>
      </div>

      <nav class="side-nav" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.id"
          :class="{ active: activeView === item.id }"
          type="button"
          @click="emit('navigate', item.id)"
        >
          <component :is="item.icon" aria-hidden="true" :size="18" />
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="sidebar-status">
        <span :class="['status-dot', isRunning ? 'running' : 'idle']"></span>
        <span>{{ isRunning ? "running" : "idle" }}</span>
      </div>
    </aside>

    <main class="main-pane">
      <header v-if="showPrContext" class="main-header">
        <div>
          <p class="header-label">当前 PR</p>
          <h2>{{ selectedPrLabel }}</h2>
        </div>
        <button class="ghost-button" type="button" @click="emit('open-command')">
          <Terminal aria-hidden="true" :size="17" />
          <span>生成命令</span>
        </button>
      </header>

      <slot />
    </main>
  </div>
</template>
