# Phase 01 TimeQA Official Source Discovery

- status: `BLOCKED_TOOLING / NO_PRE_FETCH_REDIRECT_AND_BYTE_GATES`
- metadata disposition: `METADATA_ONLY / README_LICENSE_AND_ARXIV_LANDING_READ`
- branch: `experiment/reproduction-additional-evaluation`
- discovery/audit base HEAD: `903684181f6a936650e6c1ff2488f1d12ad5a957`
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
