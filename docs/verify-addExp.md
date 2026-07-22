# Kairos 补充实验技术与结果报告

> 状态：PLANNED
> 本文件是同伴作者引用补充实验的唯一汇总来源。当前所有论文数字均为 `REPORTED`，尚无本项目 `VERIFIED` 实验结果。

## 1. 文档状态与执行摘要

- 当前阶段：Phase 01，deterministic data core implementation
- 复现性质：independent reimplementation
- 已完成实验：无
- 当前结论：尚不能验证论文数值或新增 claim

## 2. 复现范围、版本与 Git commit

restart-safe bootstrap commit 为 `989634284e58b733e0bca2520fd0e7caad930e4c`。以 `kairos.pdf` 为主要待验证规格，`main.tex` 为较早且数值冲突的版本。

## 3. PDF、TeX 与重实现差异

详细差异见 `docs/ai-context/discrepancies.md`。PDF 的 Overall Kairos Standard/CF/Average 为 0.610/0.604/0.607；TeX 为 0.272/0.251/0.262。两组数值当前均未由代码和数据支持。

## 4. 技术实现路径

阶段 1已实现第一个开发检查点：严格 JSONL schema、relation inverse、稳定 ID 与 split、唯一显式 marker 抽取、白名单反事实改写、保守 `UpdateAnswer` 和构造漏斗。该版本只支持 D-003 声明的高精度 v0 语义，不是通用事件抽取器。包含嵌套 schema、非字符串 canonical key 拒绝和无关 relation 更新拒绝的 27 项开发单元测试通过；未开始真实数据构造，因此未产生 `VERIFIED` 实验结果。

数据获取前置实现已增加不使用 `extractall`/`getmembers` 的 ZIP/TAR/TAR.GZ 前置元数据门禁、全量检查与 dirfd 流式提取。三轮审计发现的无界元数据、原地改写、symlink/竞态、伪造 EOCD count、ZIP64、central-to-EOCD gap 与 central/local header 不一致均已增加前置门禁和回归测试。仓库全套 49 项开发测试与完整 staged 复审已通过；真实数据获取尚未完成，因此不产生 `VERIFIED` 实验证据。

archive validator 已在智能体 2独立重放篡改反例后通过最终安全审计，并以 commit `c57a133cf7c05f049ca16f8e43d29302480ec411` 推送。该证据仅验证数据获取前置组件，不是论文实验运行；真实数据下载仍需单独资源与路径审批。

GSM8K 首次实际获取预审为 `BLOCKED`，未创建 raw 目录。阻塞项涉及传输硬上限、curl 局部配置隔离、archive 别名完整性、completion 崩溃一致性和 JSONL 内存上限；修复规格已冻结到 D-004-A，在代码与执行复审前仍不获取数据。

acquisition helper 的首次实施预审同样为 `BLOCKED`：完成语义还必须抵抗路径替换、未知 hardlink、hash 期间变更和掉电后数据未持久化，并在 helper 内重复实施全部字节、成员、路径与清单上限。扩展规格已追加到 D-004-A，未下载、未产生数据统计。

扩展 D-004-A 后，acquisition helper 的修订实施计划获得代码实施批准。固定布局的离线 stage/finalize/verify 模块和 33 项针对 HTTP schema、TOCTOU、hardlink/symlink、预算、清单篡改与 completion 发布的测试已实现；仓库全套 82 项测试通过。当前仍待 staged 安全复审，未下载且无 `VERIFIED` 论文数值。

首次 staged 安全复审结论为 `BLOCKED`：82 项测试未覆盖 revision 路径重解析、同内容 inode 替换、大规模空目录检查和 completion 已发布后的 fsync/snapshot 失败。该 helper 当前不可提交、不可用于获取或论文证据。

扩展修复已将 archive inspect/extract 改为 held-fd API，绑定 formal archive 重开前后 inode，线性化空目录检查，并以 fsync 后 formal-tree fingerprint 和永久 guard/final pair 表示完成。包含 44 项 acquisition 测试的仓库全套 97/97 通过；完整 staged 复审仍待进行，未下载且无 `VERIFIED` 论文数值。

第二次 staged 复审仍为 `BLOCKED`：97 项测试未阻止 completion pair 在读取后被整体替换、整条 revision parent chain 移位、formal root 的协议外文件，并且 guard 名称/发布顺序与冻结协议不一致。该 helper 仍不可提交或用于论文证据。

第二轮修复已长持并重绑 completion pair，从 absolute project root 重建整条 revision chain，限制 formal root 为三项固定集合，并以 guard-only 先 fsync、guard 再 link final 的顺序发布。新增六项回归后仓库全套 103/103 通过；第三次 staged 复审仍待进行，未下载且无 `VERIFIED` 论文数值。

第三次 staged 复审结论仍为 `BLOCKED`：内层验证结束到最外层返回之间仍可替换 completion pair 或新增 root entry，pair fd 关闭故障也可泄漏另一 fd/掩盖原异常。该 helper 仍不可提交或用于论文证据。

第三次审计修复已将 held completion pair 生命周期扩展到末次树扫描、canonical pair 重绑、完整 root/parent/revision fingerprint 校验和返回线性化点，并实现不掩盖活动异常的双 fd best-effort close。新增晚期 pair/路径/普通文件/目录攻击与 close-failure 回归后，57 项 acquisition 测试及仓库全套 110/110 开发测试通过。这仍只是待第四次 staged 安全审计的开发证据；未下载数据，不产生 `VERIFIED` 论文数值。

第四次 staged 审计仍为 `BLOCKED`：held pair 修复正确，但 canonical guard/final 每次重开的临时 fd 在 close 故障时仍可泄漏另一 fd，并以 cleanup 错误覆盖既有 validation/open 异常。因此 helper 尚不可提交、不可用于数据获取或论文证据。

canonical 临时 fd 已改用与 held pair 一致的固定快照 best-effort cleanup，并新增 final/guard/both close、active validation 和 partial-open 故障矩阵。62 项 acquisition 测试与仓库全套 115/115 通过；第五次 staged 审计前仍只是开发证据，未下载数据，不产生 `VERIFIED` 论文数值。

第五次完整 staged 审计独立重放上述故障矩阵和前四轮攻击路径后给出 `APPROVED TO COMMIT`。该批准仅证明获取 helper 快照可提交/普通推送，不是数据下载、论文实验或 `VERIFIED` 数值的批准。

## 5. 实验设计与超参数

冻结设计见 `docs/experiments/README.md`。任何偏离必须记录决定、时间和影响。

## 6. 数据构造统计与人工审计

待运行。至少报告 raw、filtered、event-success、reliable-relation、valid-counterfactual、retained，以及两人审计的有效率和 Cohen's kappa。

## 7. 已有实验复现结果

待运行。每行同时给出 `REPORTED`、重实现值、95% CI、差异、判定、run ID 和 commit。

## 8. 新增 Baseline 结果

待运行：Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph/Constraint-Rerank。

## 9. TORQUE 与 TimeQA-Hard 结果

待运行。两数据集仅用于冻结后的迁移评测。

## 10. 统计检验与实验结论

待三个 seed 和 paired bootstrap 完成后填写。负结果和无显著差异必须保留。

## 11. Interval/Graph 案例与失败分析

待填写成功案例与事件抽取、隐式关系、答案未更新、错误翻转、长上下文混淆等失败类型。

## 12. 审稿意见与新增证据映射

| Reviewer concern | Planned evidence | Status |
|---|---|---|
| 非标准 temporal 数据集 | TORQUE、TimeQA-Hard | PLANNED |
| Baseline 弱/监督不公平 | Same-data SFT、Pair-MLP、LLM-Graph、Rule-Graph | PLANNED |
| marker/template artifact | explicit/implicit、held-out、answer-unchanged | PLANNED |
| 数据构造不透明 | 构造漏斗、哈希、人工审计 | PLANNED |
| interval 可解释性不足 | interval/graph 可视化与消融 | PLANNED |

## 13. 论文修改建议

只有 `VERIFIED` 结果可以进入本节。实施阶段不自动修改 `main.tex`。

## 14. Run、Commit 与工件追踪

当前无 run。Bootstrap commit 为 `989634284e58b733e0bca2520fd0e7caad930e4c`；后续所有表格必须引用 registry 中的 run ID 和 SHA256。
