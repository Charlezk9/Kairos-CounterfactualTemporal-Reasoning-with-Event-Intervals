# Operations, Environment, and Safety

## 允许范围

只允许在 `/home/yangbin/zx-tmp` 和 `/data0/hk_data/kairos-zx` 内创建或修改文件。不得使用 `sudo`、修改系统级配置、其他用户目录、公共 CUDA/Python/Conda/Node、默认 shell 配置或来源不明的进程。

## 固定局部工具链

- Miniforge：`/data0/hk_data/kairos-zx/.conda/miniforge`
- 环境：`/data0/hk_data/kairos-zx/.conda/envs/kairos`
- Python：3.10.20
- PyTorch：2.5.1 + CUDA 12.1
- Transformers：4.48.3
- PEFT：0.14.0（仅安装于上述项目环境）
- 模型：`/data0/hk_data/kairos-zx/models/Qwen2.5-7B-Instruct/a09a35458c702b33eeacc393d103063234e8bc28`

禁止 `conda init`、`pip install --user` 和全局包修改。新增依赖只能进入该环境，版本和理由必须登记。Conda、pip、HF、Torch、Triton、XDG 和临时缓存必须指向 `/data0/hk_data/kairos-zx`。

## 数据与工件

- raw：`/data0/hk_data/kairos-zx/data/raw/<dataset>/<revision>`
- processed：`/data0/hk_data/kairos-zx/data/processed/<schema-version>`
- artifacts：`/data0/hk_data/kairos-zx/artifacts/<run-id>`
- caches/temp：`/data0/hk_data/kairos-zx/.cache`、`.tmp`

## 资源门禁

下载、训练和批量推理前必须执行：

```bash
nvidia-smi
free -h
df -h
```

- 最多 4 张 GPU，使用前显式设置 `CUDA_VISIBLE_DEVICES`。
- CPU 线程最多 16，DataLoader worker 最多 8。
- 单任务内存预算 64 GiB。
- 本项目新增磁盘预算 80 GiB。
- `/data0` 可用空间低于 120 GiB 时停止新增下载/checkpoint并请求指示。
- 不启动未经授权的后台长期任务，不结束其他进程，不擅自删除历史工件。

## 单人实现门禁

每阶段直接由单一智能体规划并执行。执行前确认路径位于授权根目录内、资源在预算范围内，执行后检查无残留进程。提交前 `.githooks/pre-commit` 自动拦截密钥、token 和超过 10 MiB 的文件。

OOM、磁盘不足、依赖冲突或异常进程发生时，保留日志并停止扩大资源。不得通过杀死未知进程、清理不明文件或修改公共环境解决。
