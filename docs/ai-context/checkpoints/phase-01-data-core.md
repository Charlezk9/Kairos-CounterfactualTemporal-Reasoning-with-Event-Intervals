# Phase 01 Data Core Checkpoint

- status: RUNNING
- branch: `experiment/reproduction-additional-evaluation`
- base_commit: `82f5cb1cb01f870cab72e5abb651cfe9965e5a46`
- implementation_agent: agent 1
- boundary_agent: agent 2

## Scope

本检查点只覆盖不依赖外部数据的确定性数据核心：严格 JSONL schema、稳定 ID、官方/internal split、保守显式时间 marker、反事实 marker 改写、确定性 `UpdateAnswer` 与构造漏斗。它不是完整阶段 1验收；数据 revision、许可、原始文件 SHA256、真实构造统计和两人 200 条人工审计仍待数据源接入。

冻结语义见 `../decisions.md` 的 D-003。该实现只使用 Python 标准库，不安装依赖、不联网、不调用 GPU。

## Pre-execution approval

智能体 2批准在 `src/kairos/` 与 `tests/` 内进行上述实现，门禁为：测试缓存和临时文件必须在 `/data0/hk_data/kairos-zx`；不得写 Git/docs，不得下载或运行高资源任务。

## Verification evidence

local Python 与可复跑命令如下（从仓库根目录执行）：

```bash
CONDARC=/data0/hk_data/kairos-zx/.condarc \
CONDA_PKGS_DIRS=/data0/hk_data/kairos-zx/.conda/pkgs \
PIP_CACHE_DIR=/data0/hk_data/kairos-zx/.cache/pip \
HF_HOME=/data0/hk_data/kairos-zx/.cache/huggingface \
HF_HUB_CACHE=/data0/hk_data/kairos-zx/.cache/huggingface/hub \
XDG_CACHE_HOME=/data0/hk_data/kairos-zx/.cache \
TORCH_HOME=/data0/hk_data/kairos-zx/.cache/torch \
TRITON_CACHE_DIR=/data0/hk_data/kairos-zx/.cache/triton \
TMPDIR=/data0/hk_data/kairos-zx/.tmp \
TMP=/data0/hk_data/kairos-zx/.tmp \
TEMP=/data0/hk_data/kairos-zx/.tmp \
PYTHONPYCACHEPREFIX=/data0/hk_data/kairos-zx/.cache/pycache \
PYTHONPATH=/home/yangbin/zx-tmp/kairos/src \
/data0/hk_data/kairos-zx/.conda/envs/kairos/bin/python \
  -m unittest discover -s tests -p 'test_*.py' -v
```

- result: 27 tests passed on 2026-07-22 after post-audit fixes
- GPU use: none
- network/download: none

## Post-audit

智能体 2的首次 staged-diff 审计为 `BLOCKED`：需拒绝与被改变 relation 无关的 yes/no 更新、拒绝 canonical JSON 的非字符串 mapping key，并记录完整可复跑环境命令。两项实现均已修复并新增回归测试；27 项测试已用上述完整命令通过。第二次审计又发现命令中 `CONDARC` 路径误写，现已指向实际存在的项目局部 `/data0/hk_data/kairos-zx/.condarc`，等待最终复核。

## Pending gates

1. staged-diff re-audit by agent 2;
2. clean commit and push;
3. official dataset source/revision decision and adapter implementation;
4. real construction funnel and required human audit.
