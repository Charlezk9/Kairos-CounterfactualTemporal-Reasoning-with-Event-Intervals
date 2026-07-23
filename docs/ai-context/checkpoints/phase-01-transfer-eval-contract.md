# Phase 01 Transfer-Evaluation Contract

- status: `COMPLETE / DEVELOPMENT_VERIFIED`
- implementation_commit: `e89bbfd5c13792e51f69ceb21b4525efcc30736b`
- effective_commit: `8b57ffeb007dfb6e51d218c85f53011cce364f6e`
- date: 2026-07-23 CST
- formal_model_run: none
- prediction_artifacts: none

## Implemented boundary

`src/kairos/transfer_eval.py` fixes the production paths, revisions and whole-file
SHA256 values for TORQUE public dev and TimeQA `human_test.hard`. Both adapters
are read-only, reject a changed file during reading, reject malformed/duplicate
JSON keys and enforce the observed nested schema. Unit tests use only synthetic
files under `/data0/hk_data/kairos-zx/.tmp`.

TORQUE answers are evaluated as normalized span sets. Normalization is Unicode
NFC, case folding and whitespace collapse; punctuation is not removed. Empty
gold/prediction sets score 1 for EM and F1. Contrast groups are keyed by the
pair `(passageID, cluster_id)`, because cluster IDs are only local. The primary
consistency metric is the percentage of groups in which every question has
set EM=1. The frozen sensitivity metric is the percentage in which every
question has set F1>=0.8.

TimeQA normalization and EM/token-F1 semantically reproduce the fixed upstream
`utils.py`: lowercase, delete ASCII punctuation, remove English articles,
collapse whitespace, and maximize each metric independently over gold targets.
The source contains legitimate empty-string targets, so the contract requires a
non-empty target list but permits empty target strings; official empty/empty EM
and F1 are both 1.

## Verification evidence

- focused synthetic suite: 13/13 passed
- full repository suite: 401/401 passed in 13.033 seconds
- GPU hidden; CPU threads fixed to 2; cache/temp stayed under `/data0`
- clean production read-only smoke on `8b57ffe...`:
  - TORQUE: 145 passages, 1,483 questions, 571 local contrast groups, 323 empty
    gold sets; answer cardinality 0--16
  - TimeQA-Hard: 989 unique IDs, 33,679 paragraphs, 1,046 targets; target
    cardinality 1/2/3 is 940/41/8; 159 records have one empty-string target
- repository remained clean and no output artifact was created

The first clean smoke attempt at `e89bbfd...` failed closed on an empty TimeQA
target before returning either dataset. The source-level aggregate confirmed
159 such records; the behavior was added to the synthetic contract and fixed in
`8b57ffe...` before the successful smoke check.

## Non-result boundary and next gate

This checkpoint verifies source parsing and metric semantics only. It generated
no model predictions, run ID, paper metric, checkpoint or GPU process. TORQUE
test remains prohibited because it has no answer field. Formal evaluation must
wait for a committed model-agnostic prediction JSONL/manifest contract that
binds clean execution commit, configuration, method, source revision, complete
record coverage and output SHA256.
