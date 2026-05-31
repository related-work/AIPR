<script setup>
import { RefreshCw, SearchCode } from "@lucide/vue";

defineProps({
  explorer: { type: Object, required: true },
  repos: { type: Array, required: true },
  pulls: { type: Array, required: true },
  repoFilter: { type: String, required: true },
  filteredRepos: { type: Array, required: true },
  selectedRepo: { type: Object, default: null },
  selectedPull: { type: Object, default: null },
  browseError: { type: String, default: "" },
  loadingRepos: { type: Boolean, default: false },
  loadingPulls: { type: Boolean, default: false }
});

const emit = defineEmits([
  "load-repositories",
  "load-pulls",
  "apply-selected-pull",
  "proceed-review",
  "update:repo-filter"
]);
</script>

<template>
  <section class="view-stack">
    <div class="page-title">
      <SearchCode aria-hidden="true" :size="22" />
      <div>
        <h2>PR 浏览</h2>
        <p>输入 GitHub 用户或组织，选择仓库和 Pull Request。</p>
      </div>
    </div>

    <section class="panel browser-panel">
      <div class="owner-row">
        <label class="field">
          <span>GitHub 用户 / 组织</span>
          <input
            v-model="explorer.owner"
            autocomplete="off"
            placeholder="oldsheeppp"
            type="text"
            @keydown.enter.prevent="emit('load-repositories')"
          />
        </label>
        <button class="load-button" type="button" :disabled="loadingRepos" @click="emit('load-repositories')">
          <RefreshCw v-if="loadingRepos" aria-hidden="true" class="spin" :size="17" />
          <SearchCode v-else aria-hidden="true" :size="17" />
          <span>{{ loadingRepos ? "读取中" : "读取仓库" }}</span>
        </button>
      </div>

      <p v-if="browseError" class="field-error">{{ browseError }}</p>
    </section>

    <section v-if="repos.length" class="split-grid">
      <div class="panel list-panel">
        <div class="panel-heading compact-heading">
          <div>
            <h3>仓库</h3>
            <p>{{ repos.length }} 个仓库</p>
          </div>
        </div>

        <label class="field">
          <span>搜索仓库</span>
          <input
            :value="repoFilter"
            autocomplete="off"
            placeholder="输入仓库名过滤"
            type="text"
            @input="emit('update:repo-filter', $event.target.value)"
          />
        </label>

        <div class="repo-list">
          <button
            v-for="repo in filteredRepos"
            :key="repo.fullName"
            :class="{ active: explorer.repo === repo.name }"
            type="button"
            @click="
              explorer.repo = repo.name;
              emit('load-pulls');
            "
          >
            <span>{{ repo.fullName }}</span>
            <small>{{ repo.archived ? "archived" : repo.defaultBranch }}</small>
          </button>
        </div>
      </div>

      <div class="panel list-panel">
        <div class="panel-heading compact-heading">
          <div>
            <h3>Pull Requests</h3>
            <p>{{ selectedRepo?.fullName || "选择仓库" }}</p>
          </div>
          <select v-model="explorer.state" class="small-select" @change="emit('load-pulls')">
            <option value="open">Open</option>
            <option value="all">All</option>
            <option value="closed">Closed</option>
          </select>
        </div>

        <div v-if="loadingPulls" class="empty-state">正在读取 PR...</div>
        <div v-else-if="!pulls.length" class="empty-state">没有可选 PR</div>
        <div v-else class="pull-list">
          <button
            v-for="pull in pulls"
            :key="pull.url"
            :class="{ active: explorer.pullUrl === pull.url }"
            type="button"
            @click="
              explorer.pullUrl = pull.url;
              emit('apply-selected-pull');
            "
          >
            <strong>#{{ pull.number }} {{ pull.title }}</strong>
            <span>{{ pull.author }} · {{ pull.updatedAt }}</span>
          </button>
        </div>

        <button
          class="primary-button"
          type="button"
          :disabled="!selectedPull"
          @click="emit('proceed-review')"
        >
          选择并进入 Review
        </button>
      </div>
    </section>
  </section>
</template>
