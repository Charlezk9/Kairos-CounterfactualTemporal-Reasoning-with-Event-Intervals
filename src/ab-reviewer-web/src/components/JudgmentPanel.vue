<script setup>
import { computed } from "vue";
import { CircleCheck, CircleClose, InfoFilled, Lock } from "@element-plus/icons-vue";
import { JUDGMENT_FIELDS, overallValue } from "../lib/audit.js";

const props = defineProps({
  model: { type: Object, required: true },
  aiA: { type: Object, default: null },
  aiB: { type: Object, default: null },
  locked: { type: Boolean, default: false },
});

const emit = defineEmits(["field", "notes"]);

const overall = computed(() => overallValue(props.model));

function aiLabel(value) {
  return value ? "是" : "否";
}
</script>

<template>
  <aside class="judgment-panel" aria-label="五项审核判断">
    <div class="judgment-heading">
      <div>
        <h2>五项判断</h2>
        <p>每项都必须依据当前两条语句独立判断。</p>
      </div>
      <el-icon v-if="locked"><Lock /></el-icon>
    </div>

    <div class="judgment-list">
      <section
        v-for="(field, index) in JUDGMENT_FIELDS"
        :key="field.key"
        class="judgment-item"
        :class="{ disagreement: aiA && aiA[field.key] !== aiB[field.key] }"
      >
        <div class="judgment-title">
          <span class="judgment-number">{{ index + 1 }}</span>
          <div>
            <h3>{{ field.short }}</h3>
            <p>{{ field.question }}</p>
          </div>
        </div>
        <div class="judgment-guide">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ field.guide }}</span>
        </div>

        <div v-if="aiA" class="ai-compare">
          <span :class="{ negative: !aiA[field.key] }">
            AI-A：{{ aiLabel(aiA[field.key]) }}
          </span>
          <span :class="{ negative: !aiB[field.key] }">
            AI-B：{{ aiLabel(aiB[field.key]) }}
          </span>
          <strong v-if="aiA[field.key] !== aiB[field.key]">存在分歧</strong>
        </div>

        <el-radio-group
          :model-value="model[field.key]"
          class="judgment-choice"
          :disabled="locked"
          @change="emit('field', field.key, $event)"
        >
          <el-radio-button :value="true">
            <el-icon><CircleCheck /></el-icon>
            是，符合标准
          </el-radio-button>
          <el-radio-button :value="false">
            <el-icon><CircleClose /></el-icon>
            否，存在问题
          </el-radio-button>
        </el-radio-group>
        <el-button
          v-if="model[field.key] !== null && !locked"
          text
          size="small"
          class="clear-choice"
          @click="emit('field', field.key, null)"
        >
          清空本项
        </el-button>
      </section>
    </div>

    <section class="notes-block">
      <label for="review-notes">备注（可选）</label>
      <el-input
        id="review-notes"
        :model-value="model.notes"
        type="textarea"
        :rows="3"
        maxlength="1000"
        show-word-limit
        :disabled="locked"
        placeholder="只记录有助于作者复核的具体问题。"
        @input="emit('notes', $event)"
      />
    </section>

    <section
      class="overall-result"
      :class="{
        pending: overall === null,
        valid: overall === true,
        invalid: overall === false,
      }"
    >
      <span>自动计算 overall_valid</span>
      <strong v-if="overall === null">等待五项完成</strong>
      <strong v-else-if="overall">true，五项全部通过</strong>
      <strong v-else>false，至少一项未通过</strong>
    </section>
  </aside>
</template>
