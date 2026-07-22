# Kairos Agent Bootstrap

本文件只保存重新启动智能体时必须遵守的最小规则，并继承
`/home/yangbin/zx-tmp/AGENTS.md` 的全部约束。

1. 先读 `docs/ai-context/CURRENT.md`，再按其中的 `required_reading` 读取文档和检查点。
2. 只读核对当前 `git status`、分支、HEAD 和 remote；不得凭聊天记忆重复已经完成的工作。
3. 正式实验只能从 clean Git commit 启动，run manifest 必须记录源码 commit。
4. 实施使用两个工作智能体：智能体 1负责代码与测试；智能体 2只负责路径、资源、Git/SSH 边界审计。
5. 每个关键进度必须更新 `CURRENT.md`、相应 checkpoint、registry 和作者结果文件，再创建 Git 提交。
6. 详细规则分别见：
   - `docs/ai-context/README.md`
   - `docs/operations/README.md`
   - `docs/implementation/README.md`
   - `docs/experiments/README.md`
   - `docs/git/README.md`
   - `docs/results/README.md`

本文件不保存方法细节、超参数、结果或长篇日志。
