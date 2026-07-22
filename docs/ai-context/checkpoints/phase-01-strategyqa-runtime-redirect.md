# Phase 01 StrategyQA Runtime Redirect Gate

- status: `BLOCKED_TOOLING / NO_NATIVE_EXEC_ENV`
- scope: documentation-only closeout; not a runtime verification or source request
- branch: `experiment/reproduction-additional-evaluation`
- observed Git HEAD: `aa8a78da98368b86343536da4fb72e289e7c1ce1`
- active run IDs: none
- running processes: none
- production flag: `RUNTIME_REDIRECT_SEMANTICS_VERIFIED=False`

## Outcome

The redirect-semantics preparation did not reach execution. Main-agent static
review passed the final on-disk identity, canonical-record, snapshot, FD-vector,
launcher-vector and terminal-path-rebind checks for the V2 preparation record.
Agent 2 nevertheless blocked execution because the available process launcher
cannot provide a replacement environment to the first dynamically loaded
process. The current inherited environment contains `LD_LIBRARY_PATH` and base
Conda state, so starting a shell or Python process and clearing its environment
afterward cannot establish the required trust boundary.

The available `exec_command` interface accepts a command, working directory and
shell options but has no native `envp` replacement or `inherit_env=false`
parameter. A shell, `/usr/bin/env`, Python, Conda or similar wrapper would itself
load under the inherited environment before it could clear that environment and
is therefore not an acceptable workaround. This is a tooling block, not a
redirect-semantics failure and not evidence about the StrategyQA source.

## Retained, invalid preparation files

The following files are retained as audit evidence. None was executed and none
may be reused for a later attempt:

- existing approval:
  `/data0/hk_data/kairos-zx/.tmp/kairos-execution-approval-746c2033ba7c25dd45c744de5abb1bc5.json`,
  SHA256 `cdc0244d5897a286dcd9dab625e1e4841718834d2ab27ad8a8c93c644dd51d0f`;
  status `INVALID_NOT_EXECUTED` for future use
- V1 record:
  `/data0/hk_data/kairos-zx/.tmp/kairos-execution-record-746c2033ba7c25dd45c744de5abb1bc5.json`,
  SHA256 `ed32d0163884443634d9b90bff4f54d79ba4fd774b958f034228b8aca4c80826`;
  status `INVALID_NOT_EXECUTED`
- V2 record:
  `/data0/hk_data/kairos-zx/.tmp/kairos-execution-record-746c2033ba7c25dd45c744de5abb1bc5-v2.json`,
  SHA256 `a60822db2dc71f81e9ce5fc4aceafde9120b212bba745d1a2269da8a9ae9a6f5`;
  status `INVALID_NOT_EXECUTED`

V1 had an incorrect FD/launcher argument contract. V2 corrected that internal
contract and added the approved full-facts, hash and terminal `lstat` rebind
checks, but it could not correct the outer inherited-environment problem. The
approval and both records remain byte-for-byte retained; their status here does
not authorize modifying, deleting or relabelling the files themselves.

No V3 record, new run ID, new execution nonce or new approval was created. The
retained identifier is not an active run and is deliberately absent from the
experiment registry.

## Non-execution evidence and boundaries

No inline pre-opener, runtime probe or production helper was executed. There
was no socket, fork, target exec, curl, signal, recovery action, HTTP HEAD/GET,
data access, StrategyQA stage/archive, experiment output or experiment artifact.
Static inspection did not change the production flag. Even a future successful
redirect-semantics verification may not set
`RUNTIME_REDIRECT_SEMANTICS_VERIFIED=True` in the same gate; changing that flag
requires a separate reviewed change and checkpoint.

During an earlier preparation turn, Agent 1 mistakenly spawned the
`recovery_patch` sub-agent. The main agent interrupted it immediately and
confirmed that it made no file changes. No later sub-agent was spawned, and
future work under this gate must not spawn one.

## Required recovery capability

Recovery requires a process API that passes the outer executable, complete
argv, exact empty or approved allowlist `envp`, and cwd natively at the first
`execve`/`posix_spawn` boundary, with inherited environment replacement rather
than merging. It must not use a shell, `env`, Python or Conda cleanup wrapper.
The outer runtime, its root-owned identity and the exact API request must be
auditable before execution.

After that capability exists, preparation must start over with a fresh run ID,
fresh nonce, fresh strict approval and fresh no-replace V3 record. The corrected
V2 FD mapping and launcher/bootstrap contract, resource limits and production
flag remain unchanged. Agent 2 must approve the native invocation record before
execution and perform a post-execution boundary audit. Until all of these gates
pass, StrategyQA acquisition remains unavailable.

## Safe continuation

This blocked gate is closed without a formal run. The next safe task is only an
Agent 1 draft of a read-only 2Wiki official source metadata/discovery plan.
Agent 2 approval is required before any network request, code change, data
access or artifact creation.
