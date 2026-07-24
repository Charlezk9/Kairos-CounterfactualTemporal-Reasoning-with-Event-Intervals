# Phase 03 Deterministic Training Plan Checkpoint

## Status

`COMPLETE / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`

- frozen parent: `6a3f18ef1839dcdcf19c58593d809c07eb37f866`
- contract commit: `d592e5cb549c52a0b9c96f42d55f69265d0bb6bc`
- implementation commit: `8de516d8b9c3fdb1804b5a7143f55c8cc29fc19a`
- formal run IDs: none
- production artifacts: none

This checkpoint implements D-031 only. It did not read production records,
candidate predictions or model files, did not use a GPU, and does not unlock
training while the D-023 two-person audit remains incomplete.

## Implemented contract

`kairos.training_plan` binds the clean execution commit, dataset revision,
source artifact ID/manifest hash and immutable source-order examples. Each
example binds its source/original/counterfactual identities, canonical record
hash, exact candidate content hashes and ordered generation origins, gold-answer
hash, target index and whether gold was appended. Duplicate candidate content,
misordered provenance, stale candidate IDs and invalid gold injection fail
closed.

For seeds 13, 42 and 2026, each of three epochs is independently ordered by a
canonical SHA256 rank over corpus hash, seed, epoch, source index and example
ID. Every real example appears exactly once per epoch. The concatenated order
is padded only to the next effective batch of 32 with a separately ranked,
explicit `repeat_padding` suffix; no sample is silently dropped and the suffix
is bounded to 0--31 slots.

The canonical manifest lists all real/repeat slots and every micro-batch's
optimizer step, accumulation position, example IDs and candidate IDs. Parsing
rebuilds the full plan from the corpus, seed and micro-batch size and requires
canonical exact equality. The manifest SHA is validated as the D-029 checkpoint
data identity and internally retains the source manifest binding.

The cursor is optimizer-boundary-only and records total/real/repeat consumed
slots, completed epochs and the exact next example/source/epoch. Planned
execution validates the requested window's example/candidate IDs, candidate
mask and answer targets before invoking the optimizer executor. Only the active
window is dereferenced, avoiding eager materialization of all three epochs.

## Verification

- focused final: 7/7 in 0.904 seconds
- full repository: 540/540 in 17.853 seconds
- full wall time: 21.47 seconds
- maximum RSS: 537,360 KiB
- environment: project Conda, GPU hidden, CPU math threads fixed to two

Coverage includes generated-gold versus appended-gold rules, source-order and
identity uniqueness, seed determinism, exact three-epoch coverage, a 31-slot
tail case, a divisible no-tail case, manifest round trip/tampering, checkpoint
data binding, cursor tampering, and pre-execution batch/target identity checks.

The first focused command failed during test-module import because the wrapper
referenced a nonexistent executor alias. No test body, data or model ran. It was
corrected to the existing `run_optimizer_steps` interface before the successful
focused and full runs above.

## Remaining boundary

Candidate generation/token materialization, immutable production training-plan
publication and the formal training runner remain incomplete. More importantly,
both human review templates are still blank, so kappa/validity are unavailable
and no Kairos, Pair-MLP or Same-data SFT production training may start. The next
unblocked reviewer-facing implementation target is the gold-free
Rule-Graph/Constraint-Rerank structured baseline; this checkpoint itself adds
no paper metric.
