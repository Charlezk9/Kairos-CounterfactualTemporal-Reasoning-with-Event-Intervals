# Audit-gated Development Training Execution Plan

## Status and compressed context

This plan replaces the unsafe assumption that the current A/B files constitute
a formal two-human audit. It is the sole detailed plan for the current critical
path; `CURRENT.md` contains only restart state.

- frozen branch/base: `experiment/reproduction-additional-evaluation` at
  `4d0cfa19ee8ac29f2176ba173d6491a0853ab2e4`
- fixed model: `Qwen/Qwen2.5-7B-Instruct` revision
  `a09a35458c702b33eeacc393d103063234e8bc28`
- model `SHA256SUMS` file SHA256:
  `3ee6c9510b7e50bfcd46d6df33cafa3e2019f13a6a09bf1d2f9e80cdfe1164e8`
- A/B bytes are structurally valid, source-order bound and user-confirmed, with
  SHA256 `99b95522c1f57156bd8f904c6d66e13b1ee9c6f6154988392b32ffdd8d5941ba`
  and `96c9c53561730d776834b5e7cc705a3274af82b2b2afd08faf1f1dc63cc67e67`
- packet manifest and items SHA256 are
  `da5d7fb0659e1bb13aa1d6b03e59e83c5ddb42c05535932313552af7dcc19ecb`
  and `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`
- strict in-memory replay gives 196/200 valid, observed agreement 1.0,
  expected agreement 0.9608, conditional Cohen's kappa 1.0 and validity 0.98
- the 370-record relation-only source has data/manifest SHA256
  `525e3b09c6a6d03942a6bc3e03ebcd1722c3a68f4f224753dbc641f98465c12a`
  and `4e22ff135d97c89ded50a54fc1007f25d9646db67ce112e4637d4e8c8b63674a`
- the existing 366-record copy has data/manifest SHA256
  `4b5fec2bf46b1b86df9639b0e2cea9bc355e77be04247f5f27fcef3cb725f788`
  and `f24a8e8ef2ee3f5abf75938e620b43a8c2dcb52b52459ac000ba97bc87258b5a`;
  its frozen `split.internal` values yield train 330 / internal-dev 36
- no relation-only record has a counterfactual answer; CF-answer accuracy,
  update, stability and consistency are prohibited
- formal audit result, private intake, partition, candidate pool, run-input
  manifests, production runner, checkpoints and held-out paper result are absent

## Evidence classification and human-provenance gate

Current A/B files are `USER_ATTESTED / INDEPENDENCE_UNVERIFIED`. Their shape,
hashes and agreement do not prove two independent human reviewers. They permit
only development training and `INTERNAL-DEV / NOT PAPER-ELIGIBLE` results.

Promotion to a formal two-human audit requires, before A/B comparison, a private
provenance record binding two distinct pseudonymous reviewer IDs, separate
independent-completion declarations, reviewer slots, export timestamps,
pre-comparison A/B hashes, packet-manifest hash and audit-items hash. It contains
no real names, sample text, secrets or notes. If this is never supplied, the
status never promotes; a single person confirming both slots is insufficient.

There are zero A/B overall-label disagreements. Therefore D-038 will introduce
an algorithmic `agreement-projection` artifact, distinct in filename, schema and
provenance from author adjudication. It is a pure canonical projection of locked
A/B labels, may exist only for zero disagreements and is always reported as
algorithmic. It is never called human or author adjudication. Existing D-035
semantics and schemas remain intact; the new adapter/result version is additive.

## Server-safety envelope

Writes are restricted to `/home/yangbin/zx-tmp/kairos` and
`/data0/hk_data/kairos-zx`. Never use sudo, global/user package installation,
default SSH, force push, history rewrite, unknown-process termination, recursive
cleanup, symlinks, hardlinks or overwrite of an existing artifact. Publishers
use no-replace creation, mode-0700 directories, mode-0600 private files,
fsync-before-manifest and manifest-last finalization. A target collision stops;
it is never deleted, overwritten or silently renamed.

Before each generation, real-model smoke or training attempt, persist a
read-only resource record containing `nvidia-smi`, `free -h`, `df -h`, selected
physical GPU and free memory, project disk use, worst-case new bytes and the
decision. Re-hash every model file against `SHA256SUMS`. Stop if `/data0` free is
below 120 GiB, projected cumulative new project data exceeds 80 GiB, task RAM
could exceed 64 GiB, or the selected single GPU has less than 22 GiB free. The
22-GiB floor is a pre-output amendment for 24-GiB RTX 3090 devices: the prior
24-GiB floor was physically unattainable after driver allocation, while the
verified one-step peak was 15,920,307,712 bytes, leaving more than 7 GiB at the
new floor. The selected UUID must also have no compute process. Use
one foreground job, at most 16 CPU threads and 8 workers; do not disturb other
processes.

Every real run exports `CUDA_DEVICE_ORDER=PCI_BUS_ID` and the selected full GPU
UUID through `CUDA_VISIBLE_DEVICES=<GPU-UUID>`, never an ambiguous ordinal.
`OMP_NUM_THREADS=8`, `MKL_NUM_THREADS=8`, `OPENBLAS_NUM_THREADS=8`,
`NUMEXPR_NUM_THREADS=8`, DataLoader workers 2 and `PYTHONHASHSEED=<run-seed>`.
It fixes `CONDARC=/data0/hk_data/kairos-zx/.conda/.condarc`, the existing Conda
prefix, and project-local `CONDA_PKGS_DIRS`, `PIP_CACHE_DIR`, `HF_HOME`,
`HF_HUB_CACHE`, `XDG_CACHE_HOME`, `TMPDIR`, `TEMP` and `TMP`. It also sets
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
`TOKENIZERS_PARALLELISM=false`. The resource record binds driver, GPU, CUDA,
Python, Torch, Transformers, PEFT, Safetensors and attention implementation.
The runner calls `torch.use_deterministic_algorithms(True)` and exports
`CUBLAS_WORKSPACE_CONFIG=:4096:8`; any unsupported nondeterministic operation is
a recorded hard failure rather than silently relaxed. No background training
is allowed.

The gate binds physical index, full UUID, PCI bus ID, name and total/free memory.
Immediately after CUDA initialization and before model loading, the child must
see exactly one CUDA device and obtain its UUID/PCI identity through CUDA/NVML;
both must equal the gate record, while name and total memory provide additional
cross-checks. If UUID/PCI lookup is unavailable or differs, stop before loading
weights. The post-run record repeats the same identity and confirms release.

## Stage 0: freeze, independent re-audit and safe source intake

The independent audit must mark this corrected plan `APPROVED` before any
production implementation or model load. Then commit and push the plan,
governing decisions, audit and compact state from a clean named-file staging
set. `CURRENT.md` must point to that exact commit.

After approval, copy the four raw A/B files and sidecars without replacement to
`/data0/hk_data/kairos-zx/artifacts/audit-intake/gsm8k-relation-v1/user-attested-20260725/`.
The intake parent is mode 0700; files are regular, mode 0600, link count one and
reopened no-follow for byte/hash verification. Store a bounded metadata record
with status `USER_ATTESTED / INDEPENDENCE_UNVERIFIED` and no sample text.

The raw A/B files were already pushed in commit `4d0cfa1`; that exposure is
recorded and cannot be undone without forbidden history rewriting. After the
private intake verifies, remove raw JSONL/sidecars from the branch tip in an
ordinary commit. Git retains only hashes, counts and aggregate facts. If the
repository owner considers the historical exposure unacceptable, stop for an
explicit owner decision; never rewrite shared history autonomously.

## Stage 1: replayable development audit artifact (D-038)

Implement a strict adapter around the tested D-035 evaluator using synthetic
fixtures first. It binds the packet, items, private A/B, their paths, byte sizes,
full hashes, schema, order, reviewer slots, provenance status and execution
commit. It emits canonical `agreement-projection.jsonl`, `audit-result.json` and
manifest-last `manifest.json` in a new immutable private `/data0` artifact.

The independent verifier reopens all source/result bytes no-follow and rejects
extra files, wrong modes/link counts, substitutions, any disagreement,
projection divergence, statistic drift, truncated hashes, existing targets and
tampering. Result status is `PASSED_DEVELOPMENT`, never `PASSED_FORMAL`. The
expected semantic values are 196 valid, 4 invalid, agreement 1.0, expected
agreement 0.9608, conditional kappa 1.0 and validity 0.98. Also publish the
Wilson 95% interval for 196/200 as uncertainty, without treating the point
estimate as proof that every retained record is valid.

Focused and full tests run with GPU hidden and two CPU threads. From a clean
implementation commit, publish once, verify in a fresh process and register all
full hashes. No sample text or review notes enter Git.

## Stage 2: immutable 330/36 development partition

Rebuild an immutable 366-record artifact from the verified 370-record source,
excluding exactly the four pair IDs derived from the D-038 result. Do not mutate
or relabel the existing copy. A verifier reconstructs the filter and rejects a
caller-provided exclusion list that is not derivable from the audit chain.

Before model output exists, publish a partition manifest by replaying the
already-frozen `split.internal` field: train 330, internal-dev 36, source order
preserved. It binds every ID, ordered partition-ID hashes, counts, data/audit/
source manifests and execution commit. A source group and its original/CF pair
may occur in exactly one partition. Training plans may bind only train IDs.
Internal-dev never enters an optimizer and never receives ordinary gold
injection. Its predictions and metrics are separate and always labeled
`INTERNAL-DEV / NOT PAPER-ELIGIBLE`.

## Stage 2.5: pre-output SFT and evaluation contracts

Before any train or internal-dev text reaches a model, freeze and commit the
tracked `docs/ai-context/sft-protocol-v1.json` and
`docs/ai-context/evaluation-protocol-v1.json`. Their current Git-byte SHA256 are
`86c1de0b6c47e9e9275771866bc42b6b39b56c0f3b1430a9cfc1fd35225f0d43` and
`b15074103a7940777dd6e39e0aa2f9831ca9fc344affddc102a8a0c3fc88aee1`.
The former fixes the Same-data SFT prompt, canonical target, parser and decoder;
the latter fixes method-specific prediction identity, exact decimal matching,
argmax/tie/non-finite behavior, candidate recall and injection diagnostic,
bootstrap, confidence intervals and the six-hypothesis Holm family. Both hashes
enter every applicable candidate/run/evaluation manifest. Neither protocol may
be changed after the first candidate or SFT output; a future revision requires
a new schema/version and invalidates comparison with v1.

## Stage 3: frozen gold-blind candidate pool (D-039)

D-039 binds the exact tracked prompt specification
`docs/ai-context/candidate-prompt-v1.json`, Git-byte SHA256
`8632dfbd3f8f2b90c9a897bdb15b232b92705d79c8d8dcfd3f7ea94886f67349`.
Qwen's
checked-in chat template is applied without modification. Direct is greedy with
128 new-token maximum; CoT is greedy with 512; Self-Consistency uses eight CoT
samples at fixed positions 0--7, temperature 0.7, top-p 0.9 and top-k 0. Input
is truncated only by a hard failure at 4096 tokens; it is never silently cut.
Batch size is one to preserve per-item RNG identity. BF16, SDPA, EOS IDs
`[151645,151643]` and pad ID `151643` are fixed.

The sole pool seed is `20260725`, shared by all methods and training seeds. For
each stochastic position, derive the 63-bit seed as the big-endian first eight
bytes of SHA256 over UTF-8 bytes
formed by ASCII `kairos-candidate-v1`, one zero byte, decimal pool seed, one
zero byte, the exact UTF-8 source ID, one zero byte and decimal sample position,
masked by
`0x7fffffffffffffff`; reset CPU/CUDA RNG immediately before that one generation.
Greedy generations use the same identity without consuming a sampling seed.

Direct accepts only an entire stripped non-empty JSON string. CoT/SC accepts
only a last non-empty line `FINAL_ANSWER: ` followed by one non-empty JSON
string. Invalid/timeout/OOM generations are retained as explicit typed rows and
never converted to gold. No parse-rate threshold changes the prompt or parser;
only model/file/resource/contract failure aborts. Each raw response is limited
to 64 KiB UTF-8, the artifact to 512 MiB and this stage's total new-data budget
to 2 GiB.

Generate for train and internal-dev into distinct namespaces from the same
gold-blind policy. Deduplicate exact candidate strings in Direct, CoT,
sample-0..7 order. Gold injection is permitted only when later materializing
train supervision under D-031/D-034 and is recorded per item. Primary
internal-dev evaluation uses the untouched pool. An injected-gold diagnostic is
published separately and can only quantify sensitivity.

Post-publication replay found exactly three empty generated pools among train330
and none among internal-dev36. D-043 is the sole amendment for this observed
case. The immutable gold-blind candidate artifact is not changed. A versioned
production train materializer may convert only those three verified empty pools
to a singleton original-gold candidate with `origin=gold`,
`gold_injected=true` and target index zero; its answer-ranking loss contribution
is therefore zero while original/CF relation supervision remains active. The
run-input v2 binds policy `train-empty-generated-pool-gold-only-injection-v1`,
empty count 3 and ordered pair-ID-list SHA256
`22b4edc8c53acf2971d1d618da17388ea34c759188fab4b32ed41f384d22161a`.
Any count/hash drift, an internal-dev empty pool or use outside train fails.
The default D-034 API continues to reject empty generated proposals; D-043
requires an explicit versioned path and independent approval before code or
training.

D-042 fixes the stochastic implementation without relaxing strict
determinism. The first failed mechanics smoke proved that CUDA
`cumsum_cuda_kernel` is rejected by `torch.use_deterministic_algorithms(True)`;
no stochastic candidate was produced or published. Self-Consistency therefore
uses incremental Qwen forward passes on the selected GPU but moves each final
step's single float32 logit vector to CPU before filtering and sampling. It
divides logits by 0.7, performs a stable ascending CPU sort (equal logits retain
ascending vocabulary-ID order), computes float32 softmax and cumulative mass,
removes entries whose ascending cumulative probability is at most 0.1 while
always retaining the final sorted entry (the highest vocabulary ID among an
exact maximum-logit tie), and scatters negative infinity back in original
vocabulary order. The exact calls are `torch.sort(..., dim=-1,
descending=False, stable=True)`, `torch.softmax(..., dim=-1,
dtype=torch.float32)`, `torch.cumsum(..., dim=-1, dtype=torch.float32)` and a
dimension-minus-one scatter. After a second float32 softmax, the only sampling
primitive is `torch.multinomial(filtered_probs, 1, replacement=False,
generator=g)`. Exactly one CPU `torch.Generator` is created and `manual_seed`ed
once at the start of each `(source_id, sample_position)` sample; the same
generator persists across all generated tokens in that sample. It is never
reset per token, shared across positions or replaced by global RNG,
`Categorical`, `rand` or search-sorted sampling. Top-k 0 performs no additional
filter.

Every SC position creates a fresh Transformers 4.48.3 `DynamicCache`; caches
are never shared across positions or records. The first forward consumes the
full unpadded prompt with `use_cache=True`, explicit attention mask,
`cache_position=0..prompt_length-1` and matching `position_ids`. Each later
forward consumes only the previously selected non-EOS token, grows the full
attention mask by one and supplies the one-element next cache position and
matching position ID. The output cache must be that position's cache and must
have exactly 28 layers; every key/value tensor must remain CUDA BF16 with shape
`[1,4,current_sequence_length,128]`, and sequence length must grow by exactly
one after every cached token forward. EOS is appended to generated IDs and
stops before another forward. Only generated IDs, never prompt IDs, are decoded.
Any non-finite logits/probabilities, invalid cache/output/attention/position
shape, device/dtype drift, empty distribution or cache reuse is a hard failure.
CPU golden tests bind exact filtering, ties and seed replay. Incremental golden
tests must prove, for every selected token, equality with a fresh full-prefix
reference's next-token logits and selected token, and must prove cache isolation
between positions before another real smoke. This amendment changes only the
deterministic implementation of the already-frozen sampling distribution;
prompt, pool seed, per-item seed formula, temperature, top-p, top-k, model,
data, parser and evidence rules do not change.

The artifact binds complete model-file verification, tokenizer/config/chat
template hashes, prompt hash, all decoding/RNG settings, partition manifests,
raw evidence and parsed proposals. An 8-record smoke checks mechanics only and
cannot tune any setting. Production generation runs once, foreground, offline,
from a synchronized clean commit after a passed persisted resource gate.

## Stage 4: full run-input identity and deterministic runner (D-040)

Introduce a versioned `kairos-run-input-v2` semantic manifest binding full
SHA256 values for audit result/manifest/provenance status, data and partition
manifests, candidate/raw-evidence manifests, tokenizer/config/chat template/
prompt, every model file, method configuration, seed, environment/resource
record and execution commit. Training plans and checkpoints bind the canonical
semantic hash of this complete object. Tests mutate each field and reject
omission, substitution, cross-seed/core reuse and truncated hashes.

For each of seeds 13, 42 and 2026, train only 330 IDs for three epochs in the
frozen D-031 order. With micro-batch 1 and effective batch 32, 990 real slots
are followed by two explicit repeat slots, producing exactly 31 optimizer
steps. Use LoRA rank 16, alpha 32, dropout 0.05, BF16, AdamW, learning rates
`2e-5` for LoRA and `2e-4` for Kairos/Pair-MLP core, weight decay 0.01, 5%
warmup, clip 1.0 and `lambda_rel=lambda_cf=1`.

Checkpoints are immutable IDs `step-000005`, every five optimizer steps, and
final `step-000031`. Resume requires an explicitly supplied checkpoint ID; no
mutable `latest` exists. Verification binds pre-state, cursor, plan/run-input
hash, trace-prefix hash and RNG state before loading tensors. A lazy sequence
reports the complete plan length but dereferences only validated active indices;
tests prove future slots are never materialized. Interrupted targets remain
immutable, receive a bounded separate failure record and are never resumed in
place. Successful run manifest publishes last after final checkpoint and trace
verification; logs are capped at 256 MiB.

CPU/synthetic focused and full tests precede one real-record no-optimizer smoke,
then one optimizer-step GPU smoke. Smoke IDs and manifests are development-only
and cannot be promoted.

## Stage 5: mandatory matched methods

Kairos and Pair-MLP use identical Qwen hidden states, train/dev identities,
candidate pool, seeds, losses and gold policy; their difference is limited to
the frozen interval geometry versus pair MLP.

Same-data SFT is mandatory before the primary reviewer comparison is complete.
It uses the same Qwen revision, LoRA rank/alpha/dropout, train/dev IDs, seeds,
optimizer schedule and final-checkpoint rule. Its prompt, target and decoder are
the already-frozen `sft-protocol-v1.json`: target bytes come from the project's
sort-key `canonical_json`, hence exact key order is `answer`,
`counterfactual_relation`, `original_relation`. It uses source answers only for
train targets, no candidate pool, and the frozen strict whole-response JSON
parser during gold-blind dev generation. Trainable parameters are separately
manifested before its first real model load.

Execute seed 13 for Kairos, Pair-MLP and Same-data SFT, verify and compare, then
continue seeds 42/2026 only if all seed-13 artifacts replay. Negative, failed and
OOM runs remain registered. If Same-data SFT is deferred, the primary reviewer
claim remains `DEFERRED`; Kairos versus Pair-MLP is secondary only.

## Stage 6: frozen evaluation and reporting

Checkpoint selection is fixed to final `step-000031`; internal-dev is not used
for selection, early stopping or hyperparameter changes. Primary development
evaluation uses the frozen 36-item internal-dev split. Per-item prediction
identity is `(dataset revision, split, source ID, method, seed, checkpoint,
method-applicable input-manifest hashes)`; paired comparisons use source ID.
Kairos/Pair-MLP use the untouched gold-blind candidate pools; Same-data SFT uses
its frozen prompt/decoder and has no candidate pool.

All selection, normalization, candidate recall, non-finite/tie behavior,
bootstrap seed/resamples/quantiles/p-values and the exact six-hypothesis Holm
family are defined only by the already-frozen `evaluation-protocol-v1.json`.
Candidate recall and injected-gold sensitivity apply only to Kairos/Pair-MLP;
for Same-data SFT the candidate manifest and both diagnostics are explicitly
`NOT_APPLICABLE`. Permitted common outcomes are original-answer accuracy, exact
five-class original-relation accuracy and counterfactual-relation accuracy.
CF-answer accuracy, update, stability and consistency remain absent.

Predictions, metrics and statistics use immutable manifest-last publishers and
fresh-process verifiers bound to the full run-input/checkpoint chain. All results
remain `PRELIMINARY / INTERNAL-DEV / NOT PAPER-ELIGIBLE`. A future paper result
requires a separately committed official-test construction and gold-blind
evaluation contract, formal two-human provenance or an explicitly accepted
alternative, three seeds and the required matched baselines. No internal-dev
number enters the paper recommendation section of `verify-addExp.md`.

## Execution order and stop rules

1. obtain independent `APPROVED` re-audit; commit/push plan and compact state;
2. private intake plus ordinary removal of raw review bytes from branch tip;
3. implement/test/publish D-038 development audit;
4. implement/test/publish audit-bound data and 330/36 partition;
5. bind/test the already tracked SFT/evaluation v1 contracts;
6. freeze/test D-039, pass resource/model gate, generate shared candidates;
7. implement/test D-040 runner and isolated smokes;
8. train matched seed 13, then remaining seeds; evaluate and report;
9. separately implement an official held-out protocol before any paper claim.

Resource amendment D-041 was frozen before any candidate/model output. Sampling
amendment D-042 was frozen after greedy mechanics outputs but before any
stochastic candidate output or published candidate artifact. Neither changes
prompts, data, metrics or training hyperparameters.

Stop without deleting or repairing evidence when hashes/facts change, A/B
disagree, provenance is misrepresented, a verifier fails, an artifact target
exists, Git is dirty at a formal run boundary, remote/upstream differs, model
files fail, candidate rows are incomplete, resource limits fail or an unknown
process owns a resource. Record the immutable failure and update `CURRENT.md`.

Milestone commits use named staging only:

1. `docs: freeze audit-gated development training plan`
2. `feat(audit): publish replayable user-attested audit result`
3. `data(training): publish audit-bound development partition`
4. `feat(candidates): add frozen GSM8K candidate pool`
5. `feat(training): add provenance-bound production runner`
6. `exp: record matched relation-only development runs`

At a key milestone update only the relevant checkpoint, registry,
`verify-addExp.md` and compact `CURRENT.md`; do not duplicate this plan.
