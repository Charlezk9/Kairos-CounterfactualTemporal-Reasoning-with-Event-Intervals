import { describe, expect, it } from "vitest";
import {
  JUDGMENT_FIELDS,
  blankJudgment,
  buildFormalPayload,
  canonicalJson,
  directSourceNames,
  overallValue,
  resultFilename,
  safeNickname,
  sha256Bytes,
  timestampForFilename,
} from "./audit.js";

describe("canonical audit output", () => {
  it("sorts object keys recursively", () => {
    expect(canonicalJson({ z: 1, a: { c: true, b: null } })).toBe(
      '{"a":{"b":null,"c":true},"z":1}',
    );
  });

  it("computes overall as the conjunction of five judgments", () => {
    const value = blankJudgment();
    JUDGMENT_FIELDS.forEach((field) => {
      value[field.key] = true;
    });
    expect(overallValue(value)).toBe(true);
    value.rewrite_grammatical = false;
    expect(overallValue(value)).toBe(false);
  });

  it("exports formal rows without nickname or timestamp fields", () => {
    const item = { audit_item_id: "human-audit-item:test" };
    const session = {
      items: [item],
      slot: "A",
      nickname: "研究者",
      mode: "formal",
    };
    const value = blankJudgment();
    JUDGMENT_FIELDS.forEach((field) => {
      value[field.key] = true;
    });
    value.notes = "checked";
    const payload = buildFormalPayload(session, {
      [item.audit_item_id]: value,
    });
    expect(payload.endsWith("\n")).toBe(true);
    const row = JSON.parse(payload);
    expect(row.schema_version).toBe("gsm8k-relation-human-review-v1");
    expect(row.reviewer_slot).toBe("A");
    expect(row.overall_valid).toBe(true);
    expect(row).not.toHaveProperty("nickname");
    expect(row).not.toHaveProperty("timestamp");
  });

  it("uses time and a filesystem-safe nickname in result names", () => {
    const date = new Date(2026, 6, 24, 19, 8, 9, 12);
    expect(timestampForFilename(date)).toBe("20260724-190809-012");
    expect(safeNickname('  审核者: A/B  ')).toBe("审核者-A-B");
    expect(
      resultFilename(
        { mode: "formal", slot: "B", nickname: '审核者: A/B' },
        date,
      ),
    ).toBe("20260724-190809-012_审核者-A-B_formal-B.jsonl");
  });

  it("produces a lowercase SHA256 digest", async () => {
    await expect(sha256Bytes("abc")).resolves.toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("links Reviewer A directly to the frozen item and template names", () => {
    expect(directSourceNames("formal", "A")).toEqual([
      "audit-items.jsonl",
      "reviewer-a-template.jsonl",
    ]);
  });
});
