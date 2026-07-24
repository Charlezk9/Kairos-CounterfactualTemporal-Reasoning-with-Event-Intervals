# Remaining Reviewer-Response Execution Plan

- status: `FROZEN / EXECUTING / PARTIAL`
- date: 2026-07-24 CST
- branch: `experiment/reproduction-additional-evaluation`
- plan_parent_commit: `7bdecae61642c883e739422ee1f17999c7c2c786`
- execution_mode: single agent
- production_training: blocked pending human audit

Execution update (2026-07-24): the planned Rule-Graph/Constraint-Rerank item is
now `VERIFIED / EXACT SCORE TIE`; its unique evidence is
`phase-03-torque-rule-graph-baseline.md`. This does not close the main
same-supervision gap: both human review templates remain blank, so Kairos,
Pair-MLP and Same-data SFT production training are still prohibited.

## Objective and claim boundary

The remaining work must answer the reviewers with traceable evidence rather
than attempt to recreate unavailable author artifacts. This remains an
independent reimplementation: author code, temporal-subset IDs, complete
prompts, candidate pools, templates and training configuration are absent.

The critical path is an audited counterfactual supervision source, formally
trained Kairos and matched-supervision baselines, and evaluation on a standard
temporal benchmark. 2Wiki recovery runs in parallel and must not delay the
TORQUE critical path. The supported claim is limited to relation update and
counterfactual temporal consistency under event-order shifts; this project does
not claim general temporal-QA state of the art.

No value from the PDF or TeX becomes verified without a registered run. The
conflicting PDF/TeX Kairos values remain `REPORTED / UNVERIFIED`.

## Reviewer-to-evidence gap matrix

| Reviewer concern | Manuscript limitation | Verified current state | Required closure evidence |
|---|---|---|---|
| Non-standard temporal subsets | Four unpublished temporal subsets are under-specified | TORQUE and TimeQA sources plus prompt baselines are verified | Trained Kairos and matched baselines on TORQUE; 2Wiki when provenance succeeds |
| Weak/asymmetric baselines | Kairos is trained while the main comparisons are prompt-only | LLM-Graph is a verified negative run; Rule-Graph exactly ties Direct; Pair-MLP is synthetic-only; Same-data SFT absent | Same-data SFT, Pair-MLP and Kairos share data/candidates/metrics and run three seeds |
| Under-specified construction | Subset IDs, full templates and author configuration are unavailable | GSM8K v0 retains zero; relation-only v1 has 370 train pairs and no CF answer | Construction funnel, complete provenance, answer-bearing v2 or explicit claim withdrawal, and human validity evidence |
| Marker/template artifacts | Rule labels depend on explicit markers | No explicit/implicit or answer-unchanged analysis exists | Frozen explicit/implicit split, paraphrased perturbations and answer-unchanged distractors |
| Gold candidate advantage | Training adds gold while evaluation reranks generated candidates | Candidate generation exists only for prompt runs | Candidate recall and no-gold-injection sensitivity using the shared pool |
| Interval interpretability | Start/end coordinates are asserted but not demonstrated | Tensor core only; no trained checkpoint | Real interval/graph cases, geometry diagnostics and registered ablations |
| Short/controlled contexts | Long-document generalization is unclear | TimeQA strict runs are dominated by format failure | Gold-blind, preregistered output-contract follow-up plus length/event-count analysis |
| Reproducibility | PDF/TeX values conflict and artifacts are unavailable | Local implementation and formal prompt runs are traceable | Replace or explicitly mark unsupported tables; bind every retained value to run/commit/hash |

## Stage 0: state and protocol freeze

1. Reconcile `CURRENT.md` with the real Git HEAD before the next formal run.
2. Append a decision that freezes this matrix, the 2Wiki source order, the
   TimeQA follow-up boundary and the rule that relation-only data cannot support
   counterfactual-answer claims.
3. Keep completed TORQUE/TimeQA prompt runs immutable. No result-driven prompt,
   parser or metric changes may overwrite an existing primary result.
4. Record the plan and each later milestone with an ordinary Git commit; never
   force-push or rewrite shared history.

Exit criterion: state, decision and plan agree; Git is clean; no run is active.

## Stage 1A: bounded 2Wiki recovery

2Wiki source attempts are ordered before any response body is inspected:

1. Official April 2021 corrected object referenced by the author repository:
   legacy URL `https://www.dropbox.com/s/ms2m13252h6xubs/data_ids_april7.zip`,
   then its observed official SCL route
   `https://www.dropbox.com/scl/fi/32t7pv1dyf3o2pp0dl25u/data_ids_april7.zip?rlkey=u868q6h0jojw4djjg7ea65j46`.
   `dl=1` and the Dropbox content-delivery host are transport routes to the
   same object, not independent sources.
2. Official older `data_ids.zip` object referenced by the same repository:
   `https://www.dropbox.com/scl/fi/aasqsj45yokx71pnm8ctr/data_ids.zip?rlkey=72n2p6jywhfmm6kdeuzz8c55u`.
3. Official original `data.zip` object:
   `https://www.dropbox.com/scl/fi/heid2pkiswhfaqr5g0piw/data.zip?rlkey=ira57daau8lxfj022xvk1irju`.
4. Pinned unofficial recovery mirror
   `xanhho/2WikiMultihopQA@6ef4eb1bc94ca4a768bb86809fafe777ad795995`
   only if every available split passes full semantic equivalence over IDs,
   questions, answers, contexts, supporting facts and evidences. A transformed
   Parquet mirror cannot be accepted from a sample check or matching counts.

Each request is foreground, bounded and preceded by `nvidia-smi`, `free -h`
and `df -h`. Curl configuration, netrc and user config stay disabled; HTTPS and
the documented Dropbox/Hugging Face hosts are allow-listed. Each attempt
records request identity, redirect chain, effective URL, response status,
bytes, SHA256 and terminal state without logging dataset content.

An official older revision is not silently relabeled as the April revision.
An unofficial mirror is `RECOVERY_REFERENCE` until a canonical per-split
semantic hash proves equivalence. On mismatch it remains excluded from formal
experiments. Existing failed artifacts are preserved.

Exit criterion: either a verified official/equivalent source with immutable
manifest, license, safe archive tree, schema and split statistics, or a precise
`DEFERRED / SOURCE_UNVERIFIED` record.

## Stage 1B: supervision validity

1. Two human authors independently complete the existing 200-pair blind
   relation audit. AI must not populate, infer or adjudicate human fields.
2. Lock reviewer submissions before comparison and compute Cohen's kappa and
   adjudicated validity. Required thresholds remain kappa >= 0.80 and validity
   >= 95%; failure requires revised rules and a new sample.
3. Treat the current 370 relation-only pairs as original-answer, relation and
   CF-relation supervision only. They never support CF-answer accuracy,
   update, stability or consistency.
4. Freeze a separate answer-bearing v2 construction contract before coding.
   It must record answer-changing versus answer-unchanged cases, deterministic
   updated answers, split isolation, complete funnel statistics and a human
   audit that includes answer validity. If reliable updated answers cannot be
   constructed, withdraw the answer-update training/effect claim rather than
   copying the original answer or fabricating labels.
5. StrategyQA safe extraction and MuSiQue trusted-path remediation are parallel
   full-reproduction work; neither may weaken the existing archive or trusted-
   ancestor policy.

Exit criterion: audited data appropriate for the exact claimed losses, or an
explicitly narrowed relation-only experiment and manuscript claim.

## Stage 2: resumable synthetic training execution

Implement the current safe action without production records or 7B weights:

- optimizer groups: LoRA `2e-5`, temporal heads `2e-4`, weight decay `0.01`;
- effective batch 32 with explicit micro-batch/accumulation accounting;
- BF16/AMP contract, gradient clip 1.0, 5% warmup and at most three epochs;
- seeds 13, 42 and 2026 with Python/Torch/CUDA/dataloader RNG state;
- deterministic sample order and exact resume cursor;
- manifest-bound, no-replace checkpoint publication with model, optimizer,
  scheduler, scaler, RNG, config, source commit and hashes;
- strict resume verification before state mutation.

First prove uninterrupted versus interrupted/resumed equivalence on CPU
synthetic data. Then add PEFT injection and perform one resource-gated GPU
single-batch development smoke from a clean commit. This stage does not grant
production-training permission.

Exit criterion: focused and full tests pass, resume equivalence passes, no
production data/model result exists, and the checkpoint is committed.

## Stage 3: matched formal experiments

After the applicable human/data gate passes, freeze one shared candidate pool,
data revision, parser and metric contract and run:

- Kairos;
- Same-data SFT without interval/relation graph/graph-aware scoring;
- Pair-MLP with the same supervision and downstream scorer as Kairos;
- Rule-Graph/Constraint-Rerank as a non-neural structured baseline.

Use seeds 13/42/2026. The primary comparison is Kairos against the strongest
same-supervision baseline, not against prompt-only methods. Existing Direct,
CoT, Self-Consistency, CoT+Verifier and strict LLM-Graph runs remain frozen and
are not repeated merely to seek a better result.

Also run no-gold-injection sensitivity, candidate recall and the four frozen
ablations: without relation supervision, interval projection, counterfactual
supervision and answer graph scoring.

Exit criterion: each formal run starts from a clean commit, has a complete
manifest/prediction/metric/checkpoint chain, passes offline replay and is
registered whether positive or negative.

## Stage 4: standard-benchmark and artifact analyses

1. Evaluate trained Kairos and matched baselines on TORQUE public dev.
2. Add a TimeQA follow-up only under a gold-blind output contract frozen from
   synthetic or independent validation evidence. Preserve Direct/CoT strict
   primary format-failure results and label the follow-up separately.
3. Evaluate 2Wiki dev only after Stage 1A provenance acceptance.
4. Report explicit-marker versus implicit/weak-marker strata, paraphrased
   perturbations, answer-unchanged distractors, context length and event count.
5. Produce 2--3 interval/graph case studies and failures covering event
   extraction, implicit relation, wrong answer grounding, spurious flip and
   long-context confusion. Case selection must use a frozen rule rather than
   cherry-picking favorable examples.
6. Aggregate mean/std and paired 10,000-resample bootstrap intervals with Holm
   correction and effect sizes under the existing metric definitions.

Exit criterion: every table cell has dataset revision, split, N, seed, metric,
run ID, source commit and artifact hashes; negative and format-failure results
remain visible.

## Stage 5: author report and manuscript disposition

Update `docs/verify-addExp.md` with the reviewer-to-evidence mapping,
construction funnel and audit statistics, matched-baseline results, standard-
benchmark results, statistical tests, interval cases and failure analysis.
Only `VERIFIED` values enter manuscript recommendations.

Unsupported PDF/TeX tables must be removed, replaced with verified independent
reimplementation results or visibly marked as unreproduced. The final wording
must distinguish prompt-only, matched-supervision and structured baselines and
must not describe their comparison as one symmetric setting.

Exit criterion: a coauthor can update the paper using Git plus registered
artifacts without relying on chat history.

## Priority and stop rules

The minimum reviewer-response path is:

1. supervision audit/claim boundary;
2. resumable trainer;
3. Kairos + Same-data SFT + Pair-MLP;
4. TORQUE evaluation and fair comparison;
5. marker/artifact and interval/failure analyses;
6. 2Wiki and the remaining original datasets for completeness.

Stop rather than improvise when `/data0` has less than 120 GiB free, a source
cannot be provenance-verified, the human gate is incomplete, a requested action
would weaken a safety policy, or an experiment would consume test output to
select a parser, source, split or hyperparameter.
