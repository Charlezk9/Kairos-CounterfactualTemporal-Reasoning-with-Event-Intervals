# Kairos 补充实验技术与结果报告

> 状态：PLANNED
> 本文件是同伴作者引用补充实验的唯一汇总来源。当前所有论文数字均为 `REPORTED`，尚无本项目 `VERIFIED` 实验结果。

## 1. 文档状态与执行摘要

- 当前阶段：Phase 00，restart-safe bootstrap
- 复现性质：independent reimplementation
- 已完成实验：无
- 当前结论：尚不能验证论文数值或新增 claim

## 2. 复现范围、版本与 Git commit

待首次 Git 提交后补充 commit。以 `kairos.pdf` 为主要待验证规格，`main.tex` 为较早且数值冲突的版本。

## 3. PDF、TeX 与重实现差异

详细差异见 `docs/ai-context/discrepancies.md`。PDF 的 Overall Kairos Standard/CF/Average 为 0.610/0.604/0.607；TeX 为 0.272/0.251/0.262。两组数值当前均未由代码和数据支持。

## 4. 技术实现路径

待阶段 1–3完成后，根据 `docs/implementation/README.md` 和实际 commit 填写。

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

当前无 run。首次提交后记录 bootstrap commit；后续所有表格必须引用 registry 中的 run ID 和 SHA256。
