# Current State

- updated_at: 2026-07-22 18:00:19 CST
- active_phase: phase-01-data-pipeline
- phase_status: RUNNING
- git_branch: experiment/reproduction-additional-evaluation
- git_head: 87251f0577d3b2c26d5a604ac6b57a3f34f37986
- last_verified_commit: 87251f0577d3b2c26d5a604ac6b57a3f34f37986
- last_completed_checkpoint: checkpoints/phase-01-data-core.md
- active_run_ids: none
- running_processes: none
- blockers: D-005 is frozen, but adapter implementation, tests, processed output and all next-source downloads remain unapproved.
- next_safe_action: 仅由智能体 1根据冻结 D-005 提交限定实现计划，必须显式覆盖 dirfd/no-follow 父链创建、raw/source/example physical-line lockstep verifier 和 D-005 exact target 优先级；智能体 2实施预审前不编码、不运行测试、不创建 processed、不下载下一源。
- required_reading:
  - `checkpoints/phase-01-data-core.md`
  - `checkpoints/phase-01-data-acquisition.md`
  - `decisions.md`
  - `../implementation/README.md`
  - `../experiments/README.md`
  - `../operations/README.md`
