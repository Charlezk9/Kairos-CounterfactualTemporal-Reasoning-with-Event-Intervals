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
