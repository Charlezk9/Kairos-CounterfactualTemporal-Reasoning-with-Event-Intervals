<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import {
  ArrowLeft,
  ArrowRight,
  Back,
  Check,
  CircleCheck,
  Download,
  FolderOpened,
  Lock,
  Search,
  WarningFilled,
} from "@element-plus/icons-vue";
import JudgmentPanel from "./JudgmentPanel.vue";
import QueryComparison from "./QueryComparison.vue";
import {
  JUDGMENT_FIELDS,
  blankJudgment,
  buildAiCheckPayload,
  buildFormalPayload,
  disagreementFields,
  isComplete,
  overallValue,
  resultFilename,
  sha256Bytes,
} from "../lib/audit.js";

const props = defineProps({
  session: { type: Object, required: true },
});
const emit = defineEmits(["exit"]);

const judgments = reactive({});
const currentIndex = ref(0);
const statusFilter = ref("all");
const disagreementFilter = ref("any");
const searchText = ref("");
const locked = ref(false);
const exporting = ref(false);
const receipt = ref(null);

const isFormal = computed(() => props.session.mode === "formal");

const baseIndices = computed(() => {
  if (isFormal.value) return props.session.items.map((_, index) => index);
  return props.session.items
    .map((_, index) => index)
    .filter(
      (index) =>
        disagreementFields(props.session.aiA[index], props.session.aiB[index]).length >
        0,
    );
});

const filteredIndices = computed(() => {
  let indices = [...baseIndices.value];
  if (!isFormal.value && disagreementFilter.value !== "any") {
    indices = indices.filter((index) =>
      disagreementFields(props.session.aiA[index], props.session.aiB[index]).includes(
        disagreementFilter.value,
      ),
    );
  }
  if (statusFilter.value === "todo") {
    indices = indices.filter(
      (index) => !isComplete(judgments[props.session.items[index].audit_item_id]),
    );
  } else if (statusFilter.value === "invalid") {
    indices = indices.filter((index) => {
      const value = judgments[props.session.items[index].audit_item_id];
      return isComplete(value) && overallValue(value) === false;
    });
  } else if (statusFilter.value === "done") {
    indices = indices.filter((index) =>
      isComplete(judgments[props.session.items[index].audit_item_id]),
    );
  }
  const query = searchText.value.trim();
  if (query) {
    indices = indices.filter(
      (index) =>
        String(index + 1) === query ||
        props.session.items[index].audit_item_id.includes(query),
    );
  }
  return indices;
});

const activeItem = computed(() => props.session.items[currentIndex.value]);
const activeJudgment = computed(
  () => judgments[activeItem.value.audit_item_id],
);
const activeAiA = computed(() =>
  isFormal.value ? null : props.session.aiA[currentIndex.value],
);
const activeAiB = computed(() =>
  isFormal.value ? null : props.session.aiB[currentIndex.value],
);

const completedCount = computed(
  () =>
    baseIndices.value.filter((index) =>
      isComplete(judgments[props.session.items[index].audit_item_id]),
    ).length,
);
const progressPercent = computed(() =>
  baseIndices.value.length
    ? Math.round((completedCount.value / baseIndices.value.length) * 100)
    : 0,
);
const allComplete = computed(
  () => completedCount.value === baseIndices.value.length && baseIndices.value.length > 0,
);
const currentPosition = computed(
  () => filteredIndices.value.indexOf(currentIndex.value),
);
const previousIndex = computed(() =>
  currentPosition.value > 0
    ? filteredIndices.value[currentPosition.value - 1]
    : null,
);
const nextIndex = computed(() =>
  currentPosition.value >= 0 &&
  currentPosition.value < filteredIndices.value.length - 1
    ? filteredIndices.value[currentPosition.value + 1]
    : null,
);

const storageKey = computed(
  () =>
    `kairos-review-draft:${props.session.itemHash}:${props.session.mode}:${
      props.session.slot || "diagnostic"
    }:${props.session.nickname}`,
);

function initializeJudgments() {
  props.session.items.forEach((item) => {
    judgments[item.audit_item_id] = blankJudgment();
  });
  const saved = localStorage.getItem(storageKey.value);
  if (!saved) return false;
  try {
    const parsed = JSON.parse(saved);
    for (const item of props.session.items) {
      const candidate = parsed[item.audit_item_id];
      if (!candidate) continue;
      const clean = blankJudgment();
      for (const field of JUDGMENT_FIELDS) {
        if (
          candidate[field.key] === null ||
          typeof candidate[field.key] === "boolean"
        ) {
          clean[field.key] = candidate[field.key];
        }
      }
      if (typeof candidate.notes === "string") clean.notes = candidate.notes.slice(0, 1000);
      judgments[item.audit_item_id] = clean;
    }
    return true;
  } catch {
    localStorage.removeItem(storageKey.value);
    return false;
  }
}

function selectIndex(index) {
  currentIndex.value = index;
  nextTick(() => document.querySelector(".review-main")?.scrollTo({ top: 0 }));
}

function updateField(key, value) {
  if (locked.value) return;
  judgments[activeItem.value.audit_item_id][key] = value;
}

function updateNotes(value) {
  if (locked.value) return;
  judgments[activeItem.value.audit_item_id].notes = value;
}

function itemState(index) {
  const value = judgments[props.session.items[index].audit_item_id];
  if (!isComplete(value)) return "todo";
  return overallValue(value) ? "valid" : "invalid";
}

function disagreementNames(index) {
  if (isFormal.value) return "";
  const keys = disagreementFields(props.session.aiA[index], props.session.aiB[index]);
  return JUDGMENT_FIELDS.filter((field) => keys.includes(field.key))
    .map((field) => field.short)
    .join("、");
}

function ensureCurrentVisible() {
  if (
    filteredIndices.value.length &&
    !filteredIndices.value.includes(currentIndex.value)
  ) {
    currentIndex.value = filteredIndices.value[0];
  }
}

function downloadFile(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function uniqueFileName(directory, proposed) {
  const names = new Set();
  for await (const name of directory.keys()) names.add(name);
  if (!names.has(proposed) && !names.has(`${proposed}.sha256`)) return proposed;
  const stem = proposed.replace(/\.jsonl$/, "");
  let suffix = 2;
  while (
    names.has(`${stem}-${suffix}.jsonl`) ||
    names.has(`${stem}-${suffix}.jsonl.sha256`)
  ) {
    suffix += 1;
  }
  return `${stem}-${suffix}.jsonl`;
}

async function writeFile(directory, name, content) {
  const handle = await directory.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(content);
  await writable.close();
}

async function exportResults() {
  if (props.session.isDemo) {
    ElMessage.warning("演示数据不能导出结果。");
    return;
  }
  if (!allComplete.value) {
    ElMessage.warning(`仍有 ${baseIndices.value.length - completedCount.value} 条未完成。`);
    return;
  }
  try {
    await ElMessageBox.confirm(
      isFormal.value
        ? "导出后当前会话将锁定。请确认五项判断与备注均已复核。"
        : "此结果仅用于核查 AI 分歧，不能作为正式 A/B 提交。",
      isFormal.value ? "锁定正式审核结果" : "导出分歧核查",
      {
        confirmButtonText: "确认导出",
        cancelButtonText: "继续检查",
        type: isFormal.value ? "warning" : "info",
      },
    );
  } catch (error) {
    if (error === "cancel" || error === "close") return;
    ElMessage.error("无法打开导出确认框，请重试。");
    return;
  }
  exporting.value = true;
  try {
    const payload = isFormal.value
      ? buildFormalPayload(props.session, judgments)
      : buildAiCheckPayload(props.session, judgments, baseIndices.value);
    let fileName = resultFilename(props.session);
    const digest = await sha256Bytes(payload);
    let method = "download";
    if ("showDirectoryPicker" in window && window.isSecureContext) {
      const directory = await window.showDirectoryPicker({
        id: "kairos-review-results",
        mode: "readwrite",
        startIn: "documents",
      });
      if (directory.name !== "results") {
        throw new Error(
          "请选择 src/ab-reviewer-web/results 文件夹。当前选择的文件夹名不是 results。",
        );
      }
      fileName = await uniqueFileName(directory, fileName);
      await writeFile(directory, fileName, payload);
      await writeFile(directory, `${fileName}.sha256`, `${digest}  ${fileName}\n`);
      method = "results-folder";
    } else {
      downloadFile(fileName, payload, "application/x-ndjson;charset=utf-8");
      downloadFile(
        `${fileName}.sha256`,
        `${digest}  ${fileName}\n`,
        "text/plain;charset=utf-8",
      );
    }
    locked.value = true;
    localStorage.removeItem(storageKey.value);
    receipt.value = {
      fileName,
      digest,
      method,
      bytes: new TextEncoder().encode(payload).byteLength,
      count: isFormal.value ? props.session.items.length : baseIndices.value.length,
    };
    ElMessage.success(
      method === "results-folder"
        ? "结果与 SHA256 已写入 results 文件夹。"
        : "浏览器已下载结果与 SHA256，请将它们移入 results 文件夹。",
    );
  } catch (error) {
    if (error?.name !== "AbortError") {
      ElMessage.error(error instanceof Error ? error.message : "结果导出失败。");
    }
  } finally {
    exporting.value = false;
  }
}

watch(
  judgments,
  (value) => {
    if (!locked.value && !props.session.isDemo) {
      localStorage.setItem(storageKey.value, JSON.stringify(value));
    }
  },
  { deep: true },
);
watch([statusFilter, disagreementFilter, searchText], ensureCurrentVisible);

const restoredDraft = initializeJudgments();
currentIndex.value = baseIndices.value[0] ?? 0;

onMounted(() => {
  if (restoredDraft) {
    ElMessage.info("已恢复此浏览器中的本地审核草稿。");
  }
});
</script>

<template>
  <main class="review-page">
    <header class="review-header">
      <div class="review-title">
        <button type="button" class="back-button" @click="emit('exit')">
          <el-icon><Back /></el-icon>
          返回
        </button>
        <div>
          <h1>{{ isFormal ? `Reviewer ${session.slot} 正式审核` : "AI 分歧核查" }}</h1>
          <p>
            {{ session.nickname }}
            <span class="header-separator"></span>
            {{ isFormal ? "独立审核，不显示 AI 判断" : "诊断流程，不作为正式提交" }}
          </p>
        </div>
      </div>

      <div class="review-progress">
        <div>
          <strong>{{ completedCount }} / {{ baseIndices.length }}</strong>
          <span>已完成</span>
        </div>
        <el-progress
          type="circle"
          :percentage="progressPercent"
          :width="52"
          :stroke-width="5"
          :show-text="false"
        />
        <el-button
          type="primary"
          :icon="locked ? Lock : Download"
          :loading="exporting"
          :disabled="!allComplete || session.isDemo || locked"
          @click="exportResults"
        >
          {{ locked ? "结果已锁定" : "锁定并导出" }}
        </el-button>
      </div>
    </header>

    <section v-if="session.isDemo" class="demo-banner">
      <el-icon><WarningFilled /></el-icon>
      当前为三条合成演示数据。界面可操作，但结果导出已禁用。
    </section>

    <div class="review-layout">
      <aside class="item-sidebar" aria-label="审核条目导航">
        <div class="sidebar-controls">
          <el-input v-model="searchText" placeholder="输入序号或条目 ID" clearable>
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-segmented
            v-model="statusFilter"
            :options="[
              { label: '全部', value: 'all' },
              { label: '待审', value: 'todo' },
              { label: '未通过', value: 'invalid' },
              { label: '已审', value: 'done' },
            ]"
            block
          />
          <el-select
            v-if="!isFormal"
            v-model="disagreementFilter"
            aria-label="AI 分歧字段筛选"
          >
            <el-option label="全部分歧字段" value="any" />
            <el-option
              v-for="field in JUDGMENT_FIELDS"
              :key="field.key"
              :label="field.short"
              :value="field.key"
            />
          </el-select>
        </div>

        <div class="item-list">
          <button
            v-for="index in filteredIndices"
            :key="session.items[index].audit_item_id"
            type="button"
            class="item-row"
            :class="{ active: currentIndex === index, [itemState(index)]: true }"
            @click="selectIndex(index)"
          >
            <span class="item-number">{{ String(index + 1).padStart(3, "0") }}</span>
            <span class="item-summary">
              <strong>
                {{
                  isFormal
                    ? session.items[index].template_id.replace("marker:", "")
                    : disagreementNames(index)
                }}
              </strong>
              <small>
                {{
                  itemState(index) === "todo"
                    ? "等待判断"
                    : itemState(index) === "valid"
                      ? "五项通过"
                      : "至少一项未通过"
                }}
              </small>
            </span>
            <el-icon v-if="itemState(index) === 'valid'" class="state-icon">
              <CircleCheck />
            </el-icon>
            <span v-else-if="itemState(index) === 'invalid'" class="invalid-mark">!</span>
          </button>
          <el-empty
            v-if="filteredIndices.length === 0"
            description="当前筛选没有条目"
            :image-size="72"
          />
        </div>
      </aside>

      <section class="review-main">
        <div class="item-context">
          <div>
            <span class="item-position">条目 {{ currentIndex + 1 }} / {{ session.items.length }}</span>
            <h2>核对事件边界与时间关系</h2>
          </div>
          <div class="item-meta">
            <span>{{ activeItem.template_id.replace("marker:", "") }}</span>
            <code>{{ activeItem.audit_item_id.slice(-12) }}</code>
          </div>
        </div>

        <el-alert
          v-if="!isFormal"
          title="请先独立阅读语句，再参考 AI-A 与 AI-B 的分歧。"
          type="warning"
          :closable="false"
          show-icon
        />

        <QueryComparison :item="activeItem" />

        <nav class="item-navigation" aria-label="前后审核条目">
          <el-button
            :icon="ArrowLeft"
            :disabled="previousIndex === null"
            @click="selectIndex(previousIndex)"
          >
            上一条
          </el-button>
          <span v-if="isComplete(activeJudgment)" class="current-complete">
            <el-icon><Check /></el-icon>
            当前条目已完成
          </span>
          <span v-else class="current-pending">
            还需完成
            {{
              JUDGMENT_FIELDS.filter(
                (field) => typeof activeJudgment[field.key] !== "boolean",
              ).length
            }}
            项
          </span>
          <el-button
            type="primary"
            :disabled="nextIndex === null"
            @click="selectIndex(nextIndex)"
          >
            下一条
            <el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </nav>
      </section>

      <div class="judgment-column">
        <JudgmentPanel
          :model="activeJudgment"
          :ai-a="activeAiA"
          :ai-b="activeAiB"
          :locked="locked"
          @field="updateField"
          @notes="updateNotes"
        />
      </div>
    </div>

    <el-dialog
      v-model="receipt"
      title="结果已生成"
      width="min(560px, 92vw)"
      :close-on-click-modal="false"
    >
      <div v-if="receipt" class="receipt">
        <div class="receipt-icon"><el-icon><FolderOpened /></el-icon></div>
        <p>
          {{
            receipt.method === "results-folder"
              ? "结果文件和校验文件已经写入 results 文件夹。"
              : "结果文件已下载。请把两个文件移动到 src/ab-reviewer-web/results。"
          }}
        </p>
        <dl>
          <div>
            <dt>文件名</dt>
            <dd>{{ receipt.fileName }}</dd>
          </div>
          <div>
            <dt>记录数</dt>
            <dd>{{ receipt.count }}</dd>
          </div>
          <div>
            <dt>字节数</dt>
            <dd>{{ receipt.bytes }}</dd>
          </div>
          <div>
            <dt>SHA256</dt>
            <dd><code>{{ receipt.digest }}</code></dd>
          </div>
        </dl>
        <el-alert
          v-if="isFormal"
          title="请保留 JSONL 与 .sha256 文件，并在 A/B 都锁定后再进行比较。"
          type="success"
          :closable="false"
          show-icon
        />
      </div>
      <template #footer>
        <el-button type="primary" @click="receipt = null">完成</el-button>
      </template>
    </el-dialog>
  </main>
</template>
