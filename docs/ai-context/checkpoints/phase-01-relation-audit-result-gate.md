# Phase 01 Relation Audit Result Gate Checkpoint

## Status

`COMPLETE / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY / HUMAN REVIEW PENDING`

- frozen parent: `6800c4123a77554da520e7413984af4c609ccdbe`
- contract commit: `fbf7de2bff1d680d4d650d503637631adce73843`
- implementation commit: `832e755fbdee9dcff5977142ad0cf7ba29b60399`
- formal audit result IDs: none
- production artifacts: none

This checkpoint implements D-035 only. It did not read, copy, modify or fill the
production audit packet or its blank Reviewer A/B templates. It does not make
human judgments, perform adjudication, publish a production result or authorize
candidate generation, a training plan or model training.

## Strict input contract

`kairos.relation_audit_results.evaluate_audit_submissions` accepts only an
already verified ordered sequence of exactly 200 audit item IDs, the packet and
items SHA256 bindings, and three caller-supplied immutable byte payloads. It
does not accept paths and cannot fall back to a template or production file.

Reviewer A and B must each provide exactly 200 LF-terminated canonical UTF-8
JSON objects in the expected order and slot. Duplicate keys, non-finite values,
missing or extra fields, invalid IDs, reordered records and non-Boolean review
values fail closed. The existing literal schema is
`gsm8k-relation-human-review-v1`; D-035's earlier generic review-schema label
does not introduce a second format. `overall_valid` must equal the conjunction
of event-span, original-relation, counterfactual-relation, grammaticality and
non-target preservation judgments. Notes are validated but never copied to the
result.

Authors' adjudication uses a separate exact schema. When reviewers agree, the
adjudicated value must preserve that agreement. Only a disagreement may be
resolved by the human authors. The program validates this invariant; it does
not select an answer or produce adjudication content.

## Statistics and immutable result

The evaluator computes the overall-valid 2x2 reviewer confusion matrix,
observed and expected agreement, Cohen's kappa and raw agreement for all six
fields. If expected agreement is one, kappa is unavailable and the gate fails.
Otherwise the kappa threshold is inclusive at 0.80. Adjudicated validity is the
true count divided by 200 and its threshold is inclusive at 0.95. Both
conditions must pass.

The canonical-compatible result binds packet, items, Reviewer A, Reviewer B
and adjudication SHA256 values. It contains only aggregate counts/rates,
thresholds and gate status, with no sample text or notes. Nested mappings are
deeply read-only so the returned value and its semantic SHA cannot be mutated
through a retained mapping reference.

## Verification

- focused: 5/5 in 0.382 seconds
- final full repository: 565/565 in 17.876 seconds
- environment: fixed project Conda, GPU hidden, CPU math threads two
- formal run or artifact: none

Synthetic coverage includes a passing 0.95-validity case, exact inclusive
kappa 0.80, finite low kappa, undefined kappa, low validity, reviewer order and
slot binding, malformed Boolean and overall fields, duplicate/extra JSON keys,
bad SHA bindings, forbidden changes to reviewer agreement and nested-result
immutability. No fixture contains a production sample, ID, review or note.

## Remaining boundary

Both production reviewer templates are still entirely null. Consequently no
real kappa, validity or gate status exists. Two human authors must independently
complete and lock A/B submissions, then human authors must adjudicate only the
disagreements. Production ingestion and immutable result publication require a
new frozen decision after those files exist. Until that later result passes,
production candidate generation, training-plan publication and Kairos,
Pair-MLP or Same-data SFT training remain prohibited.
