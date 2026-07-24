<script setup>
import { computed, ref } from "vue";
import {
  Check,
  DocumentChecked,
  Link,
  Lock,
  Warning,
} from "@element-plus/icons-vue";
import { directSourceNames } from "../lib/audit.js";

const emit = defineEmits(["start", "demo"]);

const mode = ref("formal");
const nickname = ref("");
const slot = ref("A");

const requiredFiles = computed(() => {
  return directSourceNames(mode.value, slot.value);
});

const canStart = computed(() => nickname.value.trim());

function switchMode(nextMode) {
  mode.value = nextMode;
}

function submit() {
  emit("start", {
    mode: mode.value,
    nickname: nickname.value,
    slot: slot.value,
  });
}
</script>

<template>
  <main class="setup-page">
    <section class="setup-intro" aria-labelledby="setup-title">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">K</span>
        <div>
          <span class="brand-name">KAIROS</span>
          <span class="brand-meta">Counterfactual temporal review</span>
        </div>
      </div>

      <div class="intro-copy">
        <p class="eyebrow">双人独立审核工作台</p>
        <h1 id="setup-title">看清语句，再做判断。</h1>
        <p>
          并排核对原句与反事实句，完成五项明确判断。正式 A/B
          结果保持冻结 schema，并在本地生成 SHA256。
        </p>
      </div>

      <div class="protocol-note">
        <el-icon><Lock /></el-icon>
        <div>
          <strong>正式审核保持独立</strong>
          <span>Reviewer A 与 B 在各自结果锁定前不得查看或交换对方判断。</span>
        </div>
      </div>
    </section>

    <section class="setup-form" aria-label="创建审核会话">
      <div class="form-heading">
        <h2>创建审核会话</h2>
        <p>直接读取项目中的固定审核文件，不需要手动上传。</p>
      </div>

      <div class="form-block">
        <span class="field-label">审核目的</span>
        <div class="mode-grid">
          <button
            type="button"
            class="mode-card"
            :class="{ active: mode === 'formal' }"
            @click="switchMode('formal')"
          >
            <span class="mode-icon"><el-icon><DocumentChecked /></el-icon></span>
            <span>
              <strong>正式独立 A/B 审核</strong>
              <small>不显示 AI 预审，输出训练门禁所需的正式 JSONL。</small>
            </span>
            <el-icon v-if="mode === 'formal'" class="mode-check"><Check /></el-icon>
          </button>
          <button
            type="button"
            class="mode-card"
            :class="{ active: mode === 'ai-check' }"
            @click="switchMode('ai-check')"
          >
            <span class="mode-icon warning"><el-icon><Warning /></el-icon></span>
            <span>
              <strong>AI 分歧核查</strong>
              <small>并排查看 AI-A 与 AI-B，仅生成诊断结果，不能解锁训练。</small>
            </span>
            <el-icon v-if="mode === 'ai-check'" class="mode-check"><Check /></el-icon>
          </button>
        </div>
      </div>

      <div class="identity-grid">
        <div class="form-block">
          <label class="field-label" for="nickname">审核者昵称</label>
          <el-input
            id="nickname"
            v-model="nickname"
            maxlength="40"
            show-word-limit
            placeholder="用于结果文件名，例如 charles"
          />
        </div>
        <div v-if="mode === 'formal'" class="form-block">
          <span class="field-label">正式审核槽位</span>
          <el-segmented v-model="slot" :options="['A', 'B']" block />
        </div>
      </div>

      <div class="form-block">
        <span class="field-label">固定审核源</span>
        <div class="direct-source-card">
          <el-icon><Link /></el-icon>
          <div>
            <strong>已关联 review-data 目录</strong>
            <p>开始时自动读取并校验以下文件：</p>
            <code v-for="name in requiredFiles" :key="name">
              review-data/{{ name }}
            </code>
          </div>
        </div>
      </div>

      <el-alert
        v-if="mode === 'ai-check'"
        title="AI 核查结果是诊断材料，不是 Reviewer A/B 正式提交。"
        type="warning"
        :closable="false"
        show-icon
      />

      <div class="setup-actions">
        <el-button text @click="emit('demo')">打开演示样例</el-button>
        <el-button
          type="primary"
          size="large"
          :disabled="!canStart"
          @click="submit"
        >
          读取固定文件并开始
        </el-button>
      </div>
    </section>
  </main>
</template>
