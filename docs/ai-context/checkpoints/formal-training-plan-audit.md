# D-042 Deterministic Sampling Amendment Re-audit — 2026-07-25

## D-042 VERDICT

`APPROVED_AMENDMENT`

D-042 已充分修正上一轮的两个 P1 阻塞项，可作为下一次真实 smoke 前的冻结执行契约。该批准仅覆盖计划严谨性，不把此前失败的 mechanics smoke、Direct/CoT 临时输出或任何未发布 stochastic 输出认定为候选实验工件。

批准依据：

- 采样语义已机械化固定：最终一步 logits 在 CPU float32 上除以温度 `0.7`，使用稳定升序 `torch.sort`、float32 `softmax/cumsum`、删除累计概率 `<= 0.1` 的低概率项且始终保留最后一项，再按原词表维度 scatter；`top_k=0` 不执行额外过滤。
- 随机数生命周期已唯一化：每个 `(source_id, sample_position)` 仅创建并播种一次 CPU `torch.Generator`，跨该样本全部生成 token 复用；唯一抽样原语为 `torch.multinomial(filtered_probs, 1, replacement=False, generator=g)`，禁止逐 token 重置、全局 RNG、跨样本共享及替代抽样实现。
- KV cache 契约已闭合：每个 SC 位置使用独立且全新的 Transformers 4.48.3 `DynamicCache`；首步完整未填充 prompt 与后续单 token 前向的 attention mask、`cache_position`、`position_ids`、EOS 停止行为和仅解码生成 ID 均已明确；缓存必须为 28 层 CUDA BF16，逐层 K/V 形状为 `[1, 4, current_sequence_length, 128]`，且后续步序列长度严格递增 1。
- golden gate 已覆盖 CPU 过滤边界、并列 logits、种子重现性、cached 与 fresh full-prefix 的逐 token 一致性，以及不同 SC 位置/记录间的 cache 隔离；非有限值、空分布、缓存复用或形状/位置异常均为硬失败。
- D-042 未放松严格确定性，也未改变 prompt、模型、数据、parser、证据规则及既定单 GPU/资源边界。

放行条件：在文档与本审计记录提交、推送且工作树 clean 后，先通过新增 unit/golden 与完整测试，再完成资源门禁，才可启动一个前台真实 smoke。若 cached-vs-full-prefix equality 在固定环境中不能成立，必须停止并记录失败；不得私自加入容差、改变 kernel/采样规则或发布结果，任何此类变化都需要新的 amendment 与独立复核。

# D-041 Resource Amendment Re-audit — 2026-07-25

## D-041 VERDICT

`APPROVED_AMENDMENT`

The sole change from selected-GPU free memory `>=24 GiB` to `>=22 GiB` is
approved. It is necessary for a 24,576-MiB RTX 3090 whose observed idle free
memory is 24,243 MiB, and remains conservative when combined with the unchanged
full-UUID process and resource gates.

Mechanical basis:

- the new floor is exactly 22 GiB = 22,528 MiB = 23,622,320,128 bytes;
- the observed idle value exceeds the floor by 1,715 MiB;
- the retained clean one-step peak is 15,920,307,712 bytes, so the floor-minus-
  peak margin is 7,702,012,416 bytes, approximately 7.17 GiB;
- the selected full GPU UUID must have no compute process, only one foreground
  project task may run, and UUID/PCI identity is checked again through CUDA/NVML
  after CUDA initialization and before model allocation;
- CPU, RAM, disk, model-hash, offline/cache, deterministic, no-replace and
  unknown-process protections are unchanged;
- D-041 was frozen before any GSM8K candidate, SFT or internal-dev model output
  and does not alter data, prompt, parser, metric, seed or training settings.

Implementation must interpret `GiB` as binary units and persist free memory in
both bytes and MiB to avoid unit ambiguity. The 15.9-GB observation is a known
reference, not permission to skip the stage-specific worst-case projection,
real-record smoke or immediate resource recheck. If free memory falls below
22 GiB, any compute process appears on the selected UUID, UUID/PCI differs, or
the bounded smoke fails/OOMs, stop and retain evidence without selecting another
GPU automatically, killing a process or weakening the threshold.

This amendment inherits the Round 4 approval scope:
`USER_ATTESTED / DEVELOPMENT ONLY / INTERNAL-DEV / NOT PAPER-ELIGIBLE`.
It does not independently authorize model loading before the amended plan,
D-041, audit and compact state are committed/pushed and the normal clean-HEAD,
model-file and resource gates pass.

# Round 4 Final Current Re-audit — 2026-07-25

## CURRENT VERDICT

`APPROVED`

The corrected plan is approved for the explicitly scoped
`USER_ATTESTED / DEVELOPMENT ONLY / INTERNAL-DEV / NOT PAPER-ELIGIBLE` path.
This approval does not promote the A/B files to an independent two-human audit,
does not authorize paper claims, and does not bypass any stage/resource/test
gate in the plan.

Final mechanical checks passed:

- worktree SFT protocol SHA256 is
  `86c1de0b6c47e9e9275771866bc42b6b39b56c0f3b1430a9cfc1fd35225f0d43`;
- worktree evaluation protocol SHA256 is
  `b15074103a7940777dd6e39e0aa2f9831ca9fc344affddc102a8a0c3fc88aee1`;
- both full hashes match the execution plan and D-040;
- the SFT protocol's tokenizer-config, tokenizer and generation-config hashes
  match the fixed local Qwen snapshot;
- the SFT contract uniquely binds system/user/assistant messages, prefix/full
  chat-template calls, `add_special_tokens=false`, exact prefix masking,
  supervised canonical target plus `<|im_end|>` and following LF, and no extra
  EOS;
- the evaluation contract makes an empty pool a typed zero-contribution
  failure and binds both relation metrics to `relation_logits[0,1,:]`, event 1
  source to event 2 target;
- the pre-output freeze order, 330/36 isolation, exact Decimal/argmax/statistical
  rules, method-specific candidate applicability and UUID/PCI GPU identity gate
  remain intact.

## Mandatory mechanical gates during implementation

1. Commit the plan, D-038/D-039/D-040, three protocol files, this audit and
   compact `CURRENT.md` using named staging; run the hook/diff check, push
   normally, and continue only from the synchronized clean commit recorded by
   `CURRENT.md`.
2. Before any model output, parse the tracked protocols strictly, recompute all
   three protocol hashes and the three tokenizer-related hashes, and require
   exact equality with the committed plan/D-040 values.
3. Publish the private A/B intake no-replace with 0700/0600, no-follow,
   regular-file and link-count verification before removing raw review files
   from the branch tip through an ordinary commit. Never rewrite history.
4. Keep D-038 status `PASSED_DEVELOPMENT`; verify agreement projection,
   statistics, uncertainty and all source hashes in a fresh process. Never call
   it formal human adjudication.
5. Reconstruct the 366 records and frozen 330/36 partition from immutable
   sources; only the 330 train IDs may appear in optimizer plans, while the 36
   internal-dev IDs remain gold-blind and never drive tuning/selection.
6. Synthetic golden tests must prove exact SFT rendered text/token IDs/loss
   masks and evaluation behavior for empty/all-invalid/single/tied/non-finite
   candidates and `[0,1]` versus inverse relation logits before real input.
7. Before every model load or high-resource attempt, persist and pass the full
   resource/model-file gate. Use one foreground job, fixed project caches,
   offline mode, one full-UUID GPU, and assert UUID/PCI identity after CUDA/NVML
   initialization but before weight allocation. Stop on any mismatch without
   probing other GPUs, deleting evidence or touching other processes.
8. Publish plans, checkpoints, traces, predictions, metrics and statistics only
   through the versioned full-hash chain and manifest-last/no-replace paths;
   replay each seed-13 method before continuing later seeds.
9. Keep Same-data SFT mandatory for the primary matched comparison. If it or
   any required method is deferred, retain the result and mark the reviewer
   primary claim `DEFERRED`; do not promote the secondary comparison.
10. Report every produced number as
    `PRELIMINARY / INTERNAL-DEV / NOT PAPER-ELIGIBLE`; omit all prohibited
    CF-answer/update/stability/
    consistency claims and require a separately frozen official-test plus
    formal human-provenance path before any paper use.

## Accepted non-blocking residual risks

- Human independence remains user-attested rather than demonstrated; the plan
  correctly prevents formal promotion.
- The 200-item audit estimates quality and the 36-item internal-dev evaluation
  has low statistical power; neither establishes broad generalization.
- Raw review bytes remain in already-pushed history even after ordinary removal
  from the branch tip; autonomous history rewrite remains forbidden.
- Exact CUDA results may vary across hardware/software despite deterministic
  gates; immutable artifacts, environment binding and three seeds provide
  auditability rather than cross-hardware bit identity.
- Same-data SFT and the production runner are still implementation work; this
  approval accepts the staged plan, not untested future code or artifacts.

# Round 3 Current Re-audit — 2026-07-25

## HISTORICAL ROUND 3 VERDICT

`BLOCKED`

The protocol hashes match the current worktree bytes:

- `sft-protocol-v1.json`:
  `e59bfd38da219f6f72463af4743bd8a8c776f90541e32ff854bd6a76c7d43a6a`
- `evaluation-protocol-v1.json`:
  `880c3bff711f1241dae4b3d248ab6e3455d69b73eeeceeda39e34d3c2600a759`

Round 2's freeze-order, canonical-key-order, Decimal/tie/non-finite/statistical,
method-applicability and physical-GPU identity findings are otherwise closed.
Two narrow exactness defects remain; no model output may begin until both files,
their recorded hashes and D-040 are updated consistently.

### R3-P1-01 — SFT chat bytes and supervised token slice are not unique

`sft-protocol-v1.json` fixes the system/user content and canonical assistant
object, but it does not bind the chat-template file/hash, exact message list,
`apply_chat_template` flags, `add_generation_prompt`, special-token behavior or
whether the assistant terminator (`<|im_end|>`/EOS) belongs to the training
sequence and loss mask. The phrase “assistant target tokens only” therefore
does not determine one token sequence or one loss mask.

**Required mechanical fix.** Add exact fields that bind the verified Qwen chat-
template hash and specify, separately for training and evaluation:

1. ordered roles/messages and exact content interpolation;
2. `tokenize`, `add_generation_prompt` and special-token flags;
3. the complete rendered-sequence construction;
4. the exact supervised byte/token slice, explicitly including or excluding
   the assistant terminator and EOS;
5. padding side, attention/loss mask and overlength behavior.

Add golden synthetic rendered-text, token-ID and loss-mask fixtures. Update the
protocol SHA in the plan and D-040 before any candidate or SFT output.

### R3-P1-02 — empty candidate pools and relation direction are undefined

`evaluation-protocol-v1.json` says to choose the greatest score when every score
is finite. For an empty candidate pool the finite predicate is vacuously true,
but no greatest candidate exists. It also refers to original/CF five-logit
vectors without binding which direction is extracted from the model's 2x2
relation matrix; choosing `[1,0]` would silently evaluate the inverse of SFT's
event-1-to-event-2 target.

**Required mechanical fix.** Specify that an empty valid parsed candidate pool
produces a retained typed `invalid-empty-candidate-pool` prediction with answer
contribution zero. Bind both original and counterfactual relation evaluation to
matrix entry `[0,1]`, source-order event 1 to event 2; `[1,0]` is ignored for the
primary metric (or separately named diagnostic only). Add synthetic tests for
empty/all-invalid pools, one candidate, score ties/non-finite values, `[0,1]`
versus inverse disagreement and SFT label parity. Update the protocol SHA,
plan and D-040 atomically.

## Round 3 approval condition

After these two changes, a final mechanical recheck need only confirm JSON
parsing, full-file hashes, plan/decision hash equality, pre-output ordering and
the new golden tests as mandatory implementation gates. The previously listed
non-blocking residual risks remain accepted.

# Round 2 Independent Re-audit — 2026-07-25

## ROUND 2 VERDICT

`BLOCKED`

The revision closes Round 1 P0-01 through P0-03 and P1-01 through P1-04/P1-06:
the A/B evidence is correctly downgraded to development-only, agreement
projection is no longer called human adjudication, the observed 330/36 split is
isolated, raw review bytes move to private intake, the full run-input identity
chain/checkpoint cadence is planned, and candidate/resource contracts are now
substantially bounded. Same-data SFT is also mandatory rather than optional.

Four remaining defects must be fixed before approval. Do not begin model load,
candidate generation, GPU smoke or training while this verdict is blocked.

### R2-P0-01 — evaluation and SFT contracts freeze after internal-dev output

**Evidence.** Stage 3 generates candidate outputs for internal-dev (plan lines
145--186), but Stage 5 defers the exact Same-data SFT prompt, decoder, target
canonicalization and parameter contract until immediately before its own model
load (lines 225--233). Exact evaluation rules are likewise deferred to Stage 6.
Thus internal-dev model output can exist before a competing method and its
metric/parser contracts are frozen, leaving a route for dev-informed design.

**Executable fix.** Add and hash exact tracked `sft-prompt-v1.json` and
`relation-evaluation-v1.json` contracts, freeze them in D-040, and commit them
before the first train **or internal-dev** candidate/model output. Move this
gate ahead of Stage 3. The SFT contract must include exact prompt bytes, chat
format, target bytes, generation settings, parser and trainable parameters; the
evaluation contract must include all rules in R2-P1-01. Synthetic-only tests
must pass before any internal-dev artifact is generated. After these files are
frozen, internal-dev output must never change either contract.

### R2-P1-01 — metric and statistical semantics remain non-exact

**Evidence.** “Normalized numeric accuracy”, “gold answer occurs”, relation
accuracy, paired bootstrap and “predeclared three-method comparisons” (lines
240--256) do not define the numeric grammar/normalizer, equality relation,
candidate-score tie policy, relation-logit tie/non-finite behavior, bootstrap
resample count/seed/interval algorithm or exact Holm family. This does not yet
support byte-identical metric replay. In addition, Stage 5 says SFT uses no
candidate pool, while Stage 6 gives every prediction a candidate-manifest
identity and describes candidate recall/gold-injection sensitivity as if they
applied to all three methods.

**Executable fix.** The tracked evaluation contract must freeze:

- exact UTF-8 answer parser and numeric canonicalization, including signs,
  commas, decimals, fractions, exponent notation, units, whitespace and invalid
  forms;
- whether candidate recall uses exact string equality or that same normalizer;
- earliest-candidate argmax tie behavior for Kairos/Pair-MLP, fixed relation
  class order/ties, and fail/error behavior for NaN, infinity or empty pools;
- Wilson formula/confidence level, exactly 10,000 paired source-ID bootstrap
  resamples, deterministic resampling seed/derivation, quantile convention,
  effect definition, seed aggregation and the exact Holm hypothesis family;
- method-specific identities: Kairos/Pair-MLP bind the untouched candidate
  manifest and receive candidate-recall/no-gold diagnostics; SFT instead binds
  its prompt/decoder manifest and marks candidate-only diagnostics `N/A`.

All three methods may still be compared on the same final normalized answer and
relation metrics, but method-inapplicable candidate diagnostics must not be
fabricated or included in a pooled average.

### R2-P1-02 — the SFT target byte order contradicts project canonical JSON

**Evidence.** Stage 5 calls the SFT target a canonical JSON object with ordered
keys `answer`, `original_relation`, `counterfactual_relation`. The repository's
`kairos.ids.canonical_json` uses `sort_keys=True`, which serializes these keys as
`answer`, `counterfactual_relation`, `original_relation`. Because causal-LM
targets are byte/token sequences, this is a material ambiguity rather than a
cosmetic object-order difference.

**Executable fix.** Select exactly one serializer before any model output.
Prefer the existing `kairos.ids.canonical_json`, explicitly freeze the resulting
key order `answer,counterfactual_relation,original_relation`, no trailing LF,
UTF-8 and the exact five relation label strings. Alternatively introduce a
separately named serializer with golden byte fixtures and a versioned hash; do
not call the non-sorted order project canonical JSON. Bind serializer/version
and exact target-byte hash rules in the SFT run-input manifest.

### R2-P1-03 — selected physical GPU identity is not fail-closed

**Evidence.** The plan records a selected physical GPU and sets
`CUDA_VISIBLE_DEVICES`, but it does not freeze `CUDA_DEVICE_ORDER`, bind a GPU
UUID/PCI bus ID or verify after CUDA initialization that logical device 0 is the
same physical device that passed the resource gate. An inherited enumeration
order can therefore map a numeric index to a different, possibly occupied GPU.

**Executable fix.** Set `CUDA_DEVICE_ORDER=PCI_BUS_ID` and preferably set
`CUDA_VISIBLE_DEVICES` to the selected GPU UUID rather than an unqualified
numeric index. Persist UUID, PCI bus ID, index, total/free memory and driver in
the resource record. Immediately after CUDA initialization, require exactly one
visible CUDA device and verify its UUID/PCI identity and capacity against that
record before model allocation. Any mismatch stops without probing additional
GPUs, killing processes or retrying another device.

## Round 2 approval gate

A third audit may mark `APPROVED` only after all four fixes appear in the plan,
D-040 and exact tracked contract files, their hashes match the worktree bytes,
and the execution order freezes them before all internal-dev output. The prior
acceptable residual risks remain valid; no new residual risk is accepted for
the four blockers above.

# Formal Training Execution Plan — Independent Audit

## HISTORICAL ROUND 1 VERDICT

`BLOCKED`

The plan has good path, no-replace, clean-commit, resource-gate and failure-
preservation intentions, but it is not yet safe to execute as a formal or
paper-eligible experiment. Four P0 and six P1 findings below are unresolved.
No candidate generation, production model load, GPU smoke, formal plan
publication or training may begin until all P0/P1 items are fixed in the plan,
governing decisions and tests. A synthetic-only implementation of a corrected
audit publisher may begin only after P0-01 and P0-02 are resolved in writing.

This audit inspected governance, aggregate audit facts, schemas and source
interfaces only. It did not adjudicate any review item or use sample text.

## P0 — blocking correctness or provenance defects

### P0-01 — two-person independent human provenance is not demonstrated

**Evidence.** The frozen experiment design requires two humans to complete the
200-item audit independently and lock their submissions before comparison
(`docs/experiments/README.md`, data-quality section). The plan calls the two
files “verified human inputs” based on canonical shape, source order and hashes
only (`formal-training-execution-plan.md`, lines 9--14). The files are named
`user-checked_formal-A/B`, were introduced together by commit `4d0cfa1`, and no
allowed provenance record currently binds two distinct reviewer identities,
independent completion declarations, or the two pre-comparison lock times and
hashes. Schema validity and perfect equality cannot establish independent
human review.

**Required plan text.** Replace the current “verified human inputs” claim with:

> Formal A/B bytes are structurally verified but human independence remains
> unverified until a private provenance record binds two distinct pseudonymous
> human reviewers, each reviewer’s independent-completion declaration, export
> time, pre-comparison SHA256, reviewer slot, packet manifest SHA256 and audit-
> items SHA256. The two locked hashes must match the exact bytes consumed by
> D-035. If this provenance cannot be supplied, the audit remains
> `USER_ATTESTED / INDEPENDENCE_UNVERIFIED`; only development training is
> allowed and no result may be called a formal human audit or paper-eligible.

The provenance record must not contain sample text, real names, secrets or
free-form review notes. A single person duplicating or confirming both slots is
not two-person independent review.

### P0-02 — automatic “authors adjudication” violates D-035

**Evidence.** Plan Stage 1 says the adapter constructs adjudication whenever A/B
agree (lines 52--56). D-035 states that adjudication is produced after A/B are
locked, that only human authors select disagreements, and that the program
validates but does not produce adjudication (`decisions.md`, D-035). The current
evaluator requires caller-supplied adjudication bytes and only validates them
(`relation_audit_results.py`, `_adjudication_values` and
`evaluate_audit_submissions`). A deterministic projection is statistically
harmless when all labels agree, but it is not an author-created adjudication
and must not be attributed as one.

**Required plan text.** Replace Stage 1 item 2 with one of these two explicit
contracts before implementation:

> Preferred: consume a separately locked, author-created adjudication file;
> never synthesize it. Verify that every agreement is preserved and stop on
> every unresolved disagreement.

or, if the authors intentionally require no redundant manual file:

> Freeze D-038 to introduce an algorithmic `agreement-projection` artifact,
> distinct in schema, filename and provenance from authors adjudication. It may
> exist only when A/B have zero overall disagreements, must be a pure canonical
> projection of the locked A/B labels, and must be reported as algorithmic, not
> human adjudication. Update the D-035 adapter/result schema and tests
> atomically; never silently pass generated bytes as authors adjudication.

### P0-03 — the plan trains on all 366 records and omits the frozen dev split

**Evidence.** The frozen experiment design requires a stable source-ID 10%
internal-dev split and prohibits an original/CF pair from crossing splits
(`docs/experiments/README.md`, line 24). Plan Stages 3--4 generate/build a
training corpus for all 366 records (lines 83--107). The existing
`TrainingCorpusBinding` accepts only one official-train corpus and has no
partition identity; its plan executes every bound example for all three epochs
(`training_plan.py`, `TrainingCorpusBinding` and `TrainingPlan`). As written,
the nominal internal-dev examples enter the optimizer, invalidating validation
and inviting test-like tuning.

**Required plan text.** Add before candidate generation:

> Publish an immutable partition manifest using the already frozen source-ID
> stable-hash rule. It must bind all 366 records, exact train/internal-dev IDs,
> counts, order and hashes; one source and its original/CF pair may occur in
> exactly one partition. Freeze the partition before observing any model output.
> Training plans bind only the train partition. Internal-dev is never consumed
> by an optimizer, never receives gold injection, and has a separate prediction
> and metric artifact. Any official-test artifact is separate and remains
> untouched until its construction/evaluation contract is committed.

Candidate generation may cover both partitions only if the two partitions and
their gold-access policies remain separately bound and replayable.

### P0-04 — no paper-eligible evaluation protocol exists

**Evidence.** Stage 5 describes training and says “metrics replay” (lines
124--137) without defining an evaluation dataset, checkpoint-selection rule,
prediction schema, primary metrics, candidate recall, no-gold policy or paired
unit. The only formal data proposed in Stage 2 is official-train relation-only
data. The frozen design instead assigns GSM8K temporal primary evaluation to
official test, requires candidate recall and no-gold-injection sensitivity,
and makes Kairos versus the strongest same-supervision baseline the primary
comparison. Training loss or internal-dev tuning is not an experiment result.

**Required plan text.** Insert a stage before formal training that freezes:

> (a) final-checkpoint versus validation-selection policy; (b) a strictly held-
> out evaluation artifact and split; (c) gold-blind evaluation candidates; (d)
> exact original-answer and relation/CF-relation metrics permitted by relation-
> only v1; (e) candidate recall and no-gold-injection sensitivity; (f) per-item
> prediction identity and paired comparison units; and (g) immutable prediction,
> metric and statistics publishers/verifiers. CF-answer/update/stability/
> consistency metrics remain prohibited. If only internal-dev evaluation is
> available, label outputs `INTERNAL-DEV / NOT PAPER-ELIGIBLE`; do not call the
> training run a verified reproduction result.

## P1 — blocking implementation, fairness or server-safety defects

### P1-01 — formal review data are committed despite the repository policy

**Evidence.** Plan Stage 1 deliberately binds “Git-tracked” A/B data. Both JSONL
files are tracked even though `.gitignore` excludes
`src/ab-reviewer-web/results/*`; that directory’s README says actual JSONL and
sidecars do not enter Git. `docs/git/README.md` also prohibits committing data.
The worktree files are mode 0600 while Git records only mode 100644, so private
mode is not reproducible from a checkout. The pushed history already contains
the files and cannot be repaired by forbidden history rewriting.

**Required plan text.** State that raw formal A/B inputs live under a new
mode-0700 private `/data0/hk_data/kairos-zx/...` intake artifact with mode-0600
files, no symlinks/hardlinks, no replacement and full hashes. Git stores only
aggregate facts and hashes. Remove the raw files from the branch tip in an
ordinary future commit without rewriting history, record the pre-existing
exposure, and do not add further human-review bytes to Git. Require an explicit
owner decision if the existing remote exposure is unacceptable.

### P1-02 — current v1 plan/checkpoint schemas cannot bind the claimed chain

**Evidence.** Plan Stage 4 requires every plan/checkpoint to include formal
data, candidate, audit and model manifest hashes (lines 106--111). Current
`TrainingCorpusBinding` contains only one source-manifest hash; the plan-artifact
manifest repeats only that source identity. Candidate bindings carry content
and origins but no candidate-artifact manifest identity. The v2 checkpoint has
one plan/data manifest hash and the fixed model `SHA256SUMS` identity. Therefore
the existing exact-schema verifiers cannot encode or replay the chain promised
by the plan.

**Required plan text.** Freeze a versioned schema migration before production
publication. The training-plan semantic value (preferred) or a separately
verified immutable run-input manifest must bind full SHA256 values for audit
manifest/result/provenance, formal data and partition manifests, candidate
manifest/raw-evidence manifest, tokenizer/config/prompt, model manifest and
execution commit. The checkpoint must bind the semantic hash of that complete
object. Parser/verifier tests must reject omission, substitution, cross-seed or
cross-core reuse and every one-field hash mutation. Do not claim the existing
v1 plan/v2 checkpoint already meets this requirement.

### P1-03 — candidate generation is under-frozen and has no hard resource budget

**Evidence.** Stage 3 leaves the sampling seed mapping, prompt bytes, maximum
input/new tokens, batch size, decoding EOS/padding behavior, invalid-output
acceptance threshold, output byte ceiling and projected GPU/disk budget to the
future implementation. “Seed-bound”, “bounded preflight” and “stop on failure”
are not replayable settings. Output-driven choices at this stage could alter
candidate recall and the training task.

**Required plan text.** D-039 must freeze before any real query is read by the
model: one candidate-pool seed shared by all training seeds (or an explicit
per-seed mapping shared across methods), exact prompt/template bytes and hash,
parser, `max_input_tokens`, `max_new_tokens`, batch size, sample positions,
temperature/top-p, RNG derivation, EOS/pad IDs, attention implementation,
invalid-output representation, abort thresholds and per-file/whole-artifact
byte ceilings. Set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`local_files_only=True`, explicit project caches/temp paths and
`TOKENIZERS_PARALLELISM=false`. The 8-record smoke may test mechanics only and
must not be used to tune the prompt/parser or thresholds.

### P1-04 — runner resume, checkpoint cadence and run finalization are undefined

**Evidence.** The current executor supports optimizer-boundary cursors, and
`execute_planned_training_steps` requires a sequence with the full plan length
while dereferencing only the active window. Stage 4 says “current micro-batch”
and “optimizer-boundary resume” but does not define the lazy sequence adapter,
checkpoint cadence, immutable checkpoint IDs, resume selection, trace
continuity, crash state or final run-manifest ordering. Epoch boundaries need
not coincide with optimizer boundaries.

**Required plan text.** Freeze a finite optimizer-step window and checkpoint
cadence expressed in optimizer steps, not epochs. Define deterministic IDs,
explicit user/manifest-selected resume checkpoint (no mutable `latest`
symlink), pre-state resume verification, trace prefix/hash continuity and
manifest-last run finalization. The lazy materializer must report full plan
length, dereference only the validated active indices, and prove in tests that
future slots are not materialized. Interrupted/failed targets remain immutable
and receive a separate bounded failure record; they are never resumed in place
or promoted.

### P1-05 — the main same-supervision baseline is optional in the plan

**Evidence.** Frozen H1 and the reviewer-response plan require Kairos against
the strongest same-supervision baseline, including Same-data SFT and Pair-MLP.
Stage 5 schedules Kairos and Pair-MLP, but says Same-data SFT is implemented only
“if it is still absent”. This cannot complete the planned primary comparison
and permits a favorable but incomplete comparison set.

**Required plan text.** Make Same-data SFT a mandatory separately frozen,
implemented and tested method before the matched comparison is called complete.
Freeze its exact targets, prompt/decoder, trainable parameters, optimizer,
candidate use (if any), evaluation parser and model revision. Kairos, Pair-MLP
and Same-data SFT must use the same eligible train/dev identities, seeds and
gold-access policy wherever method semantics allow. Preserve all negative
results. If SFT is deferred, the primary reviewer claim remains `DEFERRED` and
Kairos-versus-Pair-MLP is explicitly secondary.

### P1-06 — resource and determinism gates are descriptive, not executable

**Evidence.** The safety envelope names global ceilings but does not require a
project disk-usage ledger, output-size projection, environment variables that
enforce CPU/thread limits, offline loading, deterministic-kernel policy, or a
record of CUDA/Torch/driver/device identity. The existing real-model smoke used
about 15.9 GB allocated GPU memory, but it does not establish full-run disk,
host-RAM or reproducibility bounds.

**Required plan text.** Before every generation/smoke/training attempt, persist
a read-only resource-gate record containing `nvidia-smi`, `free -h`, `df -h`,
selected physical GPU and its free memory, current project disk usage,
worst-case new bytes and the decision. Export explicit `CUDA_VISIBLE_DEVICES`,
`OMP_NUM_THREADS`, `MKL_NUM_THREADS`, tokenizer/DataLoader workers and all cache/
temp paths. Freeze and record Torch/Transformers/PEFT/CUDA/driver/device,
attention implementation, deterministic-algorithm policy and RNG derivation.
Run only one foreground formal job at a time. If any estimate breaches 4 GPUs,
16 CPU threads, 8 workers, 64 GiB task RAM, 80 GiB new project data or the
120-GiB `/data0` floor, stop without deleting or killing anything.

## P2 — non-blocking improvements after P0/P1 remediation

1. Replace shortened hashes in the governing D-038/D-039 decisions and formal
   manifests with full lowercase SHA256 values; shortened hashes may remain
   only in prose summaries.
2. Reconcile stale statements in `docs/experiments/README.md`, D-037,
   `verify-addExp.md`, registry and older checkpoints that still say formal A/B
   bytes are absent. Preserve historical wording as historical evidence, but
   add dated superseding status rather than silently rewriting history.
3. Report a confidence interval for the 196/200 validity estimate. The point
   estimate passes the frozen threshold, but a sampled audit does not prove all
   366 retained records are valid.
4. At each high-resource milestone, verify the actual model files against the
   retained `SHA256SUMS`, not only the checksum file’s own hash, and bind the
   verification result to the run-input manifest.
5. Define run-ID collision behavior and bounded log sizes explicitly. A target
   collision must stop; it must not trigger deletion, overwrite or an automatic
   alternate ID that loses the intended identity.

## Mandatory pre-execution gates

All items below must be true before the named boundary:

1. **Before any production implementation:** this audit’s P0/P1 items are
   resolved in the execution plan and new D-038/D-039 decisions; the corrected
   plan is committed, pushed, and `CURRENT.md` points to that clean HEAD.
2. **Before formal audit publication:** two-person independence provenance or
   an explicit development-only downgrade is recorded; adjudication semantics
   follow P0-02; private source paths, hashes, modes and exact schemas replay.
3. **Before formal data/candidate publication:** the audit artifact is `PASSED`,
   the 366-record derivation and 10% partition replay from immutable sources,
   and train/internal-dev namespaces and gold policies are distinct.
4. **Before model load:** complete model/tokenizer hashes replay; D-039, prompt,
   parser, seed mapping, hard token/byte budgets and offline/cache environment
   are committed; Git is clean and local branch/HEAD/upstream are synchronized.
5. **Before production plans:** the versioned full provenance chain in P1-02 is
   implemented and tamper-tested; only train identities enter optimizer plans.
6. **Before the GPU optimizer smoke:** focused and full CPU suites pass from the
   clean implementation commit; the no-optimizer real-record smoke is a
   separate development artifact; a fresh resource gate passes.
7. **Before formal training:** runner resume/failure/finalization tests pass,
   held-out evaluation and Same-data SFT disposition are frozen, all run-input
   artifacts replay, one idle GPU is selected, and no other project formal job
   is active.
8. **Before `VERIFIED` or paper use:** checkpoint, prediction, metrics and
   statistics replay from exact hashes; evaluation was gold-blind and held out;
   three seeds and required matched baselines are complete; all negative and
   failed runs are registered; no prohibited CF-answer metric is present.

## Acceptable residual risks after remediation

- Human independence is ultimately attested rather than cryptographically
  provable; the project can preserve declarations and pre-comparison hashes but
  cannot prove reviewers’ cognitive isolation.
- The stratified 200/370 audit estimates construction validity; unaudited
  records may still contain errors, and 196/200 does not imply 100% validity.
- The relation-only dataset is small and explicit-marker-biased. Even a correct
  formal run has limited power and cannot establish CF-answer/update claims or
  broad temporal generalization.
- CUDA generation/training may not be bitwise portable across devices or
  software stacks. Immutable outputs, exact environment records and three seeds
  make the result auditable but do not guarantee cross-hardware identity.
- Raw A/B bytes already exist in pushed Git history. Removing them from the
  branch tip does not erase that history; history rewrite remains prohibited.
- External-dataset source/network blockers remain outside this narrow training
  path and must remain visible as `DEFERRED`, not be silently treated as solved.
