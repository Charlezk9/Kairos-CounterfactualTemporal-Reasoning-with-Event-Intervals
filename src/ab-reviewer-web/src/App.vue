<script setup>
import { computed, onMounted, ref } from "vue";
import { Moon, Sunny } from "@element-plus/icons-vue";
import SetupPanel from "./components/SetupPanel.vue";
import ReviewWorkspace from "./components/ReviewWorkspace.vue";
import { createDemoSession, loadDirectAuditSession } from "./lib/audit.js";

const session = ref(null);
const loading = ref(false);
const theme = ref("light");

const themeIcon = computed(() => (theme.value === "dark" ? Sunny : Moon));
const themeLabel = computed(() => (theme.value === "dark" ? "切换浅色" : "切换深色"));

function applyTheme(value) {
  theme.value = value;
  document.documentElement.classList.toggle("dark", value === "dark");
  localStorage.setItem("kairos-review-theme", value);
}

function toggleTheme() {
  applyTheme(theme.value === "dark" ? "light" : "dark");
}

async function startReview(request) {
  loading.value = true;
  try {
    session.value = await loadDirectAuditSession(request);
    ElMessage.success("固定审核文件校验通过，已进入本地审核。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "固定审核文件读取失败。");
  } finally {
    loading.value = false;
  }
}

function openDemo() {
  session.value = createDemoSession();
  ElMessage.info("当前为演示数据，不能导出正式结果。");
}

function exitReview() {
  session.value = null;
}

onMounted(() => {
  const saved = localStorage.getItem("kairos-review-theme");
  const preferredDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (preferredDark ? "dark" : "light"));
});
</script>

<template>
  <el-config-provider>
    <div class="app-shell">
      <div v-if="loading" class="loading-overlay" role="status" aria-live="polite">
        <span class="loading-mark">K</span>
        <strong>正在读取并校验固定审核文件</strong>
      </div>
      <button
        class="theme-toggle"
        type="button"
        :aria-label="themeLabel"
        :title="themeLabel"
        @click="toggleTheme"
      >
        <el-icon><component :is="themeIcon" /></el-icon>
      </button>

      <SetupPanel
        v-if="!session"
        @start="startReview"
        @demo="openDemo"
      />
      <ReviewWorkspace
        v-else
        :session="session"
        @exit="exitReview"
      />
    </div>
  </el-config-provider>
</template>
