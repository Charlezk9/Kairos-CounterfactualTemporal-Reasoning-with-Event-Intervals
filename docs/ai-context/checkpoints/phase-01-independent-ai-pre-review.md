# Phase 01 Independent AI Pre-review Checkpoint

## Status

`COMPLETE / AI PRE-REVIEW ONLY / HUMAN REVIEW PENDING`

- contract commit: `023490ee2fb821399961aa9fbbb97082d76c5c3a`
- source items SHA256: `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`
- source instructions SHA256: `8ee14494cded53ee8d523521e7f31b2b80cb21faef8da498f5b6812437e51038`
- sample size: 200
- summary SHA256: `fb058e64cb634a60a6ac56ff002ed45153b4e53c6107a360e4b8d0fcb203a5a4`
- formal human audit result: none

The user requested two independently spawned agents to fill review judgments
and stated that the user would inspect their accuracy. D-036 isolates these as
AI pre-reviews: they do not modify or copy the production Reviewer A/B
templates, are rejected by the D-035 human-review schema, and cannot authorize
training.

## Independence and outputs

AI-A and AI-B received the same immutable audit-items and instructions paths,
distinct output paths and an explicit prohibition on reading the other output.
Each agent reported compliance and performed its own schema/order validation.
The main agent did not inspect either partial output and read both only after
both agents had completed.

| Slot | File | SHA256 | Overall true | Non-null notes |
|---|---|---|---:|---:|
| AI-A | `../ai-reviews/reviewer-ai-a.jsonl` | `efaf43bb0439218b8584f8459d83dce1f6873d1fd86e945a518f8b9ae8916b9b` | 115 | 85 |
| AI-B | `../ai-reviews/reviewer-ai-b.jsonl` | `a579fd69768927f37f40b8f8c2c0823cf3944bc5d0ce58fe23e15f4a3640e524` | 174 | 0 |

Both files have exactly 200 LF-terminated canonical JSON objects, preserve the
source item ID and order, use true Boolean fields, and satisfy
`overall_valid=AND(first five fields)`. Their exact schema contains no source
question, answer, event text or pair ID. AI-A's notes use only five abstract
failure labels; AI-B has no notes.

## Agreement diagnostic

| Field | Agreement | Rate | Disagreements |
|---|---:|---:|---:|
| Event spans | 139 | 69.5% | 61 |
| Original relation | 197 | 98.5% | 3 |
| Counterfactual relation | 196 | 98.0% | 4 |
| Rewrite grammaticality | 185 | 92.5% | 15 |
| Non-target preservation | 200 | 100.0% | 0 |
| Overall valid | 137 | 68.5% | 63 |

Overall confusion is both true 113, AI-A true/AI-B false 2, AI-A false/AI-B
true 61 and both false 24. Observed agreement is 0.685, expected agreement is
0.5555 and the AI-only diagnostic Cohen's kappa is
`0.2913385826771655`.

This low agreement is a retained reliability warning, especially for event
span boundaries. The main agent did not adjudicate or modify any item. The
next action belongs to the user: inspect both files and determine which
judgments are accurate. The original human Reviewer A/B templates remain null,
so D-035 and all production training remain blocked.
