# Phase 01 Relation-only Human-audit Packet

- status: `COMPLETE / PACKET VERIFIED / HUMAN REVIEW PENDING`
- implementation_and_execution_commit: `6f56fcb31b07d0c2be095a4aa7d4ea69e2be72cb`
- branch: `experiment/reproduction-additional-evaluation`
- artifact_id: `AUDIT-P01-GSM8K-RELATION-ONLY-200-20260723`
- active_run_ids: none

## Frozen sampling and review contract

The population is the 370-record verified official-train relation-only artifact
with JSONL/manifest SHA256 `525e3b09...` / `4e22ff13...`. Sampling uses seed
20260723 and `stratified-hamilton-sha256-rank-v1`: strata are
`(template_id, original_relation)`, Hamilton largest-remainder allocation is
proportional to population size, and within-stratum selection plus presentation
order use separate SHA256 ranks. Pair IDs are unique and the official test split
is absent from the layout and CLI.

Two templates are created with reviewer slots A/B. All six judgement fields and
notes are exactly null. Reviewers must work independently and cannot modify the
immutable templates in place. Each reviewer assesses event spans, original
relation, counterfactual relation, grammar, non-target preservation and
`overall_valid`; overall must be the logical AND of the first five fields.

After both submissions are hash-locked, primary agreement is Cohen's kappa on
`overall_valid` with threshold 0.80. Disagreements require author consensus;
post-consensus valid rate must be at least 95%. Failing either threshold requires
a revised constructor and a new non-reused audit sample. AI judgement cannot
fill or replace the human fields.

## Development verification

`kairos.relation_human_audit` verifies and replays the complete source artifact,
constructs the deterministic packet, publishes four files followed by a
manifest, and later reconstructs every byte. It enforces no-replace, mode
0700/0600, nlink 1, exact namespace and clean Git gates.

- audit-focused tests: 7/7 passed;
- combined relation schema/artifact/audit tests: 23/23 passed in 0.440 seconds;
- final repository suite: 501/501 passed in 15.366 seconds;
- GPU hidden, CPU threads 2, cache/temp project-local.

## Production packet

Before publication Git was clean at `6f56fcb...`, target state was `ABSENT`,
`/data0` had 155 GiB free and memory had 229 GiB available. Existing VLLM
workers on GPUs 1/2/3/6 were not touched; this task used no GPU.

| Stratum | Population | Sample |
|---|---:|---:|
| `marker:after->before|follows` | 259 | 140 |
| `marker:before->after|precedes` | 111 | 60 |

Artifact files and SHA256:

- `audit-items.jsonl`: 200 records, 293,380 bytes,
  `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`;
- reviewer A template: 200 records,
  `3a2618b962ea67df6629d13021480466537afc03b4df9b6864df31117b9812f8`;
- reviewer B template: 200 records,
  `390e7cb5233907fe31910b0619a35e79711e48592f3f9455509ec518c56fd5b7`;
- instructions: `8ee14494cded53ee8d523521e7f31b2b80cb21faef8da498f5b6812437e51038`;
- manifest: `da5d7fb0659e1bb13aa1d6b03e59e83c5ddb42c05535932313552af7dcc19ecb`.

Target:
`/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/human-audit-v1/explicit-marker-relation-only-v1/train`.
A fresh process reproduced the manifest and all output hashes. This is only an
audit packet: kappa, validity, adjudication and model-training permission remain
unavailable until two human authors complete the forms.

## Next gate

Human reviewers must copy and independently complete the templates. While that
external step is pending, implementation may continue only on experiments that
do not consume this unapproved training artifact, beginning with the frozen
TORQUE Self-Consistency prompt baseline.
