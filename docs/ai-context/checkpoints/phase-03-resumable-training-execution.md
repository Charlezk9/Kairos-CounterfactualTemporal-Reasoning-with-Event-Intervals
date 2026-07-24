# Phase 03 Resumable Synthetic Training Execution

- status: `COMPLETE / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`
- implementation_commit: `7772f7c0b83557c423456de62a3fd733781e3499`
- frozen_contract_commit: `9cb192e75c3c68a319235da3efb6cedfa21c1447`
- date: 2026-07-24 CST
- production data/model/GPU/network: none
- formal run/checkpoint: none

## Implemented contract

`kairos.training_execution` implements the D-028 CPU-testable execution layer:

- exact two-group AdamW: trainable backbone `lora_` parameters at `2e-5` and
  temporal core parameters at `2e-4`, with fail-closed overlap/omission checks;
- effective batch 32, explicit micro-batch/gradient-accumulation accounting,
  BF16 autocast, loss scaling by accumulation count and gradient clipping 1.0;
- frozen linear warmup/decay scheduler with floor-5% warmup and one scheduler
  step per optimizer step;
- seeds 13/42/2026 plus Python, Torch CPU, initialized CUDA and independent
  dataloader-generator RNG capture/restore;
- optimizer-boundary progress binding for epoch, global next micro-batch cursor,
  optimizer steps and samples seen;
- mode-0700, no-replace checkpoint directories with mode-0600 canonical config,
  restricted `state.pt` and manifest-last publication;
- namespace/mode/link/hash/size/canonical-JSON verification and
  `torch.load(weights_only=True)` before live state mutation;
- model, optimizer, scheduler and RNG prevalidation plus rollback on an
  unexpected apply failure.

Checkpoints can only be created below `/data0/hk_data/kairos-zx`; symlink and
non-directory path components are rejected. Tests create temporary private
roots below `.tmp` and remove them on teardown.

## BF16 interval correction

The first equivalence run exposed an existing autocast defect: interval
projections were BF16, but the event mask was cast to the FP32 input-hidden
dtype. Multiplication promoted quantized coordinates back to FP32, so a second
FP32 `start + duration` differed from the already rounded BF16 end by about
0.002 and violated the model's own endpoint check.

Commit `7772f7c...` casts the mask to the projected start dtype. FP32 behavior is
unchanged; BF16 now preserves the exact quantized `end == start + duration`
identity required by interval geometry.

## Verification

- focused `training_execution + modeling`: 20/20 passed in 1.830 seconds;
- final full repository suite: 528/528 passed in 18.175 seconds;
- Kairos and Pair-MLP each matched uninterrupted training exactly after a
  one-step interruption, save, fresh-object restore and second step;
- equality covered trainable tensors, AdamW tensor/scalar state, scheduler,
  progress, per-step losses, gradient norms and the next Python/Torch/loader RNG
  draws;
- checkpoint no-replace, permissions, hash tamper, extra namespace, wrong-core
  fail-closed restore and non-LoRA backbone rejection are covered;
- `CUDA_VISIBLE_DEVICES` was empty and CPU threads were fixed to two;
- no persistent test checkpoint remained below `.tmp`.

## Remaining boundary

This is not a production trainer. It accepts an already materialized,
deterministic sequence of strict `TrainingBatch` objects and does not implement
dataset reading, sampler/epoch construction, candidate materialization, CLI,
PEFT injection, 7B loading or GPU execution. The v1 synthetic checkpoint binds
execution commit, configuration, trainable keys/shapes/dtypes and runtime
states, but does not yet bind a frozen backbone model revision or production
data manifest; it must not be used as a formal training checkpoint until those
bindings are added.

D-023 remains unchanged: no production GSM8K training may begin before the two
human audit submissions pass the registered agreement and validity thresholds.
The next safe action is a read-only local PEFT availability check followed by a
frozen model/data-binding and PEFT-injection design. A single-batch GPU
development smoke requires a fresh resource gate and clean implementation
commit; it is not a formal run.
