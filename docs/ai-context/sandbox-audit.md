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
