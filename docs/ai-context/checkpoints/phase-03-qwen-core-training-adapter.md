# Phase 03 Qwen-to-Core Training Adapter

- status: `COMPLETE / DEVELOPMENT_VERIFIED / SYNTHETIC ONLY`
- implementation_commit: `14f71040e4a490476c3372b1325b763843b360d9`
- date: 2026-07-24 CST
- production_data/model/GPU: none
- formal_run: none

## Implemented boundary

`kairos.training_adapter` connects contextual hidden states from a Qwen-compatible
backbone to the already verified `KairosModel` or `PairMlpBaseline`. Both cores
consume the exact same `TrainingBatch`, candidate encodings, masks, answer target,
original relation target, counterfactual relation target and fixed loss weights.
The only architectural difference remains interval geometry versus Pair-MLP pair
features.

The strict batch contains:

- original input IDs/attention and event-token/event masks;
- candidate input IDs/attention, exact candidate-span token masks and candidate
  validity mask;
- one valid answer-candidate index and optional original relation targets;
- an all-or-none counterfactual input/event-mask/relation-target group.

Every valid source has a real token; event spans cannot select padding; every
valid candidate has both attention and candidate-span tokens; padded candidates
must have neither; every example has at least one candidate and answer targets
cannot select padding. All tensors must share a device. Relation label placement
continues to be checked by the existing tensor-core loss.

Only valid candidates are flattened through the backbone, then scattered back
before the existing strict answer-span mean pool. Original and optional
counterfactual inputs are encoded separately. The adapter calls the Qwen base
decoder (`backbone.model` when available) with `use_cache=False`,
`output_hidden_states=False` and `return_dict=True`, and accepts only finite
`last_hidden_state` with exact `[batch,tokens,hidden_size]` shape. This avoids
retaining every decoder layer during training.

## Frozen LoRA interface

The development contract records rank 16, alpha 32, dropout 0.05, no bias,
gradient checkpointing enabled and cache disabled. Target module suffixes are:

`q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj`.

`validate_lora_targets` is read-only: every suffix must occur and every match
must be an `nn.Linear`. This stage does not import PEFT, mutate a model, inject
adapters or load Qwen weights. The seven-target choice is an independent project
default, not a recovered author configuration.

## Trainable state boundary

The module can clone and strictly restore the exact set of `requires_grad`
parameters in memory. Keys, CPU location, shape, dtype and finite values are
checked before any copy. Frozen backbone parameters are excluded. This supports
synthetic restore tests only; it is not a filesystem checkpoint format and does
not yet include optimizer/scheduler state, RNG state, manifest, hashes, no-replace
publication or resume semantics.

## Verification

- focused synthetic suite: 7/7 passed in 0.068 seconds
- full repository suite: 522/522 passed in 14.955 seconds
- both Kairos and Pair-MLP complete original/CF forward, all three losses and
  backward from the same batch
- gradients reach the fake backbone and each temporal core
- candidate padding, answer targets, event/padding overlap, partial CF groups,
  hidden-size/output mismatch, LoRA target type/coverage and strict trainable-state
  restore failures are covered
- `CUDA_VISIBLE_DEVICES` was empty; CPU threads were 2; all inputs were synthetic
- no production GSM8K/TORQUE/TimeQA record, Qwen weight, GPU, network or artifact
  was read or created

## Remaining work and gates

PEFT injection, optimizer parameter groups, gradient accumulation, BF16/AMP,
scheduler, deterministic dataloader, persistent checkpoint/manifest, resume,
candidate-pool materialization and training/evaluation runners remain absent.
GSM8K production training remains blocked until two human reviewers complete the
200-pair audit and the registered kappa/validity thresholds pass. This adapter
does not relax that gate and is not a model result or paper claim.
