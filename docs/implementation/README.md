# Implementation Specification

本项目根据论文公式进行独立重实现。所有论文未说明的选择必须先登记到 `../ai-context/decisions.md`。

## 数据记录

统一 JSONL 记录包含：来源 ID、dataset/split/revision/SHA256、context/question/answers/answer type、事件字符与 token span、关系两端/标签/marker/provenance、反事实 pair/template/前后关系与答案，以及 explicit/implicit、answer-changing/unchanged、长度和事件数。

关系集合固定为 `precedes`、`follows`、`overlaps`、`contains`、`during`、`unknown`。`unknown` 不进入 relation loss。方向、逆关系和对称性在编码前冻结并由测试覆盖。

## Kairos 流水线

1. 从输入中提取事件 mention，并对齐 tokenizer span。
2. 对 span hidden states 池化得到事件表示。
3. 投影 start 与 `softplus(duration)`，令 `end=start+duration`。
4. 从区间端点和差值构造 geometry features，预测 pairwise relation。
5. 对有效 pair 的关系分布做 masked graph pooling。
6. 编码共享候选池，通过 graph-aware scorer 选择答案。
7. 以 answer、relation、counterfactual relation 三种损失训练。

匹配 Baseline 必须复用相同数据、候选、解析器和指标，避免实现差异造成不公平比较。

## CLI 与 manifest

计划接口：`prepare-data`、`generate-candidates`、`train`、`evaluate`、`aggregate`、`build-author-report`。每个正式 run 必须写 manifest，包含 Git commit/dirty、配置哈希、数据与模型 revision、seed、资源、起止时间、输出路径和 SHA256。

正式实验只能从 clean commit 启动；dirty-tree smoke test 标为 `development-only`，不能进入论文结果。

## 首批测试

- schema 缺字段和非法 relation 拒绝。
- 稳定 ID、重复处理同哈希、source/CF pair 不跨 split。
- marker 方向、inverse、overlap/contain/during。
- 字符与 token span round trip。
- template 只改变目标关系并拒绝冲突。
- numeric、extractive、yes/no 和 answer-unchanged updater。
- duration 为正且 `end=start+duration`。
- geometry feature 顺序、shape 和符号。
- unknown/padding 不进入 relation loss/graph pool。
- 候选去重、解析、SC tie 和 eval 禁止 gold。
- LLM-Graph malformed JSON。
- checkpoint 保存恢复和逐样本指标重聚合一致。
