<script setup>
import { RefreshCw, ShieldCheck } from "@lucide/vue";
import { ref } from "vue";

const emit = defineEmits(["open-command"]);

const doctor = ref(null);
const doctorError = ref("");
const loadingDoctor = ref(false);

async function runDoctor(smoke = false) {
  doctorError.value = "";
  loadingDoctor.value = true;
  try {
    const response = await fetch(`/api/doctor?smoke=${smoke ? "true" : "false"}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "配置检查失败");
    }
    doctor.value = payload;
  } catch (error) {
    doctorError.value = error.message;
  } finally {
    loadingDoctor.value = false;
  }
}
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
        <p>直接调用本地后端 doctor，不展示密钥值。</p>
        <div class="settings-actions">
          <button class="ghost-button" type="button" :disabled="loadingDoctor" @click="runDoctor(false)">
            <RefreshCw v-if="loadingDoctor" aria-hidden="true" class="spin" :size="17" />
            <span>检查配置</span>
          </button>
          <button class="ghost-button" type="button" :disabled="loadingDoctor" @click="runDoctor(true)">
            <RefreshCw v-if="loadingDoctor" aria-hidden="true" class="spin" :size="17" />
            <span>运行 smoke</span>
          </button>
        </div>
      </article>

      <article class="panel info-panel">
        <h3>命令模式</h3>
        <p>命令生成保持为按需弹窗，不进入主流程。</p>
        <button class="ghost-button" type="button" @click="emit('open-command')">生成当前命令</button>
      </article>
    </section>

    <p v-if="doctorError" class="field-error">{{ doctorError }}</p>

    <section v-if="doctor" class="panel doctor-panel">
      <div class="doctor-header">
        <h3>Doctor 结果</h3>
        <span :class="['doctor-status', doctor.ok ? 'ok' : 'failed']">
          {{ doctor.ok ? "通过" : "未通过" }}
        </span>
      </div>

      <div class="doctor-grid">
        <div>
          <span>GitHub Token</span>
          <strong>{{ doctor.githubTokenConfigured ? "已配置" : "未配置" }}</strong>
        </div>
        <div>
          <span>OpenAI Key</span>
          <strong>{{ doctor.openaiApiKeyConfigured ? "已配置" : "未配置" }}</strong>
        </div>
        <div>
          <span>Base URL</span>
          <strong>{{ doctor.openaiBaseUrlStatus }}</strong>
        </div>
        <div>
          <span>API Mode</span>
          <strong>{{ doctor.apiMode }}</strong>
        </div>
        <div>
          <span>Fast Model</span>
          <strong>{{ doctor.fastModel }}</strong>
        </div>
        <div>
          <span>Strong Model</span>
          <strong>{{ doctor.strongModel }}</strong>
        </div>
        <div>
          <span>Smoke Test</span>
          <strong>{{ doctor.smokeOk ? "通过" : "未通过/未运行" }}</strong>
        </div>
      </div>

      <p v-if="doctor.smokeError" class="field-error">{{ doctor.smokeError }}</p>

      <div v-if="doctor.warnings?.length" class="doctor-list">
        <h4>警告</h4>
        <ul>
          <li v-for="item in doctor.warnings" :key="item">{{ item }}</li>
        </ul>
      </div>

      <div v-if="doctor.limitations?.length" class="doctor-list">
        <h4>限制</h4>
        <ul>
          <li v-for="item in doctor.limitations" :key="item">{{ item }}</li>
        </ul>
      </div>
    </section>
  </section>
</template>
