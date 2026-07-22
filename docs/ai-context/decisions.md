# Implementation Decisions

本文件只记录无法从论文材料唯一恢复、且会影响可复现性的决定。任何正式测试结果可见后的修改必须追加新条目，不得静默改写旧决定。

## D-001：论文版本权威

- 状态：FROZEN
- 决定：以 `docs/kairos.pdf` 作为待验证的主要实验规格；`docs/main.tex` 视为较早版本。
- 理由：PDF 含表 1–8、CoT+Verifier、held-out template、第二骨干和完整反事实附录；TeX 缺少这些内容且数值冲突。
- 影响：PDF 数值全部标为 `REPORTED`，在独立运行前不能称为 reproduced。

## D-002：复现口径

- 状态：FROZEN
- 决定：使用 independent reimplementation；不以测试集调参逼近论文数值。
- 理由：作者源码、subset ID、完整 prompt、候选池和训练配置均不可用。

## 待在正式编码前冻结

- 事件抽取和 closest-compatible-pair 的精确定义。
- 字符跨度到 tokenizer span 的对齐规则。
- `overlaps`、`contains`、`during` 的方向、逆关系和对称性。
- hidden-state 层、span pooling、graph pooling 和投影维度。
- backbone frozen/LoRA 的主轨与敏感性轨。
- candidate 数量、prompt、采样和 verifier 规则。
- temporal subset 筛选与 UpdateAnswer 的可靠性判定。

## D-003：阶段 1 数据语义

- 状态：FROZEN
- relation 方向：`relation(a, b)` 始终描述事件 `a` 相对于事件 `b` 的关系。
- inverse：`precedes <-> follows`、`contains <-> during`；`overlaps` 与 `unknown` 自逆。`overlaps` 是对称关系，其他非 unknown 关系均保留方向。
- split：优先保留官方 split。需要从训练集划 internal dev 时，以 UTF-8 canonical source ID 的 SHA256 前 8 bytes 按 big-endian 转整数并 `% 10`；余数 0为 dev，其余为 train。原样本及其全部反事实使用同一 source ID，因此不得跨组。禁止 Python `hash()`。
- 初版事件抽取：只处理文本中唯一且两侧非空的明确 marker；以最近 `.?!;` 边界内、marker 左右的去空白文本作为两个保守 event span，并保留字符偏移。多 marker、空侧、跨度重叠或嵌套、以及无法唯一对齐的文本必须返回结构化拒绝 reason。
- 初版可靠 marker：`before`、`after`、`earlier than`、`later than`、`prior to`。`while`、`when`、`until`、`then` 和隐式关系在 v0 中拒绝，不得把 v0 称为最终事件抽取器。
- counterfactual 改写白名单：只允许 `before <-> after` 与 `earlier than <-> later than`，并要求文本中 marker 唯一、替换后仍唯一且非目标文本逐字符不变。`prior to` 可检测但 v0 不生成反事实。
- UpdateAnswer：只有 task-specific deterministic updater 能证明新答案时才写 `known`。明确 earlier/later event-choice 且原答案精确匹配目标事件时可交换答案；关系型 yes/no 只有问题精确查询被改变关系时才由 truth table 更新。numeric、自由生成、无法唯一匹配或答案与目标关系无关时均标 `unknown`，从反事实 answer supervision 排除；禁止复制原答案充当 CF gold。
- scope：该决定只定义可测试的保守 v0 数据核心；扩展 parser 或隐式关系前必须追加新决定并重新审核。

## D-004：官方数据源与可识别性边界

- 状态：FROZEN BEFORE DOWNLOAD
- 原始四数据集的官方来源：
  - GSM8K：`https://github.com/openai/grade-school-math.git` @ `3101c7d5072418e28b9008a6636bde82a006892c`；使用 `train.jsonl`/`test.jsonl`。
  - MuSiQue：`https://github.com/StonyBrookNLP/musique.git` @ `922ac98f19a201998dbdae6d7f2887a5258dbdeb`；数据使用该 revision README 指向的官方 Google Drive archive `1tGdADlNjWFaHLeZZGShh2IRcpO6Lv24h`，不执行上游脚本。
  - StrategyQA：官方 archive `https://storage.googleapis.com/ai2i/strategyqa/data/strategyqa_dataset.zip`（读取时 ETag `f4ae9d9296c06f90d80aee1e4a25d58a`，Last-Modified `2021-01-07`）；代码/非官方 90/10 split 参考 `https://github.com/eladsegal/strategyqa.git` @ `1ba1e97452e189569357876f2854b01357ffbe37`。
  - 2WikiMultihopQA：`https://github.com/Alab-NII/2wikimultihop.git` @ `13800e5be57df1b4040b9b1588c6c811779e69e9`；数据使用该 revision README 指向的修正版 `data_ids_april7.zip`，不静默回退到旧 archive。
- 新增迁移数据集：
  - TORQUE：`https://github.com/qiangning/TORQUE-dataset.git` @ `ab27019cc6a317fde3c879900499f02acce8b16d`，Apache-2.0；使用有 gold 注释的官方 dev，test 注释已由作者移除。
  - TimeQA：`https://github.com/wenhuchen/Time-Sensitive-QA.git` @ `38b05989070c1168b2bef3d5a2656afeeba763dc`，BSD-3-Clause；冻结评测文件为 `dataset/human_test.hard.json`。
- 许可：GSM8K/StrategyQA 官方仓库为 MIT，MuSiQue 为 CC-BY-4.0，2Wiki/TORQUE 为 Apache-2.0，TimeQA 为 BSD-3-Clause；每个 upstream LICENSE 必须随 snapshot 保存并在 manifest 中记录。
- 可识别性：论文没有发布原始四数据集的 temporal subset IDs、完整筛选器或 counterfactual pair IDs。因此下载官方 raw data 不能使表 1–8的精确样本变得可识别；后续只能报告 independent reconstruction，不得用测试结果反向选 subset 追平论文数字。
- 下载协议：所有原始工件只写入 `/data0/hk_data/kairos-zx/data/raw/<dataset>/<revision>/`；先保存 archive/repository snapshot，计算 SHA256，然后解压到同 revision 下的 `extracted/`。禁止执行上游脚本，禁止将 raw data 纳入项目 Git。
- 可达性：MuSiQue Drive 与 2Wiki Dropbox 的 URL/ID 已由固定 commit README 确认，但 2026-07-22 在本机的 HEAD 请求超时，因此 availability 与 archive size 为 `UNVERIFIED`。实际获取失败时不得改用第三方镜像。

## D-004-A：GSM8K 直连快照获取与完成语义

- 状态：FROZEN BEFORE DOWNLOAD
- 运行范围：仅 `openai/grade-school-math` commit `3101c7d5072418e28b9008a6636bde82a006892c` 的 `codeload.github.com` TAR.GZ。该 URL 已是最终直连，本运行不允许 redirect，effective URL 必须与冻结 URL 逐字符一致。这一单源规则优先于 D-004 的通用 `--location` 门禁，不外推到其他源。
- curl：首参数必须为 `--disable`，禁止读取 `.curlrc`，不使用 netrc/config；只使用 `/usr/bin/curl` 7.68 已支持的选项。`--max-filesize 1073741824` 仅为辅助检查，必须同时以 `/usr/bin/prlimit --fsize=1073741824:1073741824` 对 curl 进程实施 1 GiB OS 硬上限，且仅 exit 0 才进入校验。
- 布局：stage 与 revision root 必须以 mode 0700 新建且不得复用。已验证的 stage archive 以 `O_CREAT|O_EXCL|O_NOFOLLOW` 独立复制为 revision root 下的 `source.tar.gz`，flush/fsync/关闭后重算 SHA256；不保留指向正式 archive 的可写 hardlink 别名。解压固定到 `extracted/`。
- 内容验证：固定相对路径为 `extracted/grade-school-math-3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/data/train.jsonl` 和 `.../test.jsonl`，条数分别为 7473/1319。在 `json.loads` 前按原始 bytes 限制每行最多 1,048,576 bytes；拒绝空行、非 object 以及空/非字符串 `question`/`answer`。
- 清单：`SHA256SUMS` 按 UTF-8 相对路径字节序覆盖 revision root 中当时的全部 regular files，只排除 `SHA256SUMS`、`completion-manifest.json` 及其私有临时文件；任何 symlink、特殊文件、缺失或额外文件均使校验失败。
- completion：先在 revision root 写入排他私有临时文件，flush+fsync+关闭后回读 JSON，校验 `status=COMPLETE`、完整字段、`SHA256SUMS` 的 SHA256 与全清单；再通过同目录 hardlink no-replace 原子发布为 `completion-manifest.json`，删除私有名后 fsync 目录。下游必须重新解析 manifest 并重验证状态、清单哈希、全部条目与无额外文件；不得仅检查文件存在。
- 失败：任一失败保留 stage/partial revision root 作证据，不覆盖、清理、续传或在原目录重试。未通过 completion 全量校验的 revision 不可消费。
