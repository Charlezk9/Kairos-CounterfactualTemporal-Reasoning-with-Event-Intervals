# Frozen Experiment Design

本文件在正式测试结果可见前冻结主要假设、数据划分和成功标准。变更必须追加到 decisions 和 Git history。

## 研究问题

- H1：Kairos 相对相同数据/参数适配的 Baseline 提高 relation update 与 counterfactual consistency。
- H2：收益不是仅来自显式 marker、额外监督或候选池中的 gold。
- H3：在 TORQUE 与 TimeQA-Hard 上仍能观察到外部时间推理泛化。
- H4：interval geometry 对关系和答案贡献可由消融、可视化和失败分析解释。

## 数据集与固定用途

| Dataset | Evaluation split | Primary metrics |
|---|---|---|
| GSM8K temporal | official test | standard/counterfactual accuracy |
| MuSiQue temporal | official validation | EM/F1 and CF accuracy |
| StrategyQA temporal | official validation | accuracy |
| 2Wiki temporal | official dev | EM/F1 |
| Counterfactual stress | source-aligned split | update, stability, consistency |
| TORQUE | public official dev | official F1, EM, cluster consistency |
| TimeQA-Hard | `human_test.hard` | normalized EM/accuracy, token F1 |

TORQUE 和 TimeQA 只作冻结后的迁移评测，不用于训练。训练数据按 source ID 稳定哈希划出 10% internal dev，同一原始样本和反事实版本不得跨 split。

### 已观察的迁移评测 source binding（非结果）

- TORQUE 固定 revision `ab27019cc6a317fde3c879900499f02acce8b16d` 的 public dev 为 145 passages/1,483 answer-bearing QA，dev SHA256 `7a8dd84c984f28a5284bdfda57b447218e1269cd2eaf05b5e173394fc1522434`。本地 test 没有 answer field，禁止用于评测。per-question 采用 NFC+casefold+whitespace collapse 后的 span-set EM/F1，保留 punctuation；323 题 gold 为空集。571 个 contrast group 以 `(passageID, cluster_id)` 唯一化。主 consistency 为组内每题 set EM=1 的 group 百分比；敏感性指标为组内每题 set F1>=0.8 的 group 百分比，两者必须同时报告。
- TimeQA 固定 revision `38b05989070c1168b2bef3d5a2656afeeba763dc` 的 `dataset/human_test.hard.json` 实为 989 条 LF-delimited JSON，exact keys 为 `context, idx, paragraphs, question, targets`，SHA256 `0318963bb2af931143be50ca24402d03c075c4b5a4898fda9bf4d5b2f0c6c188`。采用 fixed upstream normalizer（lowercase、删除 ASCII punctuation/English articles、whitespace collapse）、normalized EM 和 token F1，每题分别对多个 gold 取最大值；159 题的唯一 gold 为空字符串，必须保留。

这些是正式预测前的 source/schema 证据，不得解释为模型结果，也未改变冻结的评测 split。

## Baseline 分组

- Prompt-only：Direct、CoT、Self-Consistency、CoT+Verifier。
- Same-supervision：Same-data SFT、Pair-MLP。
- Structured temporal：LLM-Graph、Rule-Graph/Constraint-Rerank。

确定性方法使用 greedy；Self-Consistency 使用 8 个 CoT 样本、temperature 0.7、top-p 0.9。开放式候选池为 greedy Direct、greedy CoT 和 8 个采样 CoT 的去重并集。训练允许补 gold，评测禁止补 gold，并报告 candidate recall 与无 gold 注入敏感性结果。

## 训练与统计默认值

- seeds：13、42、2026。
- Qwen LoRA：rank 16、alpha 32、dropout 0.05。
- BF16、AdamW、LoRA LR `2e-5`、新头 LR `2e-4`、weight decay 0.01。
- effective batch 32、最多 3 epochs、5% warmup、gradient clip 1.0。
- `lambda_rel=lambda_cf=1`。

报告 mean/std、10,000 次 paired bootstrap 95% CI、Holm 校正和效应量。主要显著性比较为 Kairos 对最强 same-supervision Baseline；不把定义不同的指标混成一个总平均。

## 数据质量

反事实数据至少由两名人类对 200 条分层样本独立审核，检查事件、关系、语法、非目标内容和答案更新。目标为 Cohen's kappa >= 0.80、有效率 >= 95%；未达标则修正规则并用新样本复审。AI 判断不能替代该审计。

## 复现判定与 PDF 表映射

- 数值复现：原值落入 95% CI 或绝对差不超过 2 个百分点。
- 趋势复现：方法排序和消融方向一致。
- 未复现和 deferred 都必须报告，不能用测试集继续选配置。

依次复核 PDF 表 1（主结果）、2（构造统计）、3（update/stability）、4（模板泛化）、6（消融）、7（案例）、8（routing）。表 5 的 Llama 第二骨干需另行模型下载授权。
