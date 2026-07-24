# AI-A/AI-B Manual Accuracy Check

This user-requested review bundle contains 200 public-train audit items and a
line-aligned comparison template for manually checking the two AI pre-reviews.

- `audit-items.jsonl`: immutable source items; SHA256
  `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`.
- `reviewer-ab-template.jsonl`: AI-A and AI-B judgments plus an all-null
  `human_reference`; SHA256
  `fe2172561caea41591e60cb0e7721b8e1cc1addbe154af351c2fcc6f460bae45`.

The two files have exactly 200 records in the same order. Fill only the seven
fields nested under `human_reference`; keep item IDs, AI judgments and schema
unchanged. This combined file is for accuracy checking, not an independent
human Reviewer A/B submission and not a D-035 training-gate artifact.
