# Git and Project-specific SSH

## Repository

- remote：`git@github.com:Charlezk9/Kairos-CounterfactualTemporal-Reasoning-with-Event-Intervals.git`
- local identity：`Charlezk9 <Charlezk9@users.noreply.github.com>`
- protected history：`main`
- work branch：`experiment/reproduction-additional-evaluation`

只设置 repository-local Git 配置，禁止修改 global 配置。

## Dedicated SSH

- private key：`/home/yangbin/zx-tmp/.ssh/id_ed25519_git`（600）
- public key：`/home/yangbin/zx-tmp/.ssh/id_ed25519_git.pub`（644）
- known hosts：`/home/yangbin/zx-tmp/.ssh/known_hosts_github`（644）
- project public-key fingerprint：`SHA256:Q0nlVwfr9J9ObayiiiKS/Dd19GCZOzJSVbk5M0f2lp8`
- expected GitHub identity：`Charlezk9`
- GitHub Ed25519 host fingerprint：`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`

仓库局部 `core.sshCommand` 必须使用 `-F /dev/null`、专用 key、`IdentitiesOnly=yes`、`BatchMode=yes`、`HostKeyAlgorithms=ssh-ed25519`、`CheckHostIP=no`、`UpdateHostKeys=no`、严格 host 校验、专用 known_hosts 和 `GlobalKnownHostsFile=/dev/null`。`CheckHostIP=no` 防止 SSH 把动态解析出的 GitHub IP 追加到专用文件；`UpdateHostKeys=no` 禁止服务器自动扩充专用文件；主机名本身仍严格匹配官方 key。不得读取/修改默认 `~/.ssh` 或依赖 ssh-agent。

`ssh -T` 只有明确返回 `Hi Charlezk9!` 且退出码为 1才算成功。host key 不匹配、身份不同或认证失败时停止，不降级到 `StrictHostKeyChecking=no`。

## Commit and push policy

明确路径 staged，禁止 `git add -A`。提交前必须通过相关测试、`git diff --cached --check`、大文件/敏感信息 hook 和智能体 2 staged-diff 审核。阶段完成后推送一次工作分支；未验证中间提交只留本地。

固定关键提交：bootstrap、data、prompt baselines、model、end-to-end tests、original reproduction、TORQUE/TimeQA、author report。即使大型工件只在 `/data0`，也要提交 registry、哈希和结果摘要。

禁止 force push、`reset --hard`、重写已推送历史、提交密钥/数据/模型/checkpoint/大型预测。远端历史意外出现变化时先 fetch/比较并停止自动 push，不覆盖他人工作。
