# Claude Code Independent AI Pre-Review Diagnostics

- date: 2026-07-24 CST
- schema: `gsm8k-relation-ai-pre-review-v1`
- status: `AI PRE-REVIEW ONLY / HUMAN REVIEW PENDING`
- branch: `experiment/reproduction-additional-evaluation`

## Nature of these results

Two independent Claude Code sub-agents (AI-A and AI-B) each reviewed the same
200 GSM8K relation-only audit items without reading each other's output, any
prior AI review, or any production Reviewer A/B template.

**These results DO NOT:**
- Replace formal human Reviewer A/B submissions
- Enter the D-035 production evaluator
- Compute human Cohen's kappa
- Unlock GSM8K LoRA production training

Until two human authors independently complete, lock, and adjudicate the real
audit, the project remains `HUMAN REVIEW PENDING` and production training is
blocked.

## Input

- `docs/ai-context/ai-reviews/manual-check/audit-items.jsonl`
- SHA256: `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`

## Outputs

| File | Lines | SHA256 |
|---|---|---|
| `reviewer-ai-a.jsonl` | 200 | `0bd7271f4fed23326ab116b5ebceafab0051a86158cb7b5df8723ec2ebf64bd6` |
| `reviewer-ai-b.jsonl` | 200 | `918d4519242b7d8d0494c27d50765fee01baf959268b079cad3a5b24a5255227` |

## Field-level agreement

| Field | Agree | Disagree | Agreement rate |
|---|---|---|---|
| event_spans_valid | 200 | 0 | 100.0% |
| original_relation_valid | 200 | 0 | 100.0% |
| counterfactual_relation_valid | 196 | 4 | 98.0% |
| rewrite_grammatical | 198 | 2 | 99.0% |
| non_target_content_preserved | 200 | 0 | 100.0% |
| overall_valid | 194 | 6 | 97.0% |

## Overall confusion matrix (overall_valid)

| | B=True | B=False |
|---|---|---|
| **A=True** | 194 | 5 |
| **A=False** | 1 | 0 |

- Observed agreement (Po): 0.9700
- Expected agreement (Pe): 0.9703
- AI-only diagnostic Cohen's kappa: -0.0084

## Disagreement items requiring human inspection

6 items have divergent `overall_valid` judgments:

| Line | A | B | A notes | B notes |
|---|---|---|---|---|
| 2 | True | False | — | tense-marker-mismatch |
| 6 | False | True | grammar-error | — |
| 81 | True | False | — | illogical-temporal-sequence |
| 99 | True | False | — | undefined-temporal-reference |
| 119 | True | False | — | incomplete-temporal-bounds |
| 198 | True | False | — | contradictory-temporal-condition |

## Priority for human review

1. **Line 2 and Line 6**: grammar disagreements — verify whether the counterfactual rewrites are truly ungrammatical or acceptable variations.
2. **Lines 81, 99, 119, 198**: AI-B flagged counterfactual-relation validity issues that AI-A did not. These require human judgment on whether the temporal relations are genuinely illogical or semantically acceptable.
3. **event_spans_valid**: both agents agree 200/200, suggesting span annotations are reliable.

## User resolution of the six AI disagreements

On 2026-07-25, the user reviewed all six divergent fields in source order.
The locked decisions are stored in `user-disagreement-resolutions.jsonl`; they
do not modify either AI output and are not a formal Reviewer A/B submission.
The resolution file SHA256 is
`77087c1e9a077f3b37ed068d92539df27d1c30c442831b85b0df15b47f0c0c48`.

| Line | Field | Resolved value |
|---:|---|---|
| 2 | `rewrite_grammatical` | `false` |
| 6 | `rewrite_grammatical` | `false` |
| 81 | `counterfactual_relation_valid` | `false` |
| 99 | `counterfactual_relation_valid` | `false` |
| 119 | `counterfactual_relation_valid` | `true` |
| 198 | `counterfactual_relation_valid` | `true` |

These are user checks of AI disagreements only. The independent human audit
required by D-035 remains pending.
