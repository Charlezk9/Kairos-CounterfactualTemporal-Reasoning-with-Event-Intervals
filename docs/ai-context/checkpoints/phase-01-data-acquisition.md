# Phase 01 Official Data Acquisition Checkpoint

- status: PLANNED
- branch: `experiment/reproduction-additional-evaluation`
- planning_commit: pending
- implementation_agent: agent 1
- boundary_agent: agent 2

## Read-only source verification

2026-07-22 只读核验了论文与六个数据源。官方 revision、archive 和许可决策的唯一来源为 `../decisions.md` D-004。GitHub 元数据显示六个仓库尺寸合计远低于 1 GiB；MuSiQue 和 2Wiki 的外部官方 archive 尺寸须在实际下载进度中监控。

## Proposed write set

- `/data0/hk_data/kairos-zx/data/raw/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/`
- `/data0/hk_data/kairos-zx/data/raw/musique/922ac98f19a201998dbdae6d7f2887a5258dbdeb/`
- `/data0/hk_data/kairos-zx/data/raw/strategyqa/official-20210107/`
- `/data0/hk_data/kairos-zx/data/raw/2wikimultihopqa/13800e5be57df1b4040b9b1588c6c811779e69e9/`
- `/data0/hk_data/kairos-zx/data/raw/torque/ab27019cc6a317fde3c879900499f02acce8b16d/`
- `/data0/hk_data/kairos-zx/data/raw/timeqa/38b05989070c1168b2bef3d5a2656afeeba763dc/`

不写入仓库数据目录、`/tmp`、默认 cache 或其他用户目录。

## Mandatory preflight and execution gates

1. 智能体 2审核 URL、revision、许可、目标路径和命令边界。
2. 下载前由智能体 1实现只使用 Python 标准库的 archive validator/extractor，并由智能体 2审核测试与 staged diff；未通过不得下载。
3. 运行 `nvidia-smi`、`free -h`、`df -h /home/yangbin/zx-tmp /data0/hk_data/kairos-zx`；本次 GPU 预算为 0，CPU 不超过 2 线程。
4. `/data0` 可用空间小于 120 GiB 立即停止；本次新增磁盘硬限 8 GiB。每次获取前按当前 raw 目录实际字节重算 remaining bytes，下载与声明展开字节任一超过余额即停止。archive 成员数上限 200,000。
5. 只使用 `/usr/bin/curl` 7.68.0，不使用 PATH 中的 Anaconda curl。命令必须含该版本支持的 `--proto '=https' --proto-redir '=https' --fail --location --retry 3 --retry-connrefused --retry-delay 2 --retry-max-time 120 --connect-timeout 20 --max-time 1800 --max-filesize <remaining-bytes>`，顺序前台下载到新的 `*.part`，不覆盖任何已有路径。保存 effective URL，只允许冻结源的官方 host：GitHub `github.com`/`codeload.github.com`，StrategyQA `storage.googleapis.com`，MuSiQue `drive.google.com`/`drive.usercontent.google.com`，2Wiki `www.dropbox.com`/`dl.dropboxusercontent.com`。
6. 下载后先检查 effective host、Content-Type/实际 archive 格式、SHA256 和成员列表；任一失败则保留 `.part` 作为证据并停止，不改最终名。全部验证通过且最终路径不存在时，才将 `.part` 改为 immutable archive 名。
7. validator 必须拒绝绝对路径、`..`/`.`/空异常 component、Windows drive prefix、反斜杠和 NUL；只允许普通文件与目录，拒绝 symlink、hardlink、block/char device、FIFO 与其他特殊类型。解压前汇总成员数和声明展开总字节；只解压到刚创建的空 `extracted/`，失败不覆盖或清理旧目录。tar 等价操作必须禁止保留 owner/permission。
8. 不执行任何上游代码、`download_data.sh`、`gdown` 或交互流程。下载后智能体 2复核实际写入集、容量、残留进程和 manifest。

MuSiQue Google Drive 和 2Wiki Dropbox 的官方 archive 在预检时未能于 10–20 秒内完成 HEAD 请求，故 availability/size 为 `UNVERIFIED`。执行时允许对 D-004 已冻结的官方 URL 做有界前台下载；若不可达、超出预算、HTTP 失败、需要交互、返回 HTML/登录页或跳转非允许 host，立即标记该源 `BLOCKED`。禁止静默改用第三方镜像或旧版 archive。

## Expected outputs

- 每个 source 的 immutable archive/snapshot、`extracted/`、upstream LICENSE/README 和 `SHA256SUMS`。
- 一份不含 raw records 的仓库级 source manifest/checkpoint 摘要。
- 仅在检查真实文件后冻结 D-005（实际 split/schema/adapter 决定）。
