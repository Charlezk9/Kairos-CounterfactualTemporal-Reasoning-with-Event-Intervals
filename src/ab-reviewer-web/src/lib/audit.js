export const AUDIT_ITEM_SCHEMA = "gsm8k-relation-human-audit-item-v1";
export const FORMAL_REVIEW_SCHEMA = "gsm8k-relation-human-review-v1";
export const AI_REVIEW_SCHEMA = "gsm8k-relation-ai-pre-review-v1";
export const AI_CHECK_SCHEMA = "gsm8k-relation-ai-disagreement-human-check-v1";
export const EXPECTED_ITEM_COUNT = 200;

export const EXPECTED_HASHES = Object.freeze({
  auditItems: "0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113",
  formalA: "3a2618b962ea67df6629d13021480466537afc03b4df9b6864df31117b9812f8",
  formalB: "390e7cb5233907fe31910b0619a35e79711e48592f3f9455509ec518c56fd5b7",
  aiA: "efaf43bb0439218b8584f8459d83dce1f6873d1fd86e945a518f8b9ae8916b9b",
  aiB: "a579fd69768927f37f40b8f8c2c0823cf3944bc5d0ce58fe23e15f4a3640e524",
});

export const DIRECT_SOURCE_NAMES = Object.freeze({
  auditItems: "audit-items.jsonl",
  formalA: "reviewer-a-template.jsonl",
  formalB: "reviewer-b-template.jsonl",
  aiA: "reviewer-ai-a.jsonl",
  aiB: "reviewer-ai-b.jsonl",
});

export const JUDGMENT_FIELDS = Object.freeze([
  {
    key: "event_spans_valid",
    short: "事件跨度",
    question: "两条语句中标出的事件边界都准确且完整吗？",
    guide:
      "事件应包含必要的主语、动作和对象，不多含时间连接词，也不遗漏理解事件所需的核心成分。原句与反事实句都必须正确。",
  },
  {
    key: "original_relation_valid",
    short: "原关系",
    question: "原始语句中的两个事件确实满足系统给出的时间关系吗？",
    guide:
      "按“事件 A 相对于事件 B”的固定方向判断，只依据原始语句，不依据常识补充未写出的时间信息。",
  },
  {
    key: "counterfactual_relation_valid",
    short: "反事实关系",
    question: "反事实语句中的两个事件确实满足系统给出的时间关系吗？",
    guide:
      "按“事件 A 相对于事件 B”的固定方向判断。关系应与反事实语句一致，并且是原关系的目标反转。",
  },
  {
    key: "rewrite_grammatical",
    short: "语法通顺",
    question: "反事实语句语法通顺、结构完整且语义可理解吗？",
    guide:
      "若出现残缺成分、错误搭配、重复连接词、标点破坏或读者无法自然理解的表达，应选择“否”。",
  },
  {
    key: "non_target_content_preserved",
    short: "内容保持",
    question: "除目标时间关系外，反事实语句是否保持了原句的其他内容？",
    guide:
      "人物、数量、动作、对象和其他条件都应保持不变。只允许目标时间连接词及其必要语法形式发生变化。",
  },
]);

const ITEM_KEYS = [
  "audit_item_id",
  "counterfactual_events",
  "counterfactual_query",
  "original_events",
  "original_query",
  "pair_id",
  "proposed_counterfactual_relation",
  "proposed_original_relation",
  "schema_version",
  "stratum",
  "template_id",
];

const REVIEW_KEYS = [
  "audit_item_id",
  "counterfactual_relation_valid",
  "event_spans_valid",
  "non_target_content_preserved",
  "notes",
  "original_relation_valid",
  "overall_valid",
  "reviewer_slot",
  "rewrite_grammatical",
  "schema_version",
];

const RELATIONS = new Set([
  "precedes",
  "follows",
  "overlaps",
  "contains",
  "during",
]);

function fail(message) {
  throw new Error(message);
}

export function directSourceNames(mode, slot) {
  if (mode === "formal") {
    if (!["A", "B"].includes(slot)) fail("正式审核槽位必须是 A 或 B。");
    return [
      DIRECT_SOURCE_NAMES.auditItems,
      slot === "A" ? DIRECT_SOURCE_NAMES.formalA : DIRECT_SOURCE_NAMES.formalB,
    ];
  }
  if (mode === "ai-check") {
    return [
      DIRECT_SOURCE_NAMES.auditItems,
      DIRECT_SOURCE_NAMES.aiA,
      DIRECT_SOURCE_NAMES.aiB,
    ];
  }
  fail("未知的审核模式。");
}

async function fetchDirectFile(name) {
  const url = new URL(`./${name}`, document.baseURI);
  let response;
  try {
    response = await fetch(url, { cache: "no-store" });
  } catch {
    fail(`无法读取固定审核文件 ${name}。请确认 review-data 目录与本地服务可用。`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok || contentType.includes("text/html")) {
    fail(`未找到固定审核文件 review-data/${name}。`);
  }
  return new File([await response.arrayBuffer()], name, {
    type: "application/x-ndjson",
  });
}

export async function loadDirectAuditSession({ mode, nickname, slot }) {
  const names = directSourceNames(mode, slot);
  const files = await Promise.all(names.map(fetchDirectFile));
  return loadAuditSession({ files, mode, nickname, slot });
}

function sortedKeys(value) {
  return Object.keys(value).sort();
}

function assertExactKeys(value, expected, label) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    JSON.stringify(sortedKeys(value)) !== JSON.stringify([...expected].sort())
  ) {
    fail(`${label} 的字段集合与冻结协议不一致。`);
  }
}

function assertBooleanOrNull(value, label) {
  if (value !== null && typeof value !== "boolean") {
    fail(`${label} 必须是布尔值或 null。`);
  }
}

function validateEvent(event, query, label) {
  assertExactKeys(event, ["char_span", "event_id", "text"], label);
  assertExactKeys(event.char_span, ["end", "start"], `${label} 的字符范围`);
  const { start, end } = event.char_span;
  if (
    typeof event.event_id !== "string" ||
    !event.event_id ||
    typeof event.text !== "string" ||
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end <= start ||
    end > query.length ||
    query.slice(start, end) !== event.text
  ) {
    fail(`${label} 无法与语句中的字符范围严格对齐。`);
  }
}

function validateItems(rows) {
  if (rows.length !== EXPECTED_ITEM_COUNT) {
    fail(`审核条目必须恰好为 ${EXPECTED_ITEM_COUNT} 条，当前为 ${rows.length} 条。`);
  }
  const ids = new Set();
  rows.forEach((row, index) => {
    const label = `审核条目 ${index + 1}`;
    assertExactKeys(row, ITEM_KEYS, label);
    if (
      row.schema_version !== AUDIT_ITEM_SCHEMA ||
      typeof row.audit_item_id !== "string" ||
      !row.audit_item_id.startsWith("human-audit-item:") ||
      typeof row.pair_id !== "string" ||
      typeof row.stratum !== "string" ||
      typeof row.original_query !== "string" ||
      !row.original_query ||
      typeof row.counterfactual_query !== "string" ||
      !row.counterfactual_query ||
      typeof row.template_id !== "string" ||
      !RELATIONS.has(row.proposed_original_relation) ||
      !RELATIONS.has(row.proposed_counterfactual_relation)
    ) {
      fail(`${label} 的身份、语句或关系字段无效。`);
    }
    if (ids.has(row.audit_item_id)) {
      fail(`${label} 的 audit_item_id 重复。`);
    }
    ids.add(row.audit_item_id);
    if (
      !Array.isArray(row.original_events) ||
      row.original_events.length !== 2 ||
      !Array.isArray(row.counterfactual_events) ||
      row.counterfactual_events.length !== 2
    ) {
      fail(`${label} 必须各包含两个原始事件和两个反事实事件。`);
    }
    row.original_events.forEach((event, eventIndex) =>
      validateEvent(event, row.original_query, `${label} 原始事件 ${eventIndex + 1}`),
    );
    row.counterfactual_events.forEach((event, eventIndex) =>
      validateEvent(
        event,
        row.counterfactual_query,
        `${label} 反事实事件 ${eventIndex + 1}`,
      ),
    );
  });
}

function validateReviewRows(rows, items, schema, slot, requireBlank) {
  if (rows.length !== items.length) {
    fail(`${slot} 审核表的条目数与审核语句不一致。`);
  }
  rows.forEach((row, index) => {
    const label = `${slot} 审核表第 ${index + 1} 行`;
    assertExactKeys(row, REVIEW_KEYS, label);
    if (
      row.schema_version !== schema ||
      row.reviewer_slot !== slot ||
      row.audit_item_id !== items[index].audit_item_id
    ) {
      fail(`${label} 的 schema、审核槽位或条目顺序不一致。`);
    }
    JUDGMENT_FIELDS.forEach((field) =>
      assertBooleanOrNull(row[field.key], `${label} 的 ${field.key}`),
    );
    assertBooleanOrNull(row.overall_valid, `${label} 的 overall_valid`);
    if (row.notes !== null && typeof row.notes !== "string") {
      fail(`${label} 的 notes 必须是字符串或 null。`);
    }
    if (typeof row.notes === "string" && [...row.notes].length > 1000) {
      fail(`${label} 的 notes 超过 1000 个 Unicode 字符。`);
    }
    if (requireBlank) {
      if (
        JUDGMENT_FIELDS.some((field) => row[field.key] !== null) ||
        row.overall_valid !== null ||
        row.notes !== null
      ) {
        fail(`${label} 不是冻结审核包中的空白模板。`);
      }
    } else {
      if (JUDGMENT_FIELDS.some((field) => typeof row[field.key] !== "boolean")) {
        fail(`${label} 的五项 AI 判断必须全部为布尔值。`);
      }
      const expectedOverall = JUDGMENT_FIELDS.every((field) => row[field.key]);
      if (row.overall_valid !== expectedOverall) {
        fail(`${label} 的 overall_valid 不是前五项判断的逻辑与。`);
      }
    }
  });
}

export function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("结果包含非有限数值。");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${sortedKeys(value)
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  fail("结果包含无法序列化的值。");
}

export async function sha256Bytes(value) {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function parseJsonl(text, label) {
  if (!text.endsWith("\n") || text.includes("\r")) {
    fail(`${label} 必须使用 LF 换行并以 LF 结束。`);
  }
  const lines = text.slice(0, -1).split("\n");
  if (lines.some((line) => !line)) {
    fail(`${label} 不能包含空行。`);
  }
  return lines.map((line, index) => {
    let value;
    try {
      value = JSON.parse(line);
    } catch {
      fail(`${label} 第 ${index + 1} 行不是有效 JSON。`);
    }
    if (canonicalJson(value) !== line) {
      fail(`${label} 第 ${index + 1} 行不是 canonical JSON。`);
    }
    return value;
  });
}

async function readInputFile(file) {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    fail(`${file.name} 不是严格 UTF-8 文件。`);
  }
  return {
    name: file.name,
    hash: await sha256Bytes(bytes),
    text,
  };
}

function pickFile(parsedFiles, predicate, label) {
  const matches = parsedFiles.filter(predicate);
  if (matches.length !== 1) {
    fail(`${label} 必须恰好提供一份，当前识别到 ${matches.length} 份。`);
  }
  return matches[0];
}

function parseCandidate(file) {
  if (!file.name.toLowerCase().endsWith(".jsonl")) return null;
  const rows = parseJsonl(file.text, file.name);
  return {
    ...file,
    rows,
    schema: rows[0]?.schema_version,
    slot: rows[0]?.reviewer_slot,
  };
}

export async function loadAuditSession({ files, mode, nickname, slot }) {
  if (!nickname.trim()) fail("请填写审核者昵称。");
  const parsedFiles = (await Promise.all(files.map(readInputFile)))
    .map(parseCandidate)
    .filter(Boolean);
  const itemFile = pickFile(
    parsedFiles,
    (file) => file.schema === AUDIT_ITEM_SCHEMA,
    "audit-items.jsonl",
  );
  if (itemFile.hash !== EXPECTED_HASHES.auditItems) {
    fail("audit-items.jsonl 的 SHA256 与冻结审核包不一致。");
  }
  validateItems(itemFile.rows);

  const session = {
    mode,
    nickname: nickname.trim(),
    slot: mode === "formal" ? slot : null,
    items: itemFile.rows,
    itemHash: itemFile.hash,
    sourceFiles: [itemFile.name],
    aiA: null,
    aiB: null,
    isDemo: false,
  };

  if (mode === "formal") {
    if (!["A", "B"].includes(slot)) fail("正式审核槽位必须是 A 或 B。");
    const template = pickFile(
      parsedFiles,
      (file) => file.schema === FORMAL_REVIEW_SCHEMA && file.slot === slot,
      `Reviewer ${slot} 空白模板`,
    );
    const expectedHash = slot === "A" ? EXPECTED_HASHES.formalA : EXPECTED_HASHES.formalB;
    if (template.hash !== expectedHash) {
      fail(`Reviewer ${slot} 模板的 SHA256 与冻结审核包不一致。`);
    }
    validateReviewRows(template.rows, itemFile.rows, FORMAL_REVIEW_SCHEMA, slot, true);
    session.sourceFiles.push(template.name);
  } else if (mode === "ai-check") {
    const aiA = pickFile(
      parsedFiles,
      (file) => file.schema === AI_REVIEW_SCHEMA && file.slot === "AI-A",
      "AI-A 预审结果",
    );
    const aiB = pickFile(
      parsedFiles,
      (file) => file.schema === AI_REVIEW_SCHEMA && file.slot === "AI-B",
      "AI-B 预审结果",
    );
    if (aiA.hash !== EXPECTED_HASHES.aiA || aiB.hash !== EXPECTED_HASHES.aiB) {
      fail("AI 预审文件的 SHA256 与冻结诊断记录不一致。");
    }
    validateReviewRows(aiA.rows, itemFile.rows, AI_REVIEW_SCHEMA, "AI-A", false);
    validateReviewRows(aiB.rows, itemFile.rows, AI_REVIEW_SCHEMA, "AI-B", false);
    session.aiA = aiA.rows;
    session.aiB = aiB.rows;
    session.sourceFiles.push(aiA.name, aiB.name);
  } else {
    fail("未知的审核模式。");
  }
  return session;
}

export function blankJudgment() {
  return {
    event_spans_valid: null,
    original_relation_valid: null,
    counterfactual_relation_valid: null,
    rewrite_grammatical: null,
    non_target_content_preserved: null,
    notes: "",
  };
}

export function isComplete(judgment) {
  return JUDGMENT_FIELDS.every((field) => typeof judgment?.[field.key] === "boolean");
}

export function overallValue(judgment) {
  if (!isComplete(judgment)) return null;
  return JUDGMENT_FIELDS.every((field) => judgment[field.key]);
}

export function disagreementFields(aiA, aiB) {
  return JUDGMENT_FIELDS.filter((field) => aiA[field.key] !== aiB[field.key]).map(
    (field) => field.key,
  );
}

export function buildFormalPayload(session, judgments) {
  const rows = session.items.map((item) => {
    const judgment = judgments[item.audit_item_id];
    if (!isComplete(judgment)) fail("仍有未完成条目，不能导出正式审核结果。");
    const notes = judgment.notes.trim();
    return {
      schema_version: FORMAL_REVIEW_SCHEMA,
      audit_item_id: item.audit_item_id,
      reviewer_slot: session.slot,
      event_spans_valid: judgment.event_spans_valid,
      original_relation_valid: judgment.original_relation_valid,
      counterfactual_relation_valid: judgment.counterfactual_relation_valid,
      rewrite_grammatical: judgment.rewrite_grammatical,
      non_target_content_preserved: judgment.non_target_content_preserved,
      overall_valid: overallValue(judgment),
      notes: notes || null,
    };
  });
  return `${rows.map(canonicalJson).join("\n")}\n`;
}

export function buildAiCheckPayload(session, judgments, indices) {
  const rows = indices.map((index) => {
    const item = session.items[index];
    const judgment = judgments[item.audit_item_id];
    if (!isComplete(judgment)) fail("仍有未完成的 AI 分歧核查条目。");
    return {
      schema_version: AI_CHECK_SCHEMA,
      audit_item_id: item.audit_item_id,
      item_position: index + 1,
      reviewer_nickname: session.nickname,
      disagreement_fields: disagreementFields(session.aiA[index], session.aiB[index]),
      ai_a: Object.fromEntries(
        JUDGMENT_FIELDS.map((field) => [field.key, session.aiA[index][field.key]]),
      ),
      ai_b: Object.fromEntries(
        JUDGMENT_FIELDS.map((field) => [field.key, session.aiB[index][field.key]]),
      ),
      human_check: {
        ...Object.fromEntries(
          JUDGMENT_FIELDS.map((field) => [field.key, judgment[field.key]]),
        ),
        overall_valid: overallValue(judgment),
        notes: judgment.notes.trim() || null,
      },
    };
  });
  return `${rows.map(canonicalJson).join("\n")}\n`;
}

export function safeNickname(value) {
  const safe = value
    .normalize("NFKC")
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[.-]+|[.-]+$/g, "")
    .slice(0, 40);
  return safe || "reviewer";
}

export function timestampForFilename(date = new Date()) {
  const parts = [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
    "-",
    String(date.getHours()).padStart(2, "0"),
    String(date.getMinutes()).padStart(2, "0"),
    String(date.getSeconds()).padStart(2, "0"),
    "-",
    String(date.getMilliseconds()).padStart(3, "0"),
  ];
  return parts.join("");
}

export function resultFilename(session, date = new Date()) {
  const purpose =
    session.mode === "formal" ? `formal-${session.slot}` : "ai-disagreement-check";
  return `${timestampForFilename(date)}_${safeNickname(session.nickname)}_${purpose}.jsonl`;
}

export function relationLabel(relation) {
  const labels = {
    precedes: "事件 A 发生在事件 B 之前",
    follows: "事件 A 发生在事件 B 之后",
    overlaps: "事件 A 与事件 B 在时间上重叠",
    contains: "事件 A 的时间范围包含事件 B",
    during: "事件 A 发生在事件 B 的时间范围内",
  };
  return labels[relation] || relation;
}

export function createDemoSession() {
  const items = [
    {
      schema_version: AUDIT_ITEM_SCHEMA,
      audit_item_id: "human-audit-item:demo-01",
      pair_id: "counterfactual-pair:demo-01",
      stratum: "marker:before->after|precedes",
      original_query: "Lin packed the samples before Mara sealed the container.",
      counterfactual_query: "Lin packed the samples after Mara sealed the container.",
      original_events: [
        { event_id: "E1", text: "Lin packed the samples", char_span: { start: 0, end: 22 } },
        {
          event_id: "E2",
          text: "Mara sealed the container",
          char_span: { start: 30, end: 55 },
        },
      ],
      counterfactual_events: [
        { event_id: "E1", text: "Lin packed the samples", char_span: { start: 0, end: 22 } },
        {
          event_id: "E2",
          text: "Mara sealed the container",
          char_span: { start: 29, end: 54 },
        },
      ],
      proposed_original_relation: "precedes",
      proposed_counterfactual_relation: "follows",
      template_id: "marker:before->after",
    },
    {
      schema_version: AUDIT_ITEM_SCHEMA,
      audit_item_id: "human-audit-item:demo-02",
      pair_id: "counterfactual-pair:demo-02",
      stratum: "marker:after->before|follows",
      original_query: "The second alarm rang after the technician restarted the panel.",
      counterfactual_query: "The second alarm rang before the technician restarted the panel.",
      original_events: [
        { event_id: "E1", text: "The second alarm rang", char_span: { start: 0, end: 21 } },
        {
          event_id: "E2",
          text: "the technician restarted the panel",
          char_span: { start: 28, end: 62 },
        },
      ],
      counterfactual_events: [
        { event_id: "E1", text: "The second alarm rang", char_span: { start: 0, end: 21 } },
        {
          event_id: "E2",
          text: "the technician restarted the panel",
          char_span: { start: 29, end: 63 },
        },
      ],
      proposed_original_relation: "follows",
      proposed_counterfactual_relation: "precedes",
      template_id: "marker:after->before",
    },
    {
      schema_version: AUDIT_ITEM_SCHEMA,
      audit_item_id: "human-audit-item:demo-03",
      pair_id: "counterfactual-pair:demo-03",
      stratum: "marker:before->after|precedes",
      original_query: "Nora wrote the report before dawn arrived.",
      counterfactual_query: "Nora wrote the report after dawn arrived.",
      original_events: [
        { event_id: "E1", text: "Nora wrote the report", char_span: { start: 0, end: 21 } },
        { event_id: "E2", text: "dawn arrived", char_span: { start: 29, end: 41 } },
      ],
      counterfactual_events: [
        { event_id: "E1", text: "Nora wrote the report", char_span: { start: 0, end: 21 } },
        { event_id: "E2", text: "dawn arrived", char_span: { start: 28, end: 40 } },
      ],
      proposed_original_relation: "precedes",
      proposed_counterfactual_relation: "follows",
      template_id: "marker:before->after",
    },
  ];
  const makeReview = (item, slot, values) => ({
    schema_version: AI_REVIEW_SCHEMA,
    audit_item_id: item.audit_item_id,
    reviewer_slot: slot,
    event_spans_valid: values[0],
    original_relation_valid: values[1],
    counterfactual_relation_valid: values[2],
    rewrite_grammatical: values[3],
    non_target_content_preserved: values[4],
    overall_valid: values.every(Boolean),
    notes: null,
  });
  const aiA = [
    makeReview(items[0], "AI-A", [false, true, true, true, true]),
    makeReview(items[1], "AI-A", [true, true, true, false, true]),
    makeReview(items[2], "AI-A", [true, true, true, true, true]),
  ];
  const aiB = [
    makeReview(items[0], "AI-B", [true, true, true, true, true]),
    makeReview(items[1], "AI-B", [true, true, true, true, true]),
    makeReview(items[2], "AI-B", [false, true, true, true, true]),
  ];
  return {
    mode: "ai-check",
    nickname: "演示审核者",
    slot: null,
    items,
    itemHash: "demo",
    sourceFiles: ["内置演示数据"],
    aiA,
    aiB,
    isDemo: true,
  };
}
