<script setup>
import { ShieldCheck } from "@lucide/vue";

const emit = defineEmits(["open-command"]);
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <ShieldCheck aria-hidden="true" :size="22" />
      <div>
        <h2>本地配置</h2>
        <p>浏览器不读取密钥，所有凭据只留在本地 Python 进程。</p>
      </div>
    </div>

    <section class="settings-grid">
      <article class="panel info-panel">
        <h3>凭据来源</h3>
        <p>GitHub 和 OpenAI 凭据由本地服务从环境变量或 `.ai-pr-review.local.yml` 读取。</p>
        <code>GITHUB_TOKEN / OPENAI_API_KEY</code>
      </article>

      <article class="panel info-panel">
        <h3>配置检查</h3>
        <p>需要检查模型、base URL 和 smoke test 时，在终端运行 doctor。</p>
        <code>PYTHONPATH=src python -m ai_pr_review doctor</code>
      </article>

      <article class="panel info-panel">
        <h3>命令模式</h3>
        <p>命令生成保持为按需弹窗，不进入主流程。</p>
        <button class="ghost-button" type="button" @click="emit('open-command')">生成当前命令</button>
      </article>
    </section>
  </section>
</template>
