# Current State

- updated_at: 2026-07-22 14:45:29 CST
- active_phase: phase-01-data-pipeline
- phase_status: RUNNING
- git_branch: experiment/reproduction-additional-evaluation
- git_head: efb0cfd3add3b3b1bec6209ad5ab6066ec88aba0
- last_verified_commit: efb0cfd3add3b3b1bec6209ad5ab6066ec88aba0
- last_completed_checkpoint: checkpoints/phase-01-data-core.md
- active_run_ids: none
- running_processes: none
- blockers: acquisition helper 首次实施预审为 BLOCKED：需固定生产路径与长持有 dirfd，对 copy/tree/hash 做前后 fingerprint 并拒绝 hardlink，completion 前 fsync 全树，在 helper 内独立实施资源/路径上限与无歧义清单文法。
- next_safe_action: 提交 D-004-A 的 dirfd/TOCTOU/fsync/硬上限增补，再由智能体 1重新提交 helper 实施计划供智能体 2预审；获批前不实现代码、不创建 raw 数据。
- required_reading:
  - `checkpoints/phase-01-data-core.md`
  - `checkpoints/phase-01-data-acquisition.md`
  - `decisions.md`
  - `../implementation/README.md`
  - `../experiments/README.md`
  - `../operations/README.md`
