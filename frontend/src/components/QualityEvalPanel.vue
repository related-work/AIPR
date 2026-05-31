<script setup>
import { Activity, RefreshCw } from "@lucide/vue";

defineProps({
  comparison: { type: Object, default: null },
  comparisonError: { type: String, default: "" },
  compareBase: { type: String, default: "" },
  compareTarget: { type: String, default: "" },
  evaluation: { type: Object, default: null },
  evaluationError: { type: String, default: "" },
  fixture: { type: String, required: true },
  loadingEvaluation: { type: Boolean, default: false },
  loadingSnapshots: { type: Boolean, default: false },
  savingSnapshot: { type: Boolean, default: false },
  snapshotError: { type: String, default: "" },
  snapshotLabel: { type: String, default: "" },
  snapshots: { type: Array, default: () => [] }
});

const emit = defineEmits([
  "compare-snapshots",
  "refresh-snapshots",
  "run",
  "save-snapshot",
  "update:compare-base",
  "update:compare-target",
  "update:fixture",
  "update:snapshot-label"
]);

function resultStatus(result) {
  return result.passed ? "succeeded" : "failed";
}
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <Activity aria-hidden="true" :size="22" />
      <div>
        <h2>质量评测</h2>
        <p>运行本地固定 fixture，观察规则引擎的误报和漏报。</p>
      </div>
    </div>

    <section class="panel quality-panel">
      <div class="report-toolbar">
        <div class="quality-controls">
          <label class="field">
            Fixture
            <select :value="fixture" @change="emit('update:fixture', $event.target.value)">
              <option value="all">全部</option>
              <option value="high_quality_pr">high_quality_pr</option>
              <option value="low_quality_pr">low_quality_pr</option>
              <option value="harmful_pr">harmful_pr</option>
              <option value="clean_docs_pr">clean_docs_pr</option>
            </select>
          </label>
        </div>
        <button class="primary-button quality-run-button" type="button" :disabled="loadingEvaluation" @click="emit('run')">
          <RefreshCw v-if="loadingEvaluation" aria-hidden="true" class="spin" :size="17" />
          <RefreshCw v-else aria-hidden="true" :size="17" />
          <span>{{ loadingEvaluation ? "运行中" : "运行评测" }}</span>
        </button>
      </div>

      <p v-if="evaluationError" class="field-error">{{ evaluationError }}</p>

      <div v-if="evaluation" class="quality-summary">
        <article class="risk-card">
          <span>fixtures</span>
          <strong>{{ evaluation.total }}</strong>
        </article>
        <article class="risk-card">
          <span>passed</span>
          <strong>{{ evaluation.passed }}</strong>
        </article>
        <article class="risk-card">
          <span>failed</span>
          <strong>{{ evaluation.failed }}</strong>
        </article>
        <article class="risk-card">
          <span>false positives</span>
          <strong>{{ evaluation.falsePositives }}</strong>
        </article>
        <article class="risk-card">
          <span>false negatives</span>
          <strong>{{ evaluation.falseNegatives }}</strong>
        </article>
      </div>

      <div v-if="!evaluation && !loadingEvaluation" class="empty-state">尚未运行质量评测</div>

      <div v-if="evaluation?.results?.length" class="quality-results">
        <article v-for="result in evaluation.results" :key="result.fixtureId" class="quality-result">
          <header>
            <div class="history-title">
              <span :class="['status-dot', resultStatus(result)]"></span>
              <strong>{{ result.fixtureId }}</strong>
            </div>
            <span>{{ result.kind }} · {{ result.passed ? "pass" : "fail" }}</span>
          </header>
          <p>{{ result.title }}</p>
          <div class="quality-rule-grid">
            <div>
              <span>预期</span>
              <code>{{ result.expectedRuleIds.length ? result.expectedRuleIds.join(", ") : "-" }}</code>
            </div>
            <div>
              <span>实际</span>
              <code>{{ result.actualRuleIds.length ? result.actualRuleIds.join(", ") : "-" }}</code>
            </div>
            <div>
              <span>漏报</span>
              <code>{{ result.missedRuleIds.length ? result.missedRuleIds.join(", ") : "-" }}</code>
            </div>
            <div>
              <span>误报</span>
              <code>{{ result.unexpectedRuleIds.length ? result.unexpectedRuleIds.join(", ") : "-" }}</code>
            </div>
          </div>
          <small>finding {{ result.findingCount }} · merge {{ result.mergeRecommendation }}</small>
        </article>
      </div>
    </section>

    <section class="panel quality-panel">
      <div class="report-toolbar">
        <div>
          <h3>评测快照</h3>
          <p>保存当前规则评测结果，并比较两次结果的变化。</p>
        </div>
        <button class="ghost-button" type="button" :disabled="loadingSnapshots" @click="emit('refresh-snapshots')">
          <RefreshCw v-if="loadingSnapshots" aria-hidden="true" class="spin" :size="17" />
          <RefreshCw v-else aria-hidden="true" :size="17" />
          <span>刷新</span>
        </button>
      </div>

      <div class="snapshot-actions">
        <label class="field">
          快照名称
          <input
            :value="snapshotLabel"
            placeholder="例如：调整 SQL 规则前"
            @input="emit('update:snapshot-label', $event.target.value)"
          />
        </label>
        <button class="primary-button quality-run-button" type="button" :disabled="savingSnapshot" @click="emit('save-snapshot')">
          <span>{{ savingSnapshot ? "保存中" : "保存当前评测快照" }}</span>
        </button>
      </div>

      <p v-if="snapshotError" class="field-error">{{ snapshotError }}</p>

      <div v-if="snapshots.length" class="snapshot-grid">
        <article v-for="snapshot in snapshots" :key="snapshot.id" class="snapshot-card">
          <strong>{{ snapshot.label }}</strong>
          <span>{{ snapshot.createdAt }}</span>
          <small>
            {{ snapshot.passed }}/{{ snapshot.total }} passed · FP {{ snapshot.falsePositives }} · FN {{ snapshot.falseNegatives }}
          </small>
        </article>
      </div>
      <div v-else-if="!loadingSnapshots" class="empty-state compact-empty">还没有评测快照</div>

      <div class="snapshot-compare">
        <label class="field">
          基线
          <select :value="compareBase" @change="emit('update:compare-base', $event.target.value)">
            <option value="">选择基线</option>
            <option v-for="snapshot in snapshots" :key="`base-${snapshot.id}`" :value="snapshot.id">
              {{ snapshot.label }}
            </option>
          </select>
        </label>
        <label class="field">
          对比目标
          <select :value="compareTarget" @change="emit('update:compare-target', $event.target.value)">
            <option value="">选择目标</option>
            <option v-for="snapshot in snapshots" :key="`target-${snapshot.id}`" :value="snapshot.id">
              {{ snapshot.label }}
            </option>
          </select>
        </label>
        <button class="primary-button quality-run-button" type="button" @click="emit('compare-snapshots')">比较快照</button>
      </div>

      <p v-if="comparisonError" class="field-error">{{ comparisonError }}</p>

      <div v-if="comparison" class="comparison-summary">
        <article class="risk-card">
          <span>passed</span>
          <strong>{{ comparison.deltaPassed }}</strong>
        </article>
        <article class="risk-card">
          <span>failed</span>
          <strong>{{ comparison.deltaFailed }}</strong>
        </article>
        <article class="risk-card">
          <span>false positives</span>
          <strong>{{ comparison.deltaFalsePositives }}</strong>
        </article>
        <article class="risk-card">
          <span>false negatives</span>
          <strong>{{ comparison.deltaFalseNegatives }}</strong>
        </article>
      </div>

      <div v-if="comparison?.fixtureChanges?.length" class="quality-results">
        <article v-for="change in comparison.fixtureChanges" :key="change.fixtureId" class="quality-result">
          <header>
            <div class="history-title">
              <span :class="['status-dot', change.passedChanged ? 'failed' : 'succeeded']"></span>
              <strong>{{ change.fixtureId }}</strong>
            </div>
            <span>{{ change.kind }}</span>
          </header>
          <div class="quality-rule-grid">
            <div>
              <span>基线规则</span>
              <code>{{ change.baseActualRuleIds.length ? change.baseActualRuleIds.join(", ") : "-" }}</code>
            </div>
            <div>
              <span>目标规则</span>
              <code>{{ change.targetActualRuleIds.length ? change.targetActualRuleIds.join(", ") : "-" }}</code>
            </div>
            <div>
              <span>新增</span>
              <code>{{ change.addedRuleIds.length ? change.addedRuleIds.join(", ") : "-" }}</code>
            </div>
            <div>
              <span>移除</span>
              <code>{{ change.removedRuleIds.length ? change.removedRuleIds.join(", ") : "-" }}</code>
            </div>
          </div>
        </article>
      </div>
      <div v-else-if="comparison" class="empty-state compact-empty">两个快照没有 fixture 级变化</div>
    </section>
  </section>
</template>
