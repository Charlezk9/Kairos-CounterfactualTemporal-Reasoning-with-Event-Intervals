# Sandbox Audit

## 2026-07-22 — Phase 00 preflight

- verdict: APPROVED
- reviewer: boundary audit agent 2
- mode: read-only audit
- verified:
  - 所有拟写入目标均位于 `/home/yangbin/zx-tmp` 或 `/data0/hk_data/kairos-zx`。
  - `kairos` 尚未初始化 Git，且目标 GitHub remote 当前为空。
  - `.ssh` 为 700、私钥为 600、公钥为 644；公私钥指纹一致。
  - 公钥指纹为 `SHA256:Q0nlVwfr9J9ObayiiiKS/Dd19GCZOzJSVbk5M0f2lp8`。
- mandatory gates:
  - 先创建项目文档，最后精简父级 `AGENTS.md`。
  - 使用 GitHub 官方 Ed25519 host key 并校验指纹。
  - `core.sshCommand` 必须隔离默认 SSH 配置并限定 Ed25519 host key。
  - staged diff 必须拒绝密钥、token、模型、数据、checkpoint 和大型结果。
  - 首次 push 前再次确认远端为空。

## 2026-07-22 — Phase 00 postflight

- verdict: APPROVED
- bootstrap commit: `989634284e58b733e0bca2520fd0e7caad930e4c`
- push: `origin/main` created without force
- work branch: `experiment/reproduction-additional-evaluation`
- sensitive/large files: none detected
- known_hosts after remote access: still one verified Ed25519 entry
- background/GPU work: none

## 2026-07-22 — Phase 01 data-core first post-audit

- verdict: BLOCKED, fixes applied and awaiting re-audit
- paths/resources: passed; 17 staged files were limited to repository docs/src/tests, with no network, download, GPU, background task, secret, model, data or large artifact
- Git/SSH: passed; branch, remote, repository-local SSH isolation and the single verified Ed25519 host key were unchanged
- blocked defects:
  - yes/no updater treated an unrelated relation query as known;
  - canonical JSON coerced non-string mapping keys, allowing key collision;
  - checkpoint omitted the complete reproducible cache/temp environment from its displayed test command
- remediation: implementation and regression tests updated; checkpoint now records the complete command; full local suite passes 27 tests; final re-audit pending

## 2026-07-22 — Phase 01 data-core second post-audit

- verdict: BLOCKED on documentation only; implementation and safety checks passed
- verified fixes: unrelated relation queries return `UNKNOWN`; canonical JSON rejects non-string mapping keys; 27/27 tests and regression coverage agree with the checkpoint
- safety: staged paths, modes, sizes, secret scan, dangerous-operation scan, Git remote, local SSH command and single verified host key all passed
- remaining defects: displayed `CONDARC` path was incorrect and `CURRENT.next_safe_action` was stale
- remediation: `CONDARC` now points to `/data0/hk_data/kairos-zx/.condarc`; CURRENT now requests final audit followed by checkpoint commit/push; final re-audit pending

## 2026-07-22 — Phase 01 data-core final post-audit

- verdict: APPROVED TO COMMIT and ordinary non-force push
- staged scope: 18 repository files under docs/src/tests; no unstaged drift, secrets, dangerous operations, external write paths or large artifacts
- verification: 27/27 tests, pre-commit hook and cached diff check passed; the documented local Python, `.condarc`, cache and temporary paths exist within the two authorized roots
- Git/SSH: branch tracking, remote URL, repository-local isolated SSH command and the one-line verified GitHub Ed25519 host key passed
- restriction: this approval covers the deterministic data-core checkpoint only; real dataset acquisition, adapters, construction statistics and human audit require a new preflight

## 2026-07-22 — Phase 01 data-acquisition first preflight

- verdict: BLOCKED before any data download
- source facts passed: six official GitHub commits exist; StrategyQA 90/10 dev is unofficial; TORQUE test has no released gold; TimeQA `human_test.hard.json` exists; licenses and the paper's missing subset-ID limitation are accurately recorded
- availability caveat: official MuSiQue Drive and 2Wiki Dropbox URLs are present in pinned READMEs but timed out during bounded HEAD checks, so availability and size remain unverified
- blocked risks: original archive gate omitted special entries, Windows/backslash paths and expanded-size/member limits; bare `curl` resolved to an Anaconda binary outside the authorized roots
- remediation: require a tested standard-library validator, `/usr/bin/curl`, HTTPS/host/size/time bounds, `.part` files, archive-bomb checks and extraction only into a new empty directory; re-audit pending

## 2026-07-22 — Phase 01 data-acquisition second preflight

- verdict: BLOCKED on one documentation command option; all archive/source/path gates passed
- defect: `/usr/bin/curl` is 7.68.0 and does not implement the documented `--retry-all-errors`
- remediation: use supported `--retry 3 --retry-connrefused --retry-delay 2 --retry-max-time 120`; all HTTPS, redirect, host, timeout, byte-limit and `.part` gates remain unchanged; final source-plan audit pending

## 2026-07-22 — Phase 01 data source-plan final audit

- verdict: APPROVED TO COMMIT SOURCE PLAN and ordinary non-force push
- verified: five staged documentation files, hook/diff checks, fixed source revisions and licenses, curl 7.68-compatible bounded options, archive/path/type/member/expanded-size gates, 8 GiB budget, official-host allowlists and failure-without-mirror policy
- scope restriction: this is not download approval; next action is limited to agent 1 implementing and testing the standard-library archive validator inside the repository

## 2026-07-22 — Phase 01 archive-validator first staged audit

- verdict: BLOCKED; validator must not be committed and no real download is approved
- passed: no `extractall`; path normalization, duplicate/prefix, special member, encryption, declared/actual byte, member digest and final-file `O_EXCL` controls; 36/36 then-current tests
- blocked defects:
  - ZIP/TAR metadata was fully materialized before the 200,000-member limit and repeatedly loaded;
  - an in-place rewrite after the first archive hash could mix an old reported SHA with new inspected content;
  - source/parent symlinks were followed and destination path operations allowed parent replacement races
- remediation: EOCD and bounded TAR metadata preflights, before/after SHA+fstat checks, root-anchored no-follow dirfds and nine additional regressions implemented; 45/45 tests pass; re-audit pending

## 2026-07-22 — Phase 01 archive-validator second staged audit

- verdict: BLOCKED; validator must not be committed and no real download is approved
- passed: the first audit's metadata-materialization, in-place mutation, symlink and destination-parent race findings were remediated; 45/45 then-current tests passed
- blocked defects:
  - ZIP preflight trusted the EOCD entry count, so a forged smaller count could allow a larger central directory to be materialized;
  - ZIP64 rejection did not cover a local-header `0x0001` extra field.
- remediation: every central entry is now parsed with a `max_members + 1` immediate failure, the actual count and byte range must exactly match EOCD, central and local headers are cross-checked, and ZIP64/multi-disk sentinels plus ZIP64 extra fields are rejected. Forged-count, malformed-range and `force_zip64` regressions raise before `ZipFile`; 47/47 tests pass; final re-audit pending.

## 2026-07-22 — Phase 01 archive-validator third staged audit

- verdict: BLOCKED; validator must not be committed and no real download is approved
- passed: forged EOCD count and local ZIP64 extra regressions now fail before `ZipFile`; 47/47 tests, hook/diff checks, secret/large-file/dangerous-command scans, no-unstaged-drift check and project-local Git/SSH checks passed
- blocked defects:
  - preflight allowed unaccounted bytes between the central directory end and EOCD, so a one-byte gap still reached `ZipFile` and could also hide unsupported ZIP metadata;
  - local header comparison covered only filename/ZIP64, not version-needed, flags, compression, CRC32 and compressed/uncompressed sizes; mutated local values were accepted before materialization.
- required remediation: require the central directory to end exactly at EOCD under the project's no-digital-signature/no-ZIP64 policy; compare all relevant central/local fields and conservatively reject data descriptors unless fully verified; add pre-`ZipFile` regressions for each mismatch and request another full staged audit.
- remediation implemented: central end must equal EOCD offset; version-needed, flags, compression, CRC32 and both sizes are compared; encryption and bit-3 data descriptors are rejected in either header; gap and mismatch regressions fail before `ZipFile`. The full repository suite now has 49 tests; another staged audit is pending.
