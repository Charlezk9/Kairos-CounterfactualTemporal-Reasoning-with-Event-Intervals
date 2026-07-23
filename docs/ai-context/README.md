# AI Context 与恢复协议

本目录保存智能体重启后恢复任务所需的短状态、阶段证据和运行索引。详细方法、实验设计和 Git 操作分别由其他 README 维护。

## 重启顺序

1. 读取 `/home/yangbin/zx-tmp/AGENTS.md`。
2. 读取 `/home/yangbin/zx-tmp/kairos/AGENTS.md`。
3. 读取 `CURRENT.md`。
4. 只读执行 `git status --short --branch`、`git rev-parse HEAD` 和 `git remote -v`。
5. 阅读 `CURRENT.md` 指向的阶段 checkpoint 和相关 README。
6. 检查运行中的进程、GPU 和 registry；不得假设重启前的任务仍在运行。
7. 从 `next_safe_action` 继续，不重跑已完成且有哈希证据的阶段。

## 文件职责

- `CURRENT.md`：唯一的当前状态入口，只保存阶段、HEAD、阻塞项和下一安全动作。
- `checkpoints/phase-*.md`：阶段计划、审批、验证证据和完成判定。
- `decisions.md`：论文未说明事项的决定、理由和影响。
- `discrepancies.md`：PDF、TeX、代码和复现实验之间的差异。
- `implementation-log.md`：按时间追加的人类可读执行日志。
- `experiment-registry.md`：run ID、配置、数据/模型 revision、commit 和工件哈希。
- `sandbox-audit.md`：旧双智能体阶段的历史只读审批结论；审计模式放松后只作不可改写的历史证据，不是新里程碑的完成前提。

## CURRENT 字段

`CURRENT.md` 保存 `updated_at`、`active_phase`、`phase_status`、`git_branch`、`git_head`、`last_verified_commit`、`last_completed_checkpoint`、`active_run_ids`、`running_processes`、`blockers`、`next_safe_action` 和 `required_reading`。

## 状态与完成规则

checkpoint 使用 `PLANNED`、`APPROVED`、`RUNNING`、`COMPLETE`、`BLOCKED`。当前单智能体模式下，阶段只有同时满足以下条件才能标为 `COMPLETE`：预定测试通过、工件可追溯、安全与路径门禁已由主智能体核对、相关文档更新、Git 提交存在。历史 checkpoint 中的双智能体审批记录继续保留但不外推为当前要求。正式结果不得仅以终端输出或聊天记录作为证据。

如果状态文件与 Git/registry 冲突，以 Git 工件和 registry 为准；先修正状态并提交，再继续。失败实验也应登记，不能删除其存在记录。未完成运行恢复前先验证 PID、命令行、GPU 和输出目录的归属，不结束来源不明的进程。
