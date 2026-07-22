# Phase 01 StrategyQA Official Source Plan

- status: `SOURCE_PLAN_APPROVED`; implementation and network not approved
- source label: `official-20210107` (project label, not a commit or hash)
- fixed URL: `https://storage.googleapis.com/ai2i/strategyqa/data/strategyqa_dataset.zip`
- fixed host: `storage.googleapis.com`
- frozen strong ETag token: `f4ae9d9296c06f90d80aee1e4a25d58a`
- frozen Last-Modified UTC date: `2021-01-07`
- implementation agent: agent 1
- boundary agent: agent 2

## Source identity and unknowns

The pre-transfer identity gate is the exact URL/effective URL, a non-weak,
non-duplicated ETag whose optional HTTP quotes contain the frozen token, and a
parsed Last-Modified UTC date of 2021-01-07. A first approved GET must add the
archive SHA256 and actual byte count. Full Last-Modified time, archive SHA256,
size, MIME, member tree, JSON schema/counts and license contents remain
`UNVERIFIED` until observed through the audited stage path.

Repository commit `eladsegal/strategyqa@1ba1e97452e189569357876f2854b01357ffbe37`
is only a code, MIT-license and non-official 90/10 split reference. It is not the
GCS data revision and must not supply an alleged official validation split.
Expected ZIP/member names are `UNVERIFIED_EXPECTATION`, not a frozen contract.

If the ZIP does not contain verifiable upstream license evidence, acquisition
must stop at `STAGED_LICENSE_BLOCKED`. A repository license requires a separate
fixed-source approval and an applicability decision; no generated license or
manifest assertion can replace upstream file evidence.

## Fixed candidate layout

Only a separately approved implementation may use:

- stage: `/data0/hk_data/kairos-zx/data/raw/strategyqa/.acquire-official-20210107/`
- formal: `/data0/hk_data/kairos-zx/data/raw/strategyqa/official-20210107/`

Both leaves must be fresh 0700 and no-replace. Stage candidates are
`source.zip.part`, bounded header/writeout/stderr evidence,
`transfer-result.json` and a manifest. A complete formal candidate uses an
independently copied and rehashed `source.zip`, fresh `extracted/`, exact
`SHA256SUMS`, and the audited durable completion guard/final pair. Stage and
formal archives must have different inodes and `nlink=1`.

## Resource and transfer envelope

- GPU 0; CPU/threads at most 2; address space at most 8 GiB.
- Total new project bytes at most 8 GiB, including failed stage and partial
  formal output; `/data0` available space must remain strictly above 120 GiB.
- Transfer at most 1 GiB; extracted regular bytes at most 2 GiB; at most
  200,000 members and 64 MiB archive metadata.
- HTTP headers at most 1 MiB, curl write-out 4 KiB, stderr 64 KiB, and each JSON
  discovery input 64 MiB. Each is a hard limit with an exact limit+1 test.
- Connect timeout 20 seconds, curl wall time 1,800 seconds, retry budget 120
  seconds with three internal retries, low-speed 1,024 B/s for 30 seconds, and
  an outer 1,900-second watchdog with TERM then KILL after 10 seconds.
- `RLIMIT_FSIZE=1 GiB`, `RLIMIT_AS=8 GiB`, curl CPU 300 seconds,
  validator/finalizer CPU 900 seconds, `RLIMIT_NOFILE=64`, and no core dumps.

The planned fixed curl argv begins with `--disable`, uses HTTPS only, has no
credentials/config/cookies, and combines `--location --max-redirs 0` so any
redirect fails closed. Final status must be HTTP 200, redirect count zero and
effective URL byte-identical to the fixed URL. `/usr/bin/timeout` is defense in
depth only: the parent must still own, terminate and reap the complete process
group on every timeout, overflow, exception or cancellation.

Header, write-out and stderr limits require independent held-FD controls;
the archive-wide `RLIMIT_FSIZE` is not sufficient for them. Transfer remains a
single foreground wrapper invocation; curl-internal retry does not imply that
only one HTTP request occurred.

## Validation and publication sequence

1. A source-specific fixed module creates a fresh stage and all evidence files
   with held dirfds, `O_NOFOLLOW|O_EXCL`, fixed private modes and no path option.
2. A separately approved GET writes only to held FDs. Any nonzero exit,
   watchdog action, stream overflow or resource gate stops processing.
3. Offline stage validation strictly parses bounded response evidence, binds
   URL/ETag/date/MIME/size, hashes a stable single-link archive FD, and runs the
   existing bounded ZIP inspector. Only aggregate/member-path/hash facts may be
   recorded; no raw record value is logged.
4. Agent 2 reviews actual SHA, size, MIME, member tree and license state. No
   formal revision is published at this point.
5. A discovery pass with a hard 64 MiB per-JSON cap freezes the exact member,
   top-level type, key, count, split and license contract without using test
   answers to choose rules.
6. Only after another audit may a source-specific finalizer independently copy
   the archive, safely extract to a fresh leaf, enforce the frozen contract,
   write exact checksums, fsync all files/directories, bind the formal tree and
   publish the durable completion pair. A full offline replay is mandatory.

Failure states retain evidence without cleanup, overwrite, resume or same-path
retry: `BLOCKED_SOURCE_IDENTITY`, `BLOCKED_HTTP_RESPONSE`, `REJECTED_ARCHIVE`,
`STAGED_SCHEMA_UNVERIFIED`, `STAGED_LICENSE_BLOCKED`,
`INCOMPLETE_DURABILITY`, or `BLOCKED_RESOURCE_GATE`. None is adapter-consumable
or acquisition `COMPLETE`.

## Threat-model implementation gate

The GSM8K fixed helper cannot be called directly because its paths, archive,
schema and manifest are source-specific. Agent 2 permits its held-dirfd,
no-follow, terminal canonical rebinding and full offline-replay model only as a
candidate for a new StrategyQA implementation plan. This does not alter the
MuSiQue trusted-ancestor policy.

The next implementation plan must explicitly state the initial-root
authenticity assumption under current 0775 ancestors and add owner/fingerprint
checks plus pre-open, post-open and in-run replacement tests for project root,
source parent, stage and formal leaf. Held FDs and terminal rebinding alone do
not prove that an already-replaced pre-open path was authentic. If Agent 2 does
not approve this source-specific threat model, StrategyQA becomes a separate
`BLOCKED_POLICY`; no chmod or silent predicate weakening is allowed.

Required synthetic tests also cover URL/metadata grammar, real system curl
redirect behavior, independent stream limits, whole-PGID cleanup, archive
attacks, strict JSON, license gates, every publication/fsync/close boundary,
canonical path replacement, completion states and failure-evidence retention.
All tests remain offline under the project-local Python, 0 GPU, 2 CPU and
`/data0`-scoped temp/cache.

## Approval boundary

Agent 2 returned `APPROVED TO DOCUMENT / PLAN IMPLEMENTATION`. This permits
this checkpoint and one exact Agent 1 implementation plan only. It does not
permit code changes, test execution, Git preflight, HEAD/GET, network,
production, stage/raw/processed access, dependency changes or GPU use.
