# Source Discrepancies

## Manuscript result mismatch

| Item | `kairos.pdf` | `main.tex` | Handling |
|---|---:|---:|---|
| Overall Standard, Kairos | 0.610 | 0.272 | PDF 为 `REPORTED` 目标；TeX 记为旧版本 |
| Overall Counterfactual, Kairos | 0.604 | 0.251 | 同上 |
| Overall Average, Kairos | 0.607 | 0.262 | 同上 |

PDF 还包含 TeX 未包含的 per-benchmark 表、CoT+Verifier、relation update/stability、held-out templates、Llama-3.1-8B、扩展消融、routing cost 和反事实附录。这些项目只有在存在可追溯运行后才可进入 `VERIFIED` 状态。

## Missing author artifacts

- 源码和配置：缺失
- 四个 temporal subset 的样本 ID：缺失
- 完整 prompt 和候选池：缺失
- backbone 更新策略和训练超参：不明确
- 18 个 train 与 16 个 held-out template 的完整逐字清单：缺失

以上缺失项必须通过 `decisions.md` 预先登记，不能从最终结果反推选择。
