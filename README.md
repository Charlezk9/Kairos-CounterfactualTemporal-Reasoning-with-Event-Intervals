# Kairos Counterfactual Temporal Reasoning

本仓库用于对论文 *Counterfactual Temporal Reasoning with Event Intervals* 进行可审计的独立重实现，并补充标准时间推理数据集和强 Baseline。当前材料没有作者源码、原始 temporal subset ID 或完整训练配置，因此所有工作均标记为 **independent reimplementation**，不得表述为作者代码的严格复跑。

论文支持的核心 claim 被限定为：显式事件区间、事件关系图和反事实监督，能提高事件顺序改变时的关系更新与答案一致性；项目不预设 general temporal QA SOTA 结论。

## 位置

- 源码、测试、轻量配置和文档：`/home/yangbin/zx-tmp/kairos`
- 局部 Conda、数据、缓存和实验工件：`/data0/hk_data/kairos-zx`
- 固定 Qwen 模型：`/data0/hk_data/kairos-zx/models/Qwen2.5-7B-Instruct/a09a35458c702b33eeacc393d103063234e8bc28`
- 当前状态：`docs/ai-context/CURRENT.md`
- 同伴作者结果文件：`docs/verify-addExp.md`

大型数据、模型、checkpoint、逐样本预测和日志不得进入本仓库。

## 文档导航

- 上下文恢复、检查点和运行登记：`docs/ai-context/README.md`
- 服务器、环境、资源与双智能体审批：`docs/operations/README.md`
- 方法、数据结构、CLI 与测试：`docs/implementation/README.md`
- 数据集、Baseline、指标与统计方案：`docs/experiments/README.md`
- Git、项目专用 SSH 和提交规则：`docs/git/README.md`
- 结果工件、聚合和作者报告：`docs/results/README.md`

## 最短安全启动流程

1. 阅读父级和项目级 `AGENTS.md`。
2. 阅读 `docs/ai-context/CURRENT.md`。
3. 只读检查 Git 分支、HEAD、工作树和 remote。
4. 阅读 `CURRENT.md` 指向的 checkpoint 与 README。
5. 高资源任务前按 operations 文档检查 GPU、内存和磁盘。
6. 只执行 `next_safe_action`，完成后更新检查点并提交。
