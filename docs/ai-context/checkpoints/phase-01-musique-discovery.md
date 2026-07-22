# Phase 01 MuSiQue Metadata Discovery Checkpoint

- status: `COMPLETE` for metadata discovery only; acquisition is `UNVERIFIED`
- official_repository_commit: `922ac98f19a201998dbdae6d7f2887a5258dbdeb`
- raw_artifact: none
- processed_artifact: none
- run_id: none
- running_processes: none

## Evidence boundary

Agent 1先提交本地 discovery 计划，Agent 2分别批准仓库内论文核对与官方 primary-source metadata 访问。主智能体只读检查 Kairos PDF/TeX、固定 GitHub commit 的 README/LICENSE 和 ACL Anthology primary paper；未 clone、未下载数据 body、未创建目录、未运行项目代码或 GPU。

详细且唯一的事实清单位于 `../decisions.md` D-006。关键区分如下：

- Kairos PDF 第 4–5 页将 MuSiQue Ans 用于 418 条不可识别 temporal subset 的 answer-accuracy/CF 评测，但未发布 subset IDs、hash 或可重建映射。
- 官方 MuSiQue 将 `dev` 作为 validation 使用，并以 answer F1 与 paragraph support F1 作为标准指标；本项目的 `official validation + EM/F1 + CF accuracy` 是新增独立实验设计，不是 Kairos 原论文的精确指标声明。
- 固定 README 声明 Drive object `1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h` 包含 MuSiQue-Ans/Full 的 train/dev/test 与 dev/test single-hop leakage IDs；这些是 README 声明，不是已检查的本地 archive tree。

## Network observation

只对固定 Drive view URL 发起一次不跟随重定向、无 body 的 HEAD。连接在 10 秒后以 curl error 28 超时，未收到 HTTP response。命令使用过滤管道，外层状态 0 来自下游 `sed`，不能表示 curl 成功；可达性、redirect、MIME、Content-Length、archive 格式与大小全部保持 `UNVERIFIED`。未重试、未发 Range GET，也未暴露 Location、cookie 或 token。

## Gate

本检查点不冻结下载预算以外的 archive 事实，不登记 acquisition/run ID，不虚构 SHA256。下一步只能由 Agent 1提交单次有界 acquisition/probe 方案；Agent 2重新给出明确执行批准前，不得产生任何新网络请求、MuSiQue 数据文件、代码或实验运行。
