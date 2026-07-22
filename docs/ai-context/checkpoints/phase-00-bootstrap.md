# Phase 00 — Restart-safe bootstrap

- status: RUNNING
- objective: 在任何实验代码或数据下载前建立最小 AGENTS、详细 README、当前状态、项目专用 SSH 和 Git 历史。
- allowed writes: `/home/yangbin/zx-tmp/AGENTS.md`、`/home/yangbin/zx-tmp/.ssh/known_hosts_github`、`/home/yangbin/zx-tmp/kairos/**`
- forbidden: 系统/全局配置、默认 `~/.ssh`、数据下载、GPU、实验代码和长期任务。
- preflight verdict: APPROVED，见 `../sandbox-audit.md`。

## Acceptance

- 根和项目 AGENTS 只含启动必需信息。
- 所有详细说明有唯一 README 来源。
- `CURRENT.md` 能独立指出阶段和下一动作。
- GitHub host key 与项目身份严格验证。
- 初始化提交不包含密钥、模型、数据或大型结果。
- `main` 推送成功并创建实验分支。
