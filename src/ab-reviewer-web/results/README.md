# Review Results

浏览器审核结果保存到此目录。文件名固定包含本地时间、审核者昵称和用途，例如：

```text
20260724-190809-012_charles_formal-A.jsonl
20260724-190809-012_charles_formal-A.jsonl.sha256
```

正式 A/B 文件在双方各自锁定 SHA256 之前不得互相查看。实际 JSONL 与 `.sha256` 文件不进入 Git。
