# Phase 01 MuSiQue Bounded Probe Helper Checkpoint

- status: `IMPLEMENTED_AND_AUDITED`; production execution not approved
- implementation commit: `cacbcbcc504ebfcb77c1e6329edc69f05de9a7e2`
- source: `src/kairos/musique_probe.py`
- tests: `tests/test_musique_probe.py`
- implementation agent: agent 1
- boundary agent: agent 2

## Fixed scope

The helper is a single-attempt, bounded response-body acquisition for the exact
official Drive view URL recorded by MuSiQue repository commit
`922ac98f19a201998dbdae6d7f2887a5258dbdeb`. It can request only bytes
`0-65535`, follows no redirect, accepts only HTTP 206, and publishes no formal
MuSiQue revision. Body, curl write-out, stderr and process-result evidence use
separate held descriptors. A successful probe requires curl `size_download`,
the body `fstat` size and the bounded hash-read count all to equal 65,536, plus
ZIP magic, an allowed MIME type, zero redirects and an unchanged effective URL.

The production CLI has only fixed-layout `execute --approved-commit <40hex>`
and offline `verify` operations. `execute` requires an exact clean Git commit,
uses fixed `/usr/bin/prlimit` and `/usr/bin/curl`, passes only the body FD across
exec, applies `RLIMIT_FSIZE`, and writes evidence with held dirfds, `O_NOFOLLOW`,
`O_EXCL`, private modes and manifest-last publication. The offline verifier
does not invoke Git, curl, a subprocess or the network.

## Verification and audit

The final staged snapshot passed 92/92 focused tests and 258/258 full repository
tests with the project-local Python, CUDA hidden, two CPU threads and all
temporary/cache paths under `/data0/hk_data/kairos-zx`. The main agent repeated
the final full suite: 258/258 in 10.427 seconds. Diff checks and the repository
pre-commit hook passed.

Four boundary-audit rounds blocked submission until the implementation added:

- a real offline `/usr/bin/prlimit` plus `/proc/self/fd/N` test for identical
  device/inode, truncation, 65,536-byte success and 65,537-byte rejection;
- deadline-driven nonblocking Git-output reads and whole-owned-PGID cleanup,
  including an exited leader whose descendant holds stdout and ignores
  `SIGTERM`;
- complete selector, pipe and FD cleanup on initialization, read, close and
  reap faults without masking an active primary exception;
- strict `link -> fsync -> unlink -> fsync` observation publication and durable
  multi-path fail-close recovery;
- `INCOMPLETE` for absent, interrupted, malformed, tampered or canonically
  unverifiable evidence, reserving `BLOCKED` for a trusted replay whose HTTP,
  process or content gates fail;
- the formal raw path bound to repository commit `922ac98f...`, plus created-FD
  cleanup and explicit bounded-body terminology.

The final verdict was `APPROVED TO COMMIT` for the exact two-file snapshot.
No production execute, real network request, real curl/Git preflight, MuSiQue
raw/processed access, GPU use or dependency change was approved or performed.

## Fatal durability boundary

Every recovery branch may report success only after its required file and
directory `fsync` calls succeed and the terminal namespace is rebound and
revalidated. If all safe mutations or persistence calls fail, the helper raises
`publication fail-close unconfirmed` or `terminal fail-close unconfirmed` and
must stop. Such a stage is an unknown state requiring manual isolation; a later
standalone offline `verify` must not be used to authorize automatic recovery or
continued downloading.

## Remaining execution blocker

The helper deliberately rejects group/other-writable trusted ancestors. The
current `/data0`, `/data0/hk_data` and project data-root ancestors are mode
`0775`, so a production `execute` would fail closed before network access. This
policy must not be weakened merely to make the probe run. The next step is a
separate Agent 1 execution-policy plan and Agent 2 review; until then there is
no authorization to create a probe stage or send a request.
