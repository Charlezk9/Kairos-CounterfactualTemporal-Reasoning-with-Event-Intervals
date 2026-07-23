# Phase 01 Construction Audit Persistence (P2)

- status: `COMPLETE / DEVELOPMENT_VERIFICATION_PASSED`
- implementation_commit: `63737a3b0da741a5e4ee08ff32c2fd4b8dde7bc5`
- branch: `experiment/reproduction-additional-evaluation`
- production_run: none
- active_run_ids: none

## Scope

P2 adds immutable persistence for caller-supplied D-012
`ConstructionAuditRecord` streams. It does not call D-011, select a temporal
subset, download data, load a model, train, infer, or produce a paper metric.
The implementation is an independent reimplementation.

The fixed production source is GSM8K revision
`3101c7d5072418e28b9008a6636bde82a006892c`, bound through processed artifact
`PROC-P01-GSM8K-20260722` and manifest SHA256
`48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe`.
Train/test source counts are 7,473/1,319 and retain their physical source order.

## Interface and publication contract

`kairos.construction_audit_persistence` exposes:

- `publish(records, official_split, execution_commit)` for a new target;
- `verify(official_split)` for offline source/output replay;
- `observe(official_split)` for non-mutating publication-state classification;
- verify/observe CLI commands only. Construction is deliberately not hidden in
  the persistence CLI.

Targets are fixed below
`data/processed/gsm8k/<revision>/construction-audit-v1/explicit-marker-construction-v0/<split>`.
A completed target contains only mode-0600 `construction-audit.jsonl` and
`construction-audit-manifest.json` inside a mode-0700 directory. JSONL records
are exact D-012 canonical objects plus LF. Publication uses exclusive temporary
files, fsync, hardlink no-replace, temp unlink, and manifest-last completion.
Existing or partial targets are never overwritten, repaired, deleted, or
silently retried.

The publisher checks a clean, matching Git commit before target creation,
before manifest publication, and after replay verification. It binds the
processed manifest, source JSONL, acquisition completion, SHA256SUMS, formal
tree fingerprint and upstream LICENSE. The manifest records the source and
license provenance, execution commit, output SHA/bytes/count, unique identity
counts, all seven terminal counts, and the monotonic construction funnel.

The verifier re-parses every D-012 record, enforces zero-based contiguous
input order, checks source/audit/fingerprint uniqueness, compares every
embedded input to the corresponding bound source record, recomputes terminal
and funnel statistics, and requires an exact two-file directory. Audit payloads
contain source text and are therefore data-bearing; they are not logged or
tracked by Git.

## Verification evidence

Implementation and synthetic tests are exactly:

- `src/kairos/construction_audit_persistence.py`
- `tests/test_construction_audit_persistence.py`

The focused suite passed 8/8 tests. The full repository suite passed 381/381
in 13.234 seconds from clean commit `63737a3b0da741a5e4ee08ff32c2fd4b8dde7bc5`,
with GPU disabled, two CPU threads, offline model settings and project-local
cache/temp paths. Tests cover manifest-last publication, full replay,
no-replace, stream order/count failures, partial-state preservation, tamper
detection, observer states, commit/split validation and redacted CLI failures.
No production target, run ID, network access, model operation or experiment
metric was created.

## Next gate

Before production publication, add and verify a fixed GSM8K construction driver
that streams the existing processed examples through D-011, D-012 and this P2
API. The driver must run only from a clean commit and record both split
manifests in the processed-data registry. Because the current GSM8K adapter has
`text == question` and numeric answers, D-011 may legitimately retain zero
counterfactual pairs; that outcome must be reported as a frozen-policy result,
not tuned away after seeing test statistics.
