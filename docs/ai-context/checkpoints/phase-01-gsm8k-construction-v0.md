# Phase 01 GSM8K Construction v0 Production Result

- status: `COMPLETE / VERIFIED DATA ARTIFACT / ZERO_RETAINED`
- execution_commit: `3944bb56d5c16a11482de39c5f0295936b6ac035`
- driver_commit: `c8f5cecfccca1037a12660424ebcbc7a7dc70914`
- source_revision: `3101c7d5072418e28b9008a6636bde82a006892c`
- source_artifact: `PROC-P01-GSM8K-20260722`
- artifact_id: `PROC-P01-GSM8K-CONSTRUCTION-V0-20260723`
- model/GPU/network: none

## Production path

The fixed driver `kairos.gsm8k_construction` streams the already verified
canonical GSM8K examples through the real D-011 constructor, creates one D-012
typed audit record per source line, and passes that stream to the P2 immutable
publisher. It accepts only train/test plus a clean execution commit; it has no
arbitrary path and prints no record content.

The first train invocation from commit `c8f5cecf...` failed before target
creation because the initial P2 integration treated the acquisition completion
manifest as a single-link file. The target remained `ABSENT`. Commit
`3944bb56...` fixed the gate to require the actual fixed
`completion-manifest.json`/`completion-manifest.guard` same-inode `nlink=2`
pair and corrected a 63-character completion digest constant. No partial data
was created or removed. Focused tests then passed 10/10 and the clean full suite
passed 388/388 in 13.057 seconds.

## Verified construction statistics

| Split | Raw | Temporal filtered | Extraction success | Reliable relation | Valid CF | Retained |
|---|---:|---:|---:|---:|---:|---:|
| train | 7,473 | 1,845 | 370 | 370 | 0 | 0 |
| test | 1,319 | 361 | 79 | 79 | 0 | 0 |

Terminal counts:

| Split | no_marker | extraction_rejected | text_question_alias_unsupported | other terminals |
|---|---:|---:|---:|---:|
| train | 5,628 | 1,475 | 370 | 0 |
| test | 958 | 282 | 79 | 0 |

Every source ID, audit ID and record fingerprint is unique within each split.
The frozen v0 yields no valid counterfactuals because every canonical GSM8K
example has `text == question`; any successfully extracted relation reaches
the predeclared alias-safety terminal before rewriting. Numeric answers would
also require a task-specific, provable updater. This is a negative data-policy
result, not a model metric and not evidence against the paper's unavailable
author subset.

## Immutable artifact bindings

Root:

`/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/construction-audit-v1/explicit-marker-construction-v0`

| Split | Audit bytes | Audit SHA256 | Manifest SHA256 |
|---|---:|---|---|
| train | 13,619,058 | `a4b38dd3ba6b8b597732744af74b5e16fe464a98f2b8c1f6540fe04361cdb346` | `41edd3255de9e6b3c9f6df4a7d2ca9f05d6dc7ad33a65f2f7d3b044e8a15412f` |
| test | 2,420,430 | `14393b5e2c8aace358babaaf38e37bd2d4e8fcbcdd52452127b3bf49b9f6a4e4` | `dda773ba105b59eb5d4e27fe8ea4ea0dcc2b661b4c639a2d3cd2ba297f9a129c` |

An independent offline verifier replayed both artifacts after publication and
returned `STRUCTURALLY_VERIFIED`. Each split directory is 0700 and contains
exactly two 0600 single-link regular files. The repository remained clean and
equal to origin.

## Interpretation and next gate

Do not train on this zero-retained artifact and do not alter v0 after seeing
test statistics. Freeze a separately versioned construction v1 using only
train-side design evidence. It must define how one source distinguishes
context from question, how answer-changing numeric counterfactuals are
validated, and how at least 200 stratified examples are prepared for two-human
audit. Until that policy and audit pass, GSM8K counterfactual training is
blocked; remaining official datasets may proceed independently.
