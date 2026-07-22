# Phase 01 StrategyQA Acquisition Helper

- status: `IMPLEMENTATION_COMPLETE`; production execution not approved
- implementation commit: `978ba4dea0792061340d0ec97241caa1efd6d6f2`
- implementation: `src/kairos/strategyqa_acquisition.py`
- tests: `tests/test_strategyqa_acquisition.py`
- implementation agent: agent 1
- boundary agent: agent 2

## Implemented boundary

The helper fixes the source URL, `official-20210107` project label, expected
strong ETag token and UTC date from the approved source plan. Its production
CLI accepts no path, URL or resource override. A project-root transaction
marker protects the entire stage operation; all files use held dirfds,
no-follow/no-replace private creation, bounded reads and strict canonical JSON.
The stage manifest is a held guard/final hardlink pair and is replayed from
held evidence before the transaction marker can be removed.

Transfer supervision applies fixed AS/CPU/core/nofile/file-size/affinity limits,
independent header/writeout/stderr/archive bounds, a whole-process-group
watchdog and mandatory reaping. Source-parent and stage full fingerprints,
fixed policy evidence, three clean-Git checkpoints and exact terminal namespace
replay fail closed on replacement or drift.

## Transaction and fault evidence

Two complete staged audits were required. The first audit blocked commit on FD
close retry, pre-binding reads of an unknown marker and manifest-pair FDs living
past the unique commit point. The final snapshot transfers ownership before
every affected close, rejects a different-inode marker before open/read,
rebinds a rebuilt marker before reading it, and closes guard/final while the
transaction marker still exists. After unlink, root fsync and confirmed name
absence, only the unlinked marker FD and held recovery-root FD may close with
warning-only semantics.

Synthetic fault coverage includes marker existing/missing/unknown recovery,
fsync/rebind/close failures, publication replacement and ABA, unknown-object
preservation, held-pair lifetime, canonical manifest/process bytes, numeric
type confusion, commit replay and post-commit cleanup. Agent 1 and the main
agent independently passed targeted `79/79` and full-repository `337/337` tests
under the project-local Python with zero GPU, two CPU threads, 8 GiB virtual
memory and all temp/cache paths under `/data0/hk_data/kairos-zx`. The final
staged verdict was `APPROVED TO COMMIT`.

## Remaining gate

`RUNTIME_REDIRECT_SEMANTICS_VERIFIED` remains `False`. Public `fetch()` fails
before resource checks, file creation, subprocess execution or network access.
No production marker, stage or formal StrategyQA path exists; no archive body,
HTTP observation, raw data, experiment run or paper metric was produced.

The next deliverable is only a separately audited runtime redirect-semantics
verification plan. This checkpoint does not approve a real URL, loopback
server, Git/NSS/ACL preflight, production stage creation, download, extraction
or flag change.
