# Results, Artifacts, and Author Report

## Artifact layout

大型工件保存在 `/data0/hk_data/kairos-zx/artifacts/<run-id>`。建议每个 run 包含 `manifest.json`、配置快照、逐样本预测、聚合指标、checkpoint（如适用）和日志。仓库仅跟踪工件路径、revision、样本数和 SHA256。

run ID 使用稳定格式：`<UTC timestamp>-<method>-<dataset>-s<seed>-<short-config-hash>`。不得覆盖既有 run；重跑创建新 ID，并在 registry 中关联原因。

## Result states

- `REPORTED`：论文原值，未由本项目验证。
- `PRELIMINARY`：运行完成但尚未通过数据、统计和边界复核。
- `VERIFIED`：逐样本结果、聚合、commit 和工件哈希均通过复核。
- `REJECTED`：发现实现、数据或运行错误，不可用于论文，但保留记录。
- `DEFERRED`：缺少必要工件或授权。

## Aggregation and report

指标必须从逐样本预测重新聚合，生成 machine-readable metrics 和 bootstrap 结果。`build-author-report` 只更新 `docs/verify-addExp.md` 中明确标记的自动结果区块，不覆盖人工结论和限制。

每个论文表格行都必须能反查到 run ID、数据/model revision、样本数、seed、Git commit、配置和输出 SHA256。正式结果要求 clean commit。作者报告与 registry 不一致时，先标记为 `PRELIMINARY` 并修复来源，不手工改数字。
