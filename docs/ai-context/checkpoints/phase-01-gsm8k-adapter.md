# Phase 01 GSM8K Adapter Checkpoint

- status: `COMPLETE` for implementation; Phase 01 remains `RUNNING`
- implementation_commit: `892b486b6bfb522de0aae4a675b651baf7ae1868`
- design_commits: `9cabff25cae65a730d30918d3251578b51397ece`, `7c49fe06cfa321b5677be581b6050ad92f094ca7`
- implementation_agent: Agent 1
- boundary_agent: Agent 2
- formal_run_id: none
- processed_artifact: none

## Scope

本检查点实现冻结的 D-005/D-005-A：generic `SourceProvenance`、GSM8K source ledger、strict raw parser、literal stable IDs、官方/internal split、13-key `TemporalExample` 映射、duplicate statistics、exact processed manifest、固定 CLI、immutable publication 与 physical-line raw/source/example lockstep verifier。

实现严格限制在：

- `src/kairos/schema.py`
- `src/kairos/gsm8k.py`
- `tests/test_schema_identity.py`
- `tests/test_gsm8k.py`

没有修改 acquisition、archive、ID 或 overwrite JSONL helper；production writer 不调用 `io.write_examples()`。

## Audit history

1. 首次 staged audit 为 `BLOCKED`：多处 close 可泄漏 FD/掩盖活动异常，且 canonical target 在终态仍可被替换后返回 `COMPLETE`；承诺的故障矩阵覆盖不足。
2. 第二次 staged audit 为 `BLOCKED`：前述实现缺陷已修复，但 `close`/部分 `content` fault hooks 尚未位于真实操作边界，且 canonical FD 打开后的 target replacement 尚未固化为测试。
3. 第三次 staged audit 独立重放真实 content 篡改、artifact-aware close、post-validation/pre-publication tamper 和 canonical-FD-held target replacement，返回 `APPROVED TO COMMIT`。

## Verification

- schema targeted: 16/16 passed
- GSM8K targeted: 47/47 passed
- targeted total: 63/63 passed
- full repository: 166/166 passed
- execution: Agent 1与主智能体分别使用项目局部 Python 独立通过
- fixtures: synthetic only under `/data0/hk_data/kairos-zx/.tmp`
- resources: 0 GPU, offline, CPU thread variables capped at 2, no dependency install
- publication tests: five artifacts by nine failure phases, plus real content tamper, close lifecycle, inode/path replacement and manifest/raw replay attacks

## Boundary

本检查点只批准实现提交和普通 non-force push。没有运行 production `prepare`/`verify`，没有读取真实 raw records，没有创建 `/data0/hk_data/kairos-zx/data/processed/gsm8k/.../source-record-v1`，也没有论文实验指标。正式转换必须从包含 implementation commit `892b486b6bfb522de0aae4a675b651baf7ae1868` 的最新 clean checkpoint HEAD 另行提交一次性执行单，并获得 Agent 2的 `APPROVED TO EXECUTE`。
