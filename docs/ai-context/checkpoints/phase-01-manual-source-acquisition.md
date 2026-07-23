# Phase 01 Manual Official-Source Acquisition

- status: `PARTIAL / TWO_SOURCES_EXTRACTED`
- execution_commit: `7eca38ec94586678d571cb14f9f2e2297335e433`
- date: 2026-07-23 CST
- GPU/model/upstream-code execution: none
- network concurrency: 3 initial fixed-source downloads, then one 2Wiki attempt

## Shared gates

All writes stayed below `/data0/hk_data/kairos-zx/data/raw/<dataset>/<revision>`.
The resource gate reported about 156 GiB free on `/data0`, above the 120 GiB
stop threshold. Downloads used curl with user configuration disabled, HTTPS
only, fixed official URLs, bounded connect/total time and an OS file-size
limit. Archives and headers are mode 0600 under mode-0700 revision roots.
No upstream script, notebook, evaluator, model, GPU job, clone, submodule or
hook was executed.

Each revision contains a canonical `acquisition-manifest.json` with no sample
content. Raw data and manifests remain outside Git.

## StrategyQA

- status: `STAGED_ARCHIVE_POLICY_BLOCKED`
- official URL: `https://storage.googleapis.com/ai2i/strategyqa/data/strategyqa_dataset.zip`
- HTTP: 200, `application/zip`, 3,434,332 bytes
- ETag: `f4ae9d9296c06f90d80aee1e4a25d58a`
- archive SHA256: `4911d85eb6721a93bed7645419df77e721808b32b9785dee14ad80e6249e0a90`
- manifest SHA256: `464a14091f047ccdd95d6036464176baa101f8cfc3c468ddac2a0d5964f47c0e`

The official ZIP uses data descriptors. The existing conservative
`kairos.archive_safety` policy rejects data descriptors before extraction, so
the archive is retained but was not extracted. This is not a corrupt-download
finding. A separately reviewed ZIP parser policy is required; do not weaken the
generic archive guard in place.

## TORQUE

- status: `EXTRACTED_SCHEMA_OBSERVED`
- fixed revision: `ab27019cc6a317fde3c879900499f02acce8b16d`
- archive SHA256: `7284c675f0cf21ddb1272c31919d4453d2fb53a426e88b46ad6a9a0fd9030cd0`
- archive bytes/members/declared expansion: 1,920,338 / 28 / 22,163,721
- manifest SHA256: `e01f87df92daf0378ac126b83c3d596a01a04f281dc35567b305d720f70386e3`
- LICENSE SHA256: `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`

The held-FD archive safety inspection and extraction passed. Public dev has
145 passages and 1,483 question-answer pairs with answer-bearing keys. The
fixed dev file SHA256 is
`7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`.
`question_clustering.json` has 2,855 top-level records and SHA256
`7d20248ab1c08603a22cc1ce4d7419803394040c74146f728970ce9cddb351f9`.
The local test has 443 passages/4,468 question metadata entries but no answer
field, confirming it is not usable for evaluation. Only dev is eligible.

## TimeQA

- status: `EXTRACTED_SCHEMA_OBSERVED`
- fixed revision: `38b05989070c1168b2bef3d5a2656afeeba763dc`
- archive SHA256: `f0df52a31e9d4bb0d5b7577d9e0131740bd017d2aad1e9b4bee7756bfecdfd07`
- archive bytes/members/declared expansion: 128,861,667 / 40 / 454,095,594
- manifest SHA256: `8212a7826b0fadf6b0454f79c52bc6b3440d487af860c53456891efbec2e50a3`
- LICENSE SHA256: `ba5d7b48847d18655a1a552dc6ec6b44bd7f5782b1a775e293f65250f3dd7440`

The held-FD archive safety inspection and extraction passed. The planned
`dataset/human_test.hard.json` is actually LF-delimited JSON rather than one
JSON value. It contains 989 records, all with exact keys
`context, idx, paragraphs, question, targets`; the file SHA256 is
`0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`.
This is source/schema evidence, not an evaluation result.

## 2WikiMultihopQA

- status: `TRANSFER_FAILED / NO_HTTP_RESPONSE`
- fixed corrected URL: `https://www.dropbox.com/s/ms2m13252h6xubs/data_ids_april7.zip`
- fixed revision: `13800e5be57df1b4040b9b1588c6c811779e69e9`
- curl exit: 28 after 20-second connect timeout
- header bytes: 0; archive bytes: none
- manifest SHA256: `2013e6e465901c59c32719293e123e43ba4bfbaf0ac68bb003fe87248fd210db`

No retry, query modification, old-archive fallback or mirror was used. This is
not evidence that the source is permanently unavailable.

## Next gate

Implement fixed, read-only adapters and metric contracts for TORQUE dev and
TimeQA-Hard using only the bound files above. The adapter tests must use
synthetic fixtures; formal evaluation remains forbidden until prediction
manifests and metric definitions are committed. StrategyQA and 2Wiki remain
blocked, and MuSiQue's trusted-ancestor policy remains unchanged.
