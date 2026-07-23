# Kairos Agent Bootstrap

本文件只保存重新启动智能体时必须遵守的最小规则，并继承
`/home/yangbin/zx-tmp/AGENTS.md` 的全部约束。

1. 先读 `docs/ai-context/CURRENT.md`，再按其中的 `required_reading` 读取文档和检查点。
2. 只读核对当前 `git status`、分支、HEAD 和 remote；不得凭聊天记忆重复已经完成的工作。
3. 正式实验只能从 clean Git commit 启动，run manifest 必须记录源码 commit。
4. 实施使用单智能体直接推进：代码编写、测试、数据获取和实验运行合并到同一流程，不再要求独立的边界审计智能体。
5. 仅在关键里程碑（阶段完成、实验结果产出）更新 `CURRENT.md` 和 registry，不必每步都写 checkpoint。Git 提交保持原子化和可追溯。
6. 详细规则分别见：
   - `docs/ai-context/README.md`
   - `docs/operations/README.md`
   - `docs/implementation/README.md`
   - `docs/experiments/README.md`
   - `docs/git/README.md`
   - `docs/results/README.md`

本文件不保存方法细节、超参数、结果或长篇日志。
