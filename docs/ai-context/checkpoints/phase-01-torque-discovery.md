# Phase 01 TORQUE Official Source Discovery

- status: `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`
- metadata discovery disposition: `METADATA_ONLY / DOCUMENTS_READ`
- branch: `experiment/reproduction-additional-evaluation`
- metadata discovery base HEAD: `b34b72bb2b873330d08087a65e2af6c953906551`
- snapshot/acquisition plan and audit base HEAD: `45ebd0f3b7ff81ef11173f9479db9c3f68241eb8`
- active run IDs: none
- running processes: none
- scope: documentation-only fixed-revision metadata plus a non-executed A/B/C snapshot/acquisition plan and tooling disposition

## Fixed provenance and documents read

- repository: `https://github.com/qiangning/TORQUE-dataset`
- revision: `ab27019cc6a317fde3c879900499f02acce8b16d`
- pinned README read:
  `https://raw.githubusercontent.com/qiangning/TORQUE-dataset/ab27019cc6a317fde3c879900499f02acce8b16d/README.md`
- pinned repository LICENSE read:
  `https://raw.githubusercontent.com/qiangning/TORQUE-dataset/ab27019cc6a317fde3c879900499f02acce8b16d/LICENSE`
- ACL Anthology primary page read:
  `https://aclanthology.org/2020.emnlp-main.88/`
- ACL Anthology primary PDF read:
  `https://aclanthology.org/2020.emnlp-main.88.pdf`
- primary-paper DOI: `10.18653/v1/2020.emnlp-main.88`

Only these four fixed documents were read. No GitHub API/tree, data file,
script, evaluator, model repository, third-party page or mirror was read.

## README-reported metadata

The pinned README names `./data` as containing the entire dataset and the
original train/dev/test split. It states that test annotations were removed by
the authors. It also names `question_clustering.json` and
`./basic_stats/basic_stats.py`; notebook paths are retained only as
`README_REPORTED` metadata and are not guessed or opened in this discovery.

These are `README_REPORTED` names and statements, not local source-tree or data
observations. The discovery did not verify whether any reported path exists at
the fixed commit, inspect member names, or observe train/dev/test payloads.
Future project evaluation may consider only the public dev gold after a
separate acquisition and audit. Test gold is unavailable and must never be
recovered from a fork, cache, historical copy or third-party mirror.

## Primary-paper reported metadata

The primary paper reports approximately 3.2K annotations, about 2.9K of them
unique; 24.9K events; 21.2K user-generated questions; 9.5K warm-up questions;
30.7K total questions; and 65K answers. It reports an article-disjoint
80%/5%/15% train/dev/test split. These quantities are `PAPER_REPORTED`; they
are not local file counts, archive observations or experiment results and must
not be used to assert snapshot completeness.

The paper reports Macro F1, exact match (EM) and consistency (`C`). Its prose
defines EM consistency as the percentage of contrast sets for which predictions
match exactly for every question, while the Table 4 caption defines `C` as the
percentage of contrast groups for which every question has F1 at least 80%.
This is a `SPEC_CONFLICT` in the reported consistency formulation, not an
ordinary per-question EM conflict. No definition is selected, normalized or
implemented at this checkpoint. Resolution requires a separately approved
official-evaluator/source audit and must preserve both formulations.

## License, schema and evaluator boundary

The pinned repository LICENSE is Apache License 2.0. It establishes only the
repository-level license observed in that document. Its applicability to data
blobs, annotations or derived artifacts, and any additional attribution or
notice requirements in the data, remain `UNVERIFIED`.

The actual fixed-revision tree, file existence, file names beyond the README
statements, byte sizes, SHA256 values, split realization, record counts, data
schema, event/question/answer representation, gold completeness, official
evaluator path/version/behavior and data-license applicability all remain
`UNVERIFIED`. Test gold is `UNAVAILABLE` by the author's current publication
boundary.

No data/API endpoint, script, evaluator, notebook, model repository, sample
content or third-party source was read. There was no clone, snapshot/archive
download, data blob access, upstream-code execution, raw/stage path creation,
approval, execution record, acquisition record or experiment artifact. This
checkpoint registers no formal run and provides no result for a paper claim.

## Frozen acquisition candidate and stage separation

The only candidate snapshot URL is frozen as:

`https://codeload.github.com/qiangning/TORQUE-dataset/tar.gz/ab27019cc6a317fde3c879900499f02acce8b16d`

Agent 2 must still approve this literal candidate's repository, commit, direct
host and no-redirect behavior before execution. Git clone, hooks, submodules,
filters, Hugging Face, forks, test-gold recovery and all third-party mirrors
are prohibited.

The work is divided into three independently approved stages:

1. **A — repository snapshot:** transfer the complete fixed-commit archive,
   validate it, and publish the archive, README, LICENSE and tree metadata.
2. **B — public-dev data validation:** consume only public dev gold and the
   clustering/schema material necessary to validate it.
3. **C — evaluator/script audit:** statically inspect fixed source without
   importing or executing it.

A future A stage necessarily transfers the whole archive and may safely
materialize the whole validated tree to establish tree identity and formal
completion. Data and evaluator bytes would therefore be physically acquired
and possibly materialized by A, but must remain opaque and unconsumed: no
parse, sample output, schema inference, import or execution is allowed under A.
After a successful A stage it would be incorrect to claim those bytes were not
acquired; the precise claim would be that they were not consumed. In the
current actual state no archive has been downloaded or materialized.

## Native first-process transfer contract

The transfer must be created by a native process API with this complete outer
boundary:

```text
executable: /usr/bin/curl
cwd: /data0/hk_data/kairos-zx
envp: {}
inherit_env: false
RLIMIT_FSIZE soft=hard=1073741824
RLIMIT_NOFILE soft=hard=64
```

After an audited fresh absolute stage path is bound, the exact `/usr/bin/curl`
7.68-compatible argv must be:

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
  "https://codeload.github.com/qiangning/TORQUE-dataset/tar.gz/ab27019cc6a317fde3c879900499f02acce8b16d"
]
```

There is no `--location`; any redirect fails. Retry count is zero. The native
API must capture the real exit code and bounded stdout/stderr separately,
without a pipeline or wrapper, and must apply the OS resource limits before
the first dynamic process starts.

## Resource, path and archive gates

Immediately before any future write, the approved execution must run
`nvidia-smi`, `free -h` and
`df -h /home/yangbin/zx-tmp /data0/hk_data/kairos-zx`. GPU use is zero;
transfer concurrency is one CPU and archive validation/extraction is at most
two CPUs with at most 2 GiB transient memory. The archive cap is 1 GiB,
expanded regular bytes are capped at 4 GiB, members at 100,000, metadata at
64 MiB and total new stage/formal disk use at 8 GiB. If `/data0` free space is
not greater than 120 GiB, execution stops before creating a path.

The future paths must be fresh and no-replace:

```text
stage:  /data0/hk_data/kairos-zx/data/.staging/torque/<fresh-execution-id>/
formal: /data0/hk_data/kairos-zx/data/raw/torque/ab27019cc6a317fde3c879900499f02acce8b16d/repository-v1/
```

Neither path nor ID exists or is reserved by this plan. The execution audit
must bind an absent literal stage and absent formal leaf before approval.

Held-FD `archive_safety` validation must reject traversal, absolute or abnormal
paths, duplicate/prefix-conflict entries, symlink, hardlink, sparse, device,
FIFO and other special members, plus any member/metadata/expanded-byte limit
violation. It must check archive SHA256/fstat stability and must not execute
archive content. Formal publication uses independent no-follow/O_EXCL copies,
file and bottom-up directory fsync, canonical tree metadata and SHA256SUMS, a
formal-tree fingerprint, no-replace guard/final completion pair and an
independent offline verifier. Stage/formal failure evidence is retained; no
cleanup, overwrite, resume or retry in the same paths is allowed.

## B — public-dev data validation boundary

B requires a separate approval over the verified A artifact. It may consume
only public dev gold plus `question_clustering.json` and schema information
strictly necessary to validate question/answer/event/cluster linkage and the
planned public-dev metrics. Train and unrelated data remain opaque unless a
later purpose-specific approval is granted.

Test payload must never be emitted, logged, passed to a model or consumed as an
evaluation split. A bounded no-echo structural check must confirm that test
gold/annotations are absent. If annotations unexpectedly exist, processing
stops immediately and records only the gate failure—not annotation content,
values, counts or derived hashes. Test gold is never recovered from another
commit, cache, fork or mirror.

## C — static evaluator/script audit boundary

C requires a separate approval and may only statically inspect fixed, hashed
evaluator/script source from A. It must not import, execute, install or run any
upstream module, script or notebook. The audit may compare Macro F1, EM and
consistency implementation with the paper, but it must retain the prose/Table
4 `SPEC_CONFLICT`; it cannot silently choose, normalize or erase either
formulation. Any later metric implementation is an independent local
reimplementation with its own tests and review.

## Failure and tooling disposition

Unapproved URL/revision, redirect/effective-URL change, non-2xx response,
nonzero curl exit, size/resource excess, archive policy failure, README/LICENSE
or tree mismatch, unclear data license, or unexpected test annotations all
fail closed. Evidence is retained and there is no retry, fallback, mirror or
old-commit substitution.

The current `exec_command` interface has no native replacement `envp`,
`inherit_env=false` or pre-exec OS rlimit parameters, and it launches a shell
before curl. It therefore cannot exclude inherited proxy, `LD_LIBRARY_PATH`
or Conda state from the first dynamic process. Shell cleanup, `env -i`, Python
or `prlimit` wrappers do not repair that boundary. The acquisition plan is
independently `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`.

No snapshot/acquisition request, run ID, approval, execution record, stage,
archive, data or experiment artifact was created, and no code, helper or test
was run. Agent 2 approval is required before any further network,
implementation or artifact. The next safe unrelated task may proceed to TimeQA
primary-source metadata discovery.
