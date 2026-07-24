# Kairos A/B Reviewer Web

一个仅在浏览器本地运行的 Vue 3 + Element Plus 审核工作台。它包含两条严格分离的流程：

- 正式 Reviewer A/B 独立审核：不读取、不显示 AI 预审结果，输出严格的 `gsm8k-relation-human-review-v1` JSONL。
- AI 分歧核查：显示 AI-A 与 AI-B 的判断差异，只输出诊断文件，不能作为训练门禁输入。

源语句不会上传。应用通过 Vite 的静态目录直接读取
`review-data/audit-items.jsonl` 与对应审核模板，不需要在页面手动上传。
`review-data/` 已被 Git 忽略。

## 启动

```bash
cd src/ab-reviewer-web
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:4173/`。

## 固定文件

从冻结审核包复制所需文件：

```text
src/ab-reviewer-web/review-data/audit-items.jsonl
src/ab-reviewer-web/review-data/reviewer-a-template.jsonl
```

Reviewer B 另需 `reviewer-b-template.jsonl`；AI 分歧核查另需
`reviewer-ai-a.jsonl` 与 `reviewer-ai-b.jsonl`。应用读取后仍会校验冻结
schema、顺序、条目数与 SHA256，错误文件不会进入审核界面。

## 正式审核

1. 选择“正式独立 A/B 审核”，填写昵称和槽位。
2. 点击“读取固定文件并开始”。Reviewer A 会直接读取
   `audit-items.jsonl` 与 `reviewer-a-template.jsonl`。
3. 对每条语句完成事件跨度、原关系、反事实关系、语法和非目标内容五项判断。
4. 全部完成后选择“锁定并导出”。
5. 在目录选择器中选择本项目的 `results` 文件夹。

应用会写入：

```text
results/<本地时间>_<昵称>_formal-A.jsonl
results/<本地时间>_<昵称>_formal-A.jsonl.sha256
```

不支持目录写入 API 的浏览器会下载这两个文件。请手动将其移动到 `results`。

正式 JSONL 不额外写昵称或时间字段，因为 D-035 对 schema 有严格要求。昵称和时间只存在于文件名中。`overall_valid` 由五项判断自动计算，不能手填。

## AI 分歧核查

将 `audit-items.jsonl`、`docs/ai-context/ai-reviews/reviewer-ai-a.jsonl`
和 `reviewer-ai-b.jsonl` 放入 `review-data/` 后直接读取。默认只列出至少有一项分歧的条目，可按事件跨度、关系或语法筛选。

该模式生成 `gsm8k-relation-ai-disagreement-human-check-v1` 诊断 JSONL。它不会生成正式 A/B 提交，也不能解除训练门禁。

## 校验

```bash
npm test
npm run build
```

`node_modules/`、`dist/`、`review-data/` 以及 `results` 中的审核输出均被 Git 忽略。
