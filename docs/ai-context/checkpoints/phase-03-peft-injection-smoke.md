# Phase 03 Project-local PEFT Injection and GPU Smoke

- status: `COMPLETE / DEVELOPMENT_VERIFIED / NOT A FORMAL RUN`
- contract_commit: `c37d86aa6b133125f5d32086ea8554f74c7d86a6`
- implementation_commit: `c68c77a2eceba9c34f93ac99bd5893807c02cecb`
- date: 2026-07-24 CST
- production data/formal checkpoint/metric artifact: none

## Dependency installation

The project-local environment is
`/data0/hk_data/kairos-zx/.conda/envs/kairos`. PEFT was downloaded from the
official PyPI index as `peft-0.14.0-py3-none-any.whl` into a new mode-0700 stage:

`/data0/hk_data/kairos-zx/.tmp/peft-0.14.0-install-FUETh37X`

- wheel bytes: 374,831
- wheel SHA256:
  `2f04f3a870c3baf30f15e7dcaa5dd70d3e54cfdd146d3c6c187735d3ae0a0700`
- wheel members / declared uncompressed bytes: 131 / 1,351,751
- offline METADATA: Name `peft`, Version `0.14.0`, Python `>=3.9.0`;
  Torch `>=1.13.0`, Accelerate `>=0.21.0`, Hub `>=0.25.0`
- install flags: `--isolated --no-index --no-deps --no-cache-dir`
- install manifest: mode 0600, 828 bytes, SHA256
  `0b76d845b751dd23b4cc4bc9e846e9dd4d15be25ec8eeb4968c8cc68ad38a340`

Post-install exact-version assertion confirmed that Torch 2.5.1, Transformers
4.48.3, Accelerate 1.2.1, Hub 0.28.1, Safetensors 0.5.2 and the other frozen
dependencies did not change. PEFT API import and `pip check` passed. No user,
global or other Conda environment was modified.

## Implementation and CPU verification

`kairos.training_adapter.inject_qwen_lora` now lazy-imports exact PEFT 0.14.0,
validates all seven Qwen projection suffixes before mutation, rejects repeated
injection and creates the frozen Causal-LM LoRA configuration. It disables
cache, enables input gradients and gradient checkpointing, then verifies the
single default adapter, exact hyperparameters/targets, and that every trainable
backbone tensor is a covered `lora_A` or `lora_B` tensor.

The Qwen-to-core adapter resolves the PEFT-wrapped base decoder directly, so it
still returns only the final hidden state rather than retaining every decoder
layer. A one-layer in-memory `Qwen2ForCausalLM` verifies real PEFT injection,
Kairos forward/backward, two optimizer groups, trainable-state round trip and
v2 checkpoint/resume with real PEFT parameter names.

- focused training-adapter: 9/9 passed in 0.216 seconds
- focused training-execution: 9/9 passed in 1.511 seconds
- full repository suite: 533/533 passed in 16.746 seconds
- full wall time / maximum RSS: 20.48 seconds / 538,448 KiB
- GPU was hidden and CPU math threads were fixed to two for tests

## Fixed-model GPU development smoke

Before execution, the four Safetensors shard hashes and index hash were
recomputed and matched the retained `SHA256SUMS`. The repository was clean at
`c68c77a...`; `/data0` had 144 GiB free, memory had 223 GiB available and
physical GPU 4 was idle at 11 MiB.

The first attempt failed before model loading because CUDA peak-memory reset
was called before explicit CUDA initialization. Status is
`INTERRUPTED_PREFLIGHT / NO MODEL LOAD / NO ARTIFACT`. After a fresh resource
gate, the corrected foreground attempt used only physical GPU 4, offline local
files and synthetic records:

- fixed model revision: `a09a35458c702b33eeacc393d103063234e8bc28`
- BF16, PEFT 0.14.0, seed 13, batch 32, one accumulation/optimizer step
- 392 trainable LoRA tensors; one `lora_B` tensor was proven changed
- samples seen: 32
- loss / gradient norm: 1.96875 / 203.84228515625
- model load / train step: 5.3596 / 1.1002 seconds
- peak allocated / reserved GPU bytes: 15,920,307,712 / 15,934,160,896

The process exited 0. GPU 4 returned to 11 MiB immediately afterward. No
production sample, formal run ID, checkpoint, prediction, metric or experiment
result was created; these numbers are implementation diagnostics only and must
not enter a paper table.

## Remaining boundary

PEFT installation and Stage 2 GPU feasibility are no longer blockers.
Production training remains blocked by the two-person relation audit and by the
absence of a deterministic sampler, source-order batch/candidate manifest and
formal training runner. Relation-only v1 still cannot support counterfactual
answer metrics or Same-data SFT answer-update claims.
