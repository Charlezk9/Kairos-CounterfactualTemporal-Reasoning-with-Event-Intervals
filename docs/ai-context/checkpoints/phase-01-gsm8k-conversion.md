# Phase 01 GSM8K Production Conversion Checkpoint

- status: `COMPLETE` for the GSM8K source/example conversion; Phase 01 remains `RUNNING`
- artifact_id: `PROC-P01-GSM8K-20260722`
- source_revision: `3101c7d5072418e28b9008a6636bde82a006892c`
- acquisition_id: `ACQ-GSM8K-20260722`
- adapter_implementation_commit: `892b486b6bfb522de0aae4a675b651baf7ae1868`
- execution_commit: `3e34c9c6da06a0364b84ef97492331e59a764a45`
- formal_model_run_id: none
- running_processes: none

## Gate and execution

Agent 1提交单次执行单，Agent 2在核对 clean HEAD、资源、固定路径、target absent、失败保留和非内容证据边界后给出 `APPROVED TO EXECUTE`。执行前 Git branch/HEAD/remote/upstream 均与批准快照一致；`/data0` 可用 181 GiB，局部 Python 使用 0 GPU、最多 2 个 CPU 线程和完全局部 cache/temp。

固定 target 在执行前既不存在也不是 dangling symlink。仅执行一次：

1. `python -m kairos.gsm8k prepare --adapter-commit 3e34c9c6da06a0364b84ef97492331e59a764a45`，exit 0。
2. `python -m kairos.gsm8k verify`，exit 0。

二者返回完全一致的 canonical manifest。未重试、未启动后台任务、未下载、未训练、未推理，也未回显真实 source/example 行、question、answer、record ID 或逐记录 hash。

## Immutable artifact

固定目录：`/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/source-record-v1`

目录为 0700，且恰含下列五个 0600 regular、`nlink=1` 文件：

| File | Lines | Bytes | SHA256 |
|---|---:|---:|---|
| `source-train.jsonl` | 7,473 | 8,120,014 | `e8a9f8ac7629736a6107d8d3ce6482381e3625f6eddd3371830f7056816cdbf3` |
| `source-test.jsonl` | 1,319 | 1,440,301 | `fe1b352dca874abe61cde8b1f0d78f684f68c8bf706aa6da38838b37042546e0` |
| `examples-train.jsonl` | 7,473 | 7,236,805 | `485ef8996a700958a327ed5888467f630274ecff105249f88b008e8cf88d5be2` |
| `examples-test.jsonl` | 1,319 | 1,286,440 | `b0b14552e13e6390a8e40187e76d5f65e2d29e49146e4757a10759ba98cd1a97` |
| `processed-manifest.json` | 1 | 2,427 | `48f1df79303cf41efc986c762744c0550cecb07689abaf77a4ebde202b6ee4fe` |

Manifest 记录 train/test question duplicate group、question duplicate record、raw-record duplicate group 和 raw-record duplicate record 八个统计均为 0。该结果只描述固定 upstream GSM8K revision 的 source-ledger/canonical-example 转换，不代表论文 temporal subset、事件构造、模型效果或论文指标。

## Post-audit

Agent 2未再次运行 conversion/verifier，也未读取内容；其只读核验确认 namespace、权限、owner、link count、大小、Git clean、upstream 0/0、181 GiB 余量和无残留 `kairos.gsm8k` 进程，结论为 `POST-AUDIT APPROVED`。后续不得在该 immutable target 上重跑、覆盖或清理。
