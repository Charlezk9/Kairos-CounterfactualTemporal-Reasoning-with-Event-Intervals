<script setup>
import { computed } from "vue";
import { ArrowRight, Connection } from "@element-plus/icons-vue";
import { relationLabel } from "../lib/audit.js";

const props = defineProps({
  item: { type: Object, required: true },
});

function segments(query, events) {
  const sorted = events
    .map((event, index) => ({ ...event, index }))
    .sort((left, right) => left.char_span.start - right.char_span.start);
  const output = [];
  let cursor = 0;
  for (const event of sorted) {
    if (event.char_span.start > cursor) {
      output.push({
        kind: "plain",
        text: query.slice(cursor, event.char_span.start),
        key: `plain-${cursor}`,
      });
    }
    output.push({
      kind: `event-${event.index + 1}`,
      text: query.slice(event.char_span.start, event.char_span.end),
      key: `event-${event.index}-${event.char_span.start}`,
      label: event.index === 0 ? "事件 A" : "事件 B",
    });
    cursor = event.char_span.end;
  }
  if (cursor < query.length) {
    output.push({ kind: "plain", text: query.slice(cursor), key: `plain-${cursor}` });
  }
  return output;
}

function changedParts(original, counterfactual) {
  let prefix = 0;
  while (
    prefix < original.length &&
    prefix < counterfactual.length &&
    original[prefix] === counterfactual[prefix]
  ) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < original.length - prefix &&
    suffix < counterfactual.length - prefix &&
    original[original.length - 1 - suffix] ===
      counterfactual[counterfactual.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  return {
    original: original.slice(prefix, original.length - suffix || undefined),
    counterfactual: counterfactual.slice(
      prefix,
      counterfactual.length - suffix || undefined,
    ),
  };
}

const originalSegments = computed(() =>
  segments(props.item.original_query, props.item.original_events),
);
const counterfactualSegments = computed(() =>
  segments(props.item.counterfactual_query, props.item.counterfactual_events),
);
const change = computed(() =>
  changedParts(props.item.original_query, props.item.counterfactual_query),
);
</script>

<template>
  <section class="query-comparison" aria-label="原始语句与反事实语句对照">
    <div class="query-card original">
      <div class="query-card-header">
        <span>原始语句</span>
        <code>{{ item.proposed_original_relation }}</code>
      </div>
      <p class="query-text">
        <template v-for="segment in originalSegments" :key="segment.key">
          <mark
            v-if="segment.kind !== 'plain'"
            :class="segment.kind"
            :aria-label="segment.label"
          >{{ segment.text }}</mark>
          <span v-else>{{ segment.text }}</span>
        </template>
      </p>
      <div class="relation-statement">
        <el-icon><Connection /></el-icon>
        <span>{{ relationLabel(item.proposed_original_relation) }}</span>
      </div>
    </div>

    <div class="change-column" aria-label="目标改写">
      <el-icon><ArrowRight /></el-icon>
      <span class="change-token old">{{ change.original }}</span>
      <span class="change-token next">{{ change.counterfactual }}</span>
    </div>

    <div class="query-card counterfactual">
      <div class="query-card-header">
        <span>反事实语句</span>
        <code>{{ item.proposed_counterfactual_relation }}</code>
      </div>
      <p class="query-text">
        <template v-for="segment in counterfactualSegments" :key="segment.key">
          <mark
            v-if="segment.kind !== 'plain'"
            :class="segment.kind"
            :aria-label="segment.label"
          >{{ segment.text }}</mark>
          <span v-else>{{ segment.text }}</span>
        </template>
      </p>
      <div class="relation-statement">
        <el-icon><Connection /></el-icon>
        <span>{{ relationLabel(item.proposed_counterfactual_relation) }}</span>
      </div>
    </div>

    <div class="event-legend">
      <span><i class="event-a-swatch"></i>事件 A</span>
      <span><i class="event-b-swatch"></i>事件 B</span>
      <span class="event-detail">
        A: {{ item.original_events[0].text }}
      </span>
      <span class="event-detail">
        B: {{ item.original_events[1].text }}
      </span>
    </div>
  </section>
</template>
