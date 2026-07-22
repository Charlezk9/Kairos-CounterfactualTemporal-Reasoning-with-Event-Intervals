# Phase 01 Official Data Acquisition Checkpoint

- status: IN PROGRESS; GSM8K COMPLETE, FIVE SOURCES NOT STARTED
- branch: `experiment/reproduction-additional-evaluation`
- planning_commit: `b6491ec501ad18115bf5d3588cb250e01891d1e2`
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
5. 只使用 `/usr/bin/curl` 7.68.0，不使用 PATH 中的 Anaconda curl。首参数必须是 `--disable` 以禁用 `.curlrc`，不使用 netrc/config。通用命令必须含该版本支持的 `--proto '=https' --proto-redir '=https' --fail --location --retry 3 --retry-connrefused --retry-delay 2 --retry-max-time 120 --connect-timeout 20 --max-time 1800 --max-filesize <remaining-bytes>`，并以 `prlimit --fsize` 实施 OS 级单文件硬上限。顺序前台下载到新的 `*.part`，不覆盖任何已有路径。保存 effective URL，只允许冻结源的官方 host：GitHub `github.com`/`codeload.github.com`，StrategyQA `storage.googleapis.com`，MuSiQue `drive.google.com`/`drive.usercontent.google.com`，2Wiki `www.dropbox.com`/`dl.dropboxusercontent.com`。GSM8K 固定 codeload 直连例外按 `../decisions.md` D-004-A 执行：不用 `--location`，effective URL 必须逐字符一致。
6. 下载后先检查 effective host、Content-Type/实际 archive 格式、SHA256 和成员列表；任一失败则保留 `.part` 作为证据并停止，不改最终名。全部验证通过且最终路径不存在时，才按数据源冻结规则发布 immutable archive；GSM8K 必须按 D-004-A 独立 O_EXCL 复制、fsync 并重算 SHA，不得 hardlink stage archive。
7. validator 必须拒绝绝对路径、`..`/`.`/空异常 component、Windows drive prefix、反斜杠和 NUL；只允许普通文件与目录，拒绝 symlink、hardlink、block/char device、FIFO 与其他特殊类型。ZIP 必须在构造 `ZipFile` 前预检 EOCD/中心目录；TAR 必须先有界扫描 header/PAX/GNU metadata，不得调用 `getmembers`。解压前汇总成员数、metadata 与声明展开总字节；源与目标路径必须为绝对且全链无 symlink，使用根锚定 dirfd/相对 `O_NOFOLLOW|O_EXCL` 操作。只解压到刚创建的空 `extracted/`，失败保留 partial 证据且不覆盖或清理旧目录。仅当 completion manifest 已被重新解析且其状态、清单哈希、全部条目和无额外文件条件均通过时，adapter 才可消费 `extracted/`，不得仅依赖 completion 文件存在。禁止保留上游 owner/permission。
8. 不执行任何上游代码、`download_data.sh`、`gdown` 或交互流程。下载后智能体 2复核实际写入集、容量、残留进程和 manifest。

GSM8K 的 archive promotion、JSONL 单行上限、清单覆盖集、completion 原子发布和下游全量校验均以 D-004-A 为唯一详细来源。

MuSiQue Google Drive 和 2Wiki Dropbox 的官方 archive 在预检时未能于 10–20 秒内完成 HEAD 请求，故 availability/size 为 `UNVERIFIED`。执行时允许对 D-004 已冻结的官方 URL 做有界前台下载；若不可达、超出预算、HTTP 失败、需要交互、返回 HTML/登录页或跳转非允许 host，立即标记该源 `BLOCKED`。禁止静默改用第三方镜像或旧版 archive。

## Expected outputs

- 每个 source 的 immutable archive/snapshot、`extracted/`、upstream LICENSE/README 和 `SHA256SUMS`。
- 一份不含 raw records 的仓库级 source manifest/checkpoint 摘要。
- 仅在检查真实文件后冻结 D-005（实际 split/schema/adapter 决定）。

## Validator implementation checkpoint

- source plan commit: `b6491ec501ad18115bf5d3588cb250e01891d1e2`
- validator commit: `c57a133cf7c05f049ca16f8e43d29302480ec411`
- implementation: `src/kairos/archive_safety.py`
- APIs: `inspect_archive` / `safe_extract` / `normalize_member_path`
- supported formats: ZIP, TAR, TAR.GZ
- behavior: ZIP EOCD and every central/local header are bounded and cross-checked before `ZipFile`; the central directory must end exactly at EOCD, actual entry count and byte range must match EOCD, central/local version-needed, flags, compression, CRC and sizes must agree, and data descriptors, ZIP64 and multi-disk are rejected. TAR header/extended-metadata limits likewise run before standard-library archive materialization. Full SHA/member/content inspection, path/type/member/metadata/expanded-byte gates, absolute symlink-free source/destination paths, archive SHA/fstat checks before/after inspection and after extraction, and root-anchored dirfds with streamed `O_NOFOLLOW|O_EXCL` writes are mandatory. Output modes are normalized to 0755/0644 and partial extraction is retained on failure.
- verification: 49/49 repository unit tests passed with the project-local Python and all cache/temp variables directed to `/data0/hk_data/kairos-zx`
- residual scope: nested archives are not recursively inspected; the module does not claim to resist a malicious external process concurrently replacing destination parent directories
- status: first staged audit was `BLOCKED` on unbounded metadata, in-place source mutation and symlink/parent-race defects. Second staged audit was `BLOCKED` because a forged EOCD count could hide additional central entries and local ZIP64 metadata was incompletely rejected. Third staged audit verified those fixes but remained `BLOCKED` on central-to-EOCD gaps and incomplete local-header field comparison. All three remediation sets and regressions were independently replayed, the final verdict was `APPROVED TO COMMIT`, and validator commit `c57a133` was pushed by ordinary non-force update with matching local/remote SHA. This does not approve real data download, and no real data has been downloaded.

## Acquisition helper implementation checkpoint

- protocol commits: `efb0cfd3add3b3b1bec6209ad5ab6066ec88aba0`, `f3003a290d01f1ce72e77cb973c3aa9aefc3776a`
- implementation commit: `ca759ac26bfc0bd64ee25a9732c20d8ea335a362`
- implementation: `src/kairos/acquisition.py`
- production CLI: fixed-path `validate-stage`, `finalize`, `verify`; no network, subprocess, path option or environment override
- scope: strict HTTP observation; independent archive copy; fd-relative tree and GSM8K validation; canonical SHA256SUMS; fsync plus no-replace completion publication; full offline verification
- verification: 62 acquisition tests, 26 archive-safety tests and 115/115 full repository tests passed with all test temp/cache paths directed to `/data0/hk_data/kairos-zx`
- status: implementation plan was first `BLOCKED`, D-004-A was hardened, and the revised plan received `APPROVED TO IMPLEMENT`. The first staged audit was `BLOCKED` on path reopen, copied-archive identity, quadratic validation and publication order. The second audit remained `BLOCKED` on pair lifetime, complete canonical chain, formal-root protocol entries and guard publication order. The third audit then blocked on the outer pair lifetime, complete terminal fingerprint and held-pair close semantics. The fourth audit found the same cleanup defect in canonical temporary FDs. A shared fixed-snapshot best-effort closer now covers held and canonical pairs; final/guard/both close, active validation and partial-open regressions pass without masking primary errors. The fifth complete staged audit independently replayed all prior attack and cleanup paths and returned `APPROVED TO COMMIT`. Commit `ca759ac26bfc0bd64ee25a9732c20d8ea335a362` was pushed by ordinary non-force update with matching local/remote SHA. That implementation approval did not authorize download; the later separately approved execution is recorded below.

## GSM8K acquisition result

- acquisition ID: `ACQ-GSM8K-20260722`
- status: `COMPLETE` (source integrity only; not an experiment run)
- completed at: `2026-07-22T09:20:01.531117+00:00`
- provenance commit: `482af857249b03d89c986dce96c9d38fc11cfd70`
- source revision: `3101c7d5072418e28b9008a6636bde82a006892c`
- fixed/effective URL: `https://codeload.github.com/openai/grade-school-math/tar.gz/3101c7d5072418e28b9008a6636bde82a006892c`
- HTTP: curl exit 0, status 200, MIME `application/x-gzip`, size `4,447,003` bytes
- archive SHA256: `19ab616f7ad67a18250e57eba3b57b8ff9b1d365055fd59839613424c24afb6a`
- archive: 18 members, `14,356,149` declared expanded bytes; stage/formal copies have different inodes and `nlink=1`
- dataset: `train.jsonl` 7,473 rows; `test.jsonl` 1,319 rows
- SHA256SUMS: 15 entries, strict 15/15 verification, file SHA256 `fb6bb5349ea5a620062f34cda78eb4faed2aa8a6ec9cf43ad54010904b813107`
- formal tree fingerprint: `6b52e122a14c0f78baf3fc0b046b312b780518771828702acf074ab8ac95583f`
- completion manifest SHA256: `d8861250e197bf04e1f24fee4dbb7bfe07194f485095f77cdcc8669412e35047`
- completion pair: device 2048, inode 176825412, guard/final both `nlink=2`
- paths: fixed stage and revision under `/data0/hk_data/kairos-zx/data/raw/gsm8k/`; raw top-level contains only `gsm8k`
- storage: GSM8K `23,287,235` bytes; project-root pre/post `28,380,762,718` / `28,404,058,145` bytes; delta `23,295,427` bytes including 8,192 bytes of new parent directories
- post-run available bytes: `193,444,249,600`
- audit: main and boundary-agent offline verify passed; no symlink/special files, non-protocol hardlinks, residual curl/acquisition process, background job, or task GPU use

The approved download scope ended with this source. MuSiQue, StrategyQA, 2Wiki, TORQUE and TimeQA remain not acquired; no mirror or second run is authorized by this checkpoint.
