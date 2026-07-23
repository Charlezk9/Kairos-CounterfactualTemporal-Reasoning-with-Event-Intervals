# Results, Artifacts, and Author Report

## Artifact layout

大型工件保存在 `/data0/hk_data/kairos-zx/artifacts/<run-id>`。预测阶段的冻结 v2 集合为 `config.json`、`predictions.jsonl`、`generation-evidence.jsonl` 和最后发布的 `manifest.json`；聚合指标、checkpoint 和日志在后续阶段以 manifest 关联，不得改写这四个文件。仓库仅跟踪工件路径、revision、样本数和 SHA256。

run ID 使用稳定格式：`<UTC timestamp>-<method>-<dataset>-s<seed>-<short-config-hash>`。不得覆盖既有 run；重跑创建新 ID，并在 registry 中关联原因。

实现 `kairos.prediction_artifacts` 固定支持 `torque-dev` 和 `timeqa-hard`，要求完整 record-ID coverage 和 source order，并在发布前/manifest 前检查 clean exact HEAD。目录为 0700、文件为 0600、publication no-replace；offline verifier 重放 source adapter 和所有 SHA/schema。v1 底层始于 `f12efa05459daa982b4a5583abf22d48e38b9a1a`，v2 raw-generation evidence contract 在首次 production publication 前由 `f45c9e8c1adeee4f357ab7823ce1dbf287ff5d37` 冻结。首个 production artifact 是 `20260723T094748Z-direct-torque-dev-s13-ec6ea450f14d`；其状态与 SHA 见 experiment registry。

派生指标固定保存于 `/data0/hk_data/kairos-zx/artifacts/derived-metrics/<run-id>`，不得向已发布 prediction 目录追加文件。`kairos.metrics_artifacts` 只发布 canonical `metrics.json` 和最后发布的 `manifest.json`；发布前后重放 prediction/source，绑定 aggregation commit、prediction 四个 SHA，并由 offline verifier 重新聚合。实现 commit 为 `61e96bc58cd13bb4f5dc997ee678b86e81d9044a`。

配对推断固定保存于 `/data0/hk_data/kairos-zx/artifacts/derived-statistics/<comparison-id>`。`kairos.statistical_artifacts` 只发布 canonical `statistics.json` 和 manifest-last `manifest.json`，绑定两侧 prediction/metrics manifest，并在发布前后与离线验证时重新计算 10,000 次确定性 bootstrap。TORQUE 使用 `(passage_id, cluster_id)` 组级单位，TimeQA 使用 record 单位；95% percentile CI、add-one 双侧 bootstrap sign p-value 与 dataset 内指标族 Holm 校正的冻结实现 commit 为 `db6efe20a6317edac47343d1c713e9f4ec51263b`。

## Result states

- `REPORTED`：论文原值，未由本项目验证。
- `PRELIMINARY`：运行完成但尚未通过数据、统计和边界复核。
- `VERIFIED`：逐样本结果、聚合、commit 和工件哈希均通过复核。
- `REJECTED`：发现实现、数据或运行错误，不可用于论文，但保留记录。
- `DEFERRED`：缺少必要工件或授权。

## Aggregation and report

指标必须从逐样本预测重新聚合，生成 machine-readable metrics 和 bootstrap 结果。`build-author-report` 只更新 `docs/verify-addExp.md` 中明确标记的自动结果区块，不覆盖人工结论和限制。

每个论文表格行都必须能反查到 run ID、数据/model revision、样本数、seed、Git commit、配置和输出 SHA256。正式结果要求 clean commit。作者报告与 registry 不一致时，先标记为 `PRELIMINARY` 并修复来源，不手工改数字。
