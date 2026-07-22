# Phase 01 TimeQA Official Source Discovery

- status: `BLOCKED_TOOLING / NO_PRE_FETCH_REDIRECT_AND_BYTE_GATES`
- metadata disposition: `METADATA_ONLY / README_LICENSE_AND_ARXIV_LANDING_READ`
- branch: `experiment/reproduction-additional-evaluation`
- discovery/audit base HEAD: `903684181f6a936650e6c1ff2488f1d12ad5a957`
- snapshot/acquisition plan and audit base HEAD: `e301d576843cf13768b317d34f34c5192c348c72`
- snapshot/acquisition plan disposition: `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`
- active run IDs: none
- running processes: none
- scope: documentation-only fixed-revision repository metadata, official arXiv landing metadata, routing-failure evidence and a non-executed direct-PDF plan

## Fixed repository provenance

- repository: `https://github.com/wenhuchen/Time-Sensitive-QA`
- revision: `38b05989070c1168b2bef3d5a2656afeeba763dc`
- pinned README read:
  `https://raw.githubusercontent.com/wenhuchen/Time-Sensitive-QA/38b05989070c1168b2bef3d5a2656afeeba763dc/README.md`
- pinned LICENSE read:
  `https://raw.githubusercontent.com/wenhuchen/Time-Sensitive-QA/38b05989070c1168b2bef3d5a2656afeeba763dc/LICENSE`
- official arXiv landing read: `https://arxiv.org/abs/2108.06314`
- project-planned evaluation path: `dataset/human_test.hard.json`

The planned evaluation path is only `PROJECT_PLANNED`. Its existence, bytes,
SHA256, count, schema, gold completeness and license have not been locally
observed or verified.

## README-reported metadata

The pinned README describes `dataset/` as containing the data. It describes
`dataset/annotated*` as crowd-annotated passages and time-evolving facts, and
describes train/dev/test as synthesized-template easy/hard splits. It names
`human_hard` as an evaluation mode, not as a locally verified file. The README
states that the data and code are released under BSD 3-Clause. These statements
are `README_REPORTED`; no tree, data file, script, model or sample was opened
to verify them.

The README names and labels do not establish actual file existence, exact
member names, split counts, schema, easy/hard semantics or evaluator behavior.
No fact from an unvisited path is promoted beyond `README_REPORTED`.

## LICENSE evidence

The fixed LICENSE contains BSD 3-Clause terms and `Copyright 2021 Wenhu Chen`.
This is `LICENSE_EVIDENCE` for the fixed repository document. The discovery did
not map that license to any specific data, annotation, script or model file, so
per-file and data-license applicability remain `UNVERIFIED`.

## Official arXiv landing metadata

The official arXiv landing identifies *A Dataset for Answering Time-Sensitive
Questions* by Wenhu Chen, Xinyi Wang and William Yang Wang; version v1 is dated
2021-08-13, version v5 is dated 2021-10-25, and the venue is the NeurIPS 2021
Datasets and Benchmarks Track. It gives DOI
`10.48550/arXiv.2108.06314`. The landing reports approximately 150K facts,
5.5K candidates and about 20K question-answer pairs, and reports FiD at 46%
and human performance at 87%.

All of these title/author/version/venue/DOI and scale/result statements are
`ARXIV_LANDING_REPORTED` only. They are not split counts, local observations,
reproduced experiments, verified metrics or claims about
`dataset/human_test.hard.json`.

No other landing-page statement is adopted as a data/schema/result fact.

## Rejected ar5iv route

An earlier approved “View PDF” navigation did not deliver an official arXiv
PDF. It routed to an ar5iv HTML endpoint and is classified
`ROUTING_POLICY_FAILURE / OUT_OF_SCOPE_REDIRECT`. The ar5iv HTML body/content
was discarded and no fact from that response was adopted. No ar5iv statement,
number, definition, table, page reference or sample may be cited or used
downstream.

In particular, this checkpoint contains no adopted Table 1 values, easy/hard
body definition, paper-body schema, paper-body metric/table result, PDF byte or
page claim, or example text. None may be reconstructed from memory or the
rejected route.

## Direct official-PDF plan and tooling disposition

The unexecuted direct candidate is
`https://arxiv.org/pdf/2108.06314.pdf`. A valid read would require pre-fetch
enforcement of an exact `https://arxiv.org` host and paper ID, a closed
same-host PDF-only redirect allowlist, HTTP 200, normalized
`application/pdf`, `%PDF-` magic, a byte cap and title/author identity before
any PDF-body fact is accepted. Any ar5iv/third-party redirect, HTML, ID
mismatch, unexpected content type or magic mismatch must stop without adopting
content.

The available Web navigation does not expose sufficient pre-fetch redirect
and byte gates before following/reading the response. The direct plan was not
executed and is `BLOCKED_TOOLING / NO_PRE_FETCH_REDIRECT_AND_BYTE_GATES`.
There is no accepted PDF-body evidence, PDF byte identity, page citation,
table result, easy/hard body definition, schema or PDF-body metric evidence.

## Unverified boundaries and next gate

The fixed-revision tree, actual `dataset/` files, the planned hard file,
SHA256/bytes/counts, data schema, split realization, easy/hard construction,
evaluator path/version/behavior, model assets and data-license applicability
all remain `UNVERIFIED`. The only out-of-scope third-party response was the
ar5iv response retained solely as routing-failure evidence; none of its content
was adopted. No third-party data, mirror or Hugging Face source was read, and
no data/API, script, model, clone, snapshot, archive or sample was read.

No snapshot/acquisition request, run ID, approval, execution record, stage,
data or experiment artifact was created. The metadata reads and rejected route
are not acquisition or experiment runs.

The only next deliverable is an Agent 1 TimeQA fixed-revision
snapshot/acquisition plan. It must independently freeze repository-code versus
data-blob access, native process/environment gates, exact candidate URLs,
fresh no-replace paths, resource/archive limits, license mapping, hard-file
validation and failure retention. Agent 2 approval is required before any
network request, code/helper change, data access, approval/record or artifact.

## Snapshot candidate and non-execution boundary

The following literal is the only proposed snapshot candidate:

`https://codeload.github.com/wenhuchen/Time-Sensitive-QA/tar.gz/38b05989070c1168b2bef3d5a2656afeeba763dc`

It is an unverified and unexecuted candidate. This checkpoint does not claim
that it is direct, available, redirect-free, associated with a known MIME or
that it returns the intended commit. Agent 2 must separately approve the exact
URL/host/revision request before any execution. Git clone, hooks, submodules,
filters, branch/release archives, Hugging Face, forks and mirrors are forbidden.

No snapshot/acquisition request, run ID, approval, execution record, stage,
snapshot, data, code or experiment artifact was created by this plan.

## Independently approved A/B/C stages

### A — repository snapshot and formal tree

A would transfer the complete candidate archive, validate it and may safely
materialize the complete tree to bind archive/tree identity and formal
completion. README, LICENSE and tree metadata may be read semantically under A.
Every other member may necessarily have its bytes read by archive hashing,
validation, extraction, materialization and fingerprinting. For those members,
`opaque/unconsumed` means only that A performs no semantic parsing, sample
output, import or execution; it does not mean the bytes were never read or
materialized.

The local archive guard is `src/kairos/archive_safety.py` at clean commit
`e301d576843cf13768b317d34f34c5192c348c72`. It provides local archive
inspection/extraction safety only. It does not perform network transfer,
dataset-specific identity, publication or formal-completion semantics, so a
TimeQA-specific helper would require a separate code plan and audit.

### B — planned hard evaluation file

B may be proposed only after A has a verified formal tree and that tree proves
the exact path `dataset/human_test.hard.json` exists as an approved regular
member. A will already have mechanically read, hashed, extracted and possibly
materialized the whole tree, but B still requires separate Agent 2 approval
before semantically parsing the hard member or copying/publishing it into the B
root. B may validate only the planned hard file and explicitly approved minimum
non-executable schema metadata whose exact paths and hashes were established by
A. Evaluator source belongs exclusively to C and is outside B.

All B validation is no-echo: it may report aggregate file identity, strict
schema/type/count facts and rejection totals, but may not output question,
answer, context, sample, fact text or per-record identifier. Path absence,
schema ambiguity or unapproved dependency stops B without guessing from README,
arXiv landing, ar5iv or PDF content.

### C — license mapping and static evaluator audit

C requires a third independent approval. It may semantically read only fixed,
verified-hash LICENSE/README and explicitly approved evaluator/schema source.
It may map repository/data licensing and statically document evaluator entry,
normalizer and metric behavior. It must not import, compile, install or execute
upstream code, notebook, model or evaluator, and it may not access additional
data samples.

## Proposed native first-process contract

Every field below is proposed and unexecuted. After a fresh literal stage path
is bound, the transfer would require a native process API to create:

```text
executable: /usr/bin/curl
cwd: /data0/hk_data/kairos-zx
envp: {}
inherit_env: false
RLIMIT_FSIZE soft=hard=1073741824
RLIMIT_NOFILE soft=hard=64
RLIMIT_CORE soft=hard=0
```

The proposed `/usr/bin/curl` 7.68 argv is:

```text
[
  "/usr/bin/curl",
  "--disable",
  "--silent",
  "--show-error",
  "--fail",
  "--proto", "=https",
  "--proxy", "",
  "--max-redirs", "0",
  "--retry", "0",
  "--connect-timeout", "20",
  "--max-time", "1800",
  "--max-filesize", "1073741824",
  "--output", "<fresh-absolute-stage>/source.tar.gz.part",
  "--write-out",
  "http_code=%{http_code}\\nnum_redirects=%{num_redirects}\\nurl_effective=%{url_effective}\\nsize_download=%{size_download}\\n",
  "https://codeload.github.com/wenhuchen/Time-Sensitive-QA/tar.gz/38b05989070c1168b2bef3d5a2656afeeba763dc"
]
```

The proposed response gate requires the exact candidate URL and host, 2xx,
zero redirects, gzip magic, size/fstat stability and complete archive
validation. The proposed MIME allowlist is `application/gzip`,
`application/x-gzip` or `application/octet-stream`, but MIME is never identity
evidence and cannot independently admit a response. The complete gate must pass
as a conjunction; any mismatch fails closed.

The current `exec_command` interface cannot natively replace `envp`, set
`inherit_env=false` or install pre-exec OS rlimits, and launches a shell before
curl. It therefore cannot exclude inherited proxy, `LD_LIBRARY_PATH` or Conda
state from the first dynamic process. Shell cleanup, `env -i`, Python and
`prlimit` wrappers do not repair the boundary. The plan is consequently
`BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`.

## Proposed paths and resource envelope

All proposed paths below are private no-replace path templates under the
allowed data root, not execution-ready literals. This plan does not assert that
a path is absent and reserves none; a future execution audit must bind each
template to an exact literal path, determined byte for byte, and prove every
bound leaf absent before approval:

`/data0/hk_data/kairos-zx/data/.staging/timeqa/<fresh-execution-id>/`

`/data0/hk_data/kairos-zx/data/raw/timeqa/38b05989070c1168b2bef3d5a2656afeeba763dc/repository-v1/`

`/data0/hk_data/kairos-zx/data/raw/timeqa/38b05989070c1168b2bef3d5a2656afeeba763dc/hard-eval-v1/`

`/data0/hk_data/kairos-zx/data/raw/timeqa/38b05989070c1168b2bef3d5a2656afeeba763dc/static-audit-v1/`

Future preflight must run `nvidia-smi`, `free -h` and
`df -h /home/yangbin/zx-tmp /data0/hk_data/kairos-zx`. Proposed limits are
GPU 0, curl CPU 1, archive/helper CPU at most 2, transient memory at most 2 GiB,
transfer archive at most 1 GiB, expanded regular bytes at most 4 GiB, members
at most 100,000, archive metadata at most 64 MiB and total new disk at most
8 GiB. `/data0` free space must be greater than 120 GiB before any path creation.

## Proposed archive, completion and failure semantics

Held-FD archive validation must reject absolute/traversal/abnormal paths,
duplicates and prefix conflicts, symlink, hardlink, sparse, device, FIFO and
other special members, plus any path/member/metadata/expanded-byte limit
violation. It must bind archive SHA256/fstat stability, gzip magic, the expected
single TAR root and the complete formal tree. No upstream content is executed.

Formal A uses an independent no-follow/O_EXCL archive copy, safe tree
materialization, file and bottom-up directory fsync, canonical tree metadata,
SHA256SUMS, a formal-tree fingerprint, no-replace guard/final completion pair
and an independent offline verifier. B and C require separate private roots,
manifests, completion and approvals; they do not mutate a completed A root.

Every incomplete namespace is retained as evidence, including no-marker,
guard-only, final-only, guard/final pair mismatch, inode mismatch or link-count
mismatch states. All consumers must reject every such state. Only a complete
guard/final pair with the required shared identity/link count plus a fully
passing independent verifier is `complete`.

Incomplete evidence must not be registered as an acquisition, data artifact or
experiment and is never cleaned, overwritten, resumed or retried in the same
path. If a fixed formal leaf contains any partial state, a fresh execution ID
alone does not authorize reusing that leaf; recovery in place or a new
versioned formal path requires a separate design and Agent 2 approval.

Any URL/host/status/redirect/MIME/magic/size/fstat/archive/tree/license/schema,
resource or approved-path mismatch fails closed. A new attempt requires fresh
identity and separate approval, plus either an approved recovery protocol or a
new versioned formal path when the prior fixed leaf contains partial evidence.
No approval/record/run semantics exist until native process capability, exact
absent bound paths and all proposed fields have passed Agent 2 review.
