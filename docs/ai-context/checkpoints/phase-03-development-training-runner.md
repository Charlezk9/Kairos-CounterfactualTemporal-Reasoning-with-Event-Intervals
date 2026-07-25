# Phase 03 Development Training Runner

## Status

`IMPLEMENTED / CPU TESTED / INDEPENDENT IMPLEMENTATION AUDIT APPROVED / REAL RUN SUPERSEDED`

This checkpoint records implementation readiness only. No production run-input,
training plan, checkpoint or training metric was created while the repository
was dirty.

## Frozen execution path

`kairos.production_training` replays the fixed development data, immutable
candidate pool, prompt/protocol files and local model checksums. It publishes a
manifest-last run-input v2, builds the deterministic seed-13 plan, and runs
micro-batch 1 with gradient accumulation 32 for 31 optimizer steps. Immutable
checkpoints are required at steps 5, 10, 15, 20, 25, 30 and 31. Training and
finalization are separate foreground processes so finalization can prove that
the selected GPU was released before writing post-resource evidence and the
completion manifest.

Each attempt uses a caller-supplied immutable run namespace plus a separate
canonical experiment ID. A failure before step 5 leaves evidence but does not
prevent a from-zero retry under a new run ID. Each train/resume attempt requires
a no-replace resource gate whose signed `gate_id` equals that run ID; it cannot
reuse the run-input gate, another run's gate, the same payload hash or a record
older than 15 minutes. Resume is only from an explicit checkpoint into a fresh
run. Every checkpoint has an immutable trace-prefix receipt; recursive ancestry
binds source config, plan, run-input, attempt gate, checkpoint, receipt and
parent ancestry. Finalization cross-checks every receipt against the exact
full-trace prefix and publishes the completion manifest last.

D-043 is implemented through an explicit train-only API. The default D-034 API
still rejects empty generated pools. The exceptional API creates one original
gold candidate only for an empty train pool and records `gold_injected=true`;
internal-dev remains fail-closed. The production replay binds the exact count
three and ordered pair-ID SHA256
`22b4edc8c53acf2971d1d618da17388ea34c759188fab4b32ed41f384d22161a`.

## Verification before commit

- `git diff --check`: pass.
- Python bytecode compilation: pass.
- focused materialization/runner tests: 21/21 pass.
- complete GPU-hidden CPU suite: 594/594 pass in 19.103 seconds.
- strict read-only implementation audit: `APPROVED_IMPLEMENTATION`, no P0/P1.
- production artifacts created: none.
- GPU/model loaded: no.

Real-record materialization, one-step GPU smoke and the complete 31-step run
subsequently executed from synchronized clean commit `416dbd773144...` and
passed fresh replay. The authoritative execution evidence is
`phase-03-first-development-training.md`. Every resulting artifact remains
fixed to `DEVELOPMENT / INTERNAL-DEV / NOT PAPER-ELIGIBLE`; missing two-human
independence provenance is not upgraded by the successful run.
