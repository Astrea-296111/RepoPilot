# 在 GitHub Actions 运行 RepoPilot

工作流：`.github/workflows/windows-eval.yml`。运行环境为 Windows、Python 3.12。不会把模型 Key 写入代码或提交。真实模型调用会产生阿里云费用。

## 两类 Job

### Tests and scripted benchmark

每次 push 到 `main` 都会运行：

1. `python -m pytest -q`
2. `python eval/run_benchmark.py --fake --runs 1 --require-all`
3. 上传 `benchmark-fake` artifact

脚本化 benchmark 使用已知 patch，只用于验证 evaluator 的复制仓库、基线失败、Agent 执行、protected tests、hidden tests、汇总统计等基础设施没有坏。

### Qwen3.8-Max five-task benchmark

只有两种情况会运行付费模型：

- 手动 **Run workflow** 并设置 `run_real_model=true`
- push 的 commit message 显式包含 `[qwen-eval]`

命令为：

```powershell
python eval/run_benchmark.py --runs $env:BENCH_RUNS --limit 5
```

手动运行时可以选择每题 1 次或 3 次。普通 push 不会调用 Qwen。

## Secret 设置

在 **Settings → Secrets and variables → Actions → New repository secret** 新建：

```text
DASHSCOPE_API_KEY
```

根据 Key 地域选择 Beijing 或 Singapore。不要把 Key 放进仓库、Issue、聊天记录或 artifact。

## Mini Benchmark v2 的判定

当前有 5 个任务：

- exception-handling
- boundary-condition
- configuration
- path-security
- state-management

每次运行都会：

1. 将对应故障仓库复制到系统临时目录；
2. 初始化独立 Git baseline；
3. 运行固定测试，要求 baseline 非 0；
4. 让 RepoPilot 在临时仓库中工作；
5. 检查 Agent 是否修改了受保护的 `tests/`；
6. Agent 结束后才注入 `eval/hidden_tests/` 对应的 regression test；
7. 再运行固定测试；
8. 保存 resolved、steps、tool calls、token usage、duration、changed files、failure category。

真实模型没有解出某个任务是正常 benchmark 数据，不会因此把 CI 基础设施标成失败。Runner 错误或 baseline 本来就通过会返回非零。FakeLLM sanity check 使用 `--require-all`，任何任务未通过都会让 CI 失败。

## 2026-09-29 已验证结果

GitHub Actions run `36546370324`：

- 项目测试：`21 passed, 1 warning`
- Scripted 5-task benchmark：5/5
- Qwen3.8-Max real benchmark：5/5 first-run resolved
- median steps：3
- median tool calls：4
- median total tokens：3554
- median duration：27.205 s
- failure categories：无

单任务差异明显：path-security 使用 11103 tokens、约 150.986 s；说明后续不能只看平均成功数，还要分析不同任务类型的成本与轨迹。

这只是 **5 个小型 Python 任务 × 每题 1 次**，不代表通用软件工程成功率，也不是 SWE-bench。

## 查看诊断

真实评测结束后下载 Artifact：

```text
benchmark-qwen
  benchmark-qwen.json
```

JSON 含 summary 和逐任务 records，可看到模型调用、计划、steps、token、duration、changed files、hidden test 输出和 failure category。当前 artifact 保留 14 天。

公开仓库的 Actions 日志和 artifact 也可能公开，因此不要将私人代码、凭据或敏感任务放入这个工作流。

## 下一阶段

把任务集扩到 20–30 个，每题 3 次；再加入相同 Qwen3.8-Max 的 one-shot baseline，比较 Agent Loop 相比一次性 patch 的收益，并对失败做分类。
