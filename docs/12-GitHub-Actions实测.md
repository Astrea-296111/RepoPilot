# 在 GitHub Actions 运行 RepoPilot

工作流：`.github/workflows/windows-eval.yml`。运行环境为 Windows、Python 3.12。不会把模型 Key 写入代码或提交。真实模型调用会产生阿里云费用。

## 当前 CI 结构

### Tests and scripted benchmark

每次 push 到 `main` 都会运行项目测试，以及不调用真实模型的 scripted Agent / one-shot benchmark。它验证 evaluator 的仓库复制、基线失败、patch、protected tests、hidden tests 和结果汇总本身没有坏。

### 真实 Qwen benchmark

只有两种情况会运行付费模型：

- 手动 **Run workflow** 并设置 `run_real_model=true`
- push 的 commit message 显式包含 `[qwen-eval]`

当前 25 个任务会分成 **5 个 shard**。Agent 和 one-shot 各自使用 matrix，每个 shard 只处理 5 个任务；每类 matrix 最多并行 2 个 shard。这样即使以后选择每题 3 次，也不会让全部任务堆在一个长达数十分钟的单 job 里。

手动运行时可在 `task_ids` 填写英文逗号分隔的 ID，例如 `relative_config_paths,shared_feature_flag_precedence,shared_identifier_normalization,shared_rounding_policy`。有筛选条件时，两组各用一个 job 运行同样的题目，Artifact 仍分别名为 `agent-qwen-shard-0` 和 `oneshot-qwen-shard-0`；留空则各分成 5 个 shard。未知 ID 会直接报错，避免误以为已评测该任务。完整运行与定向运行使用同一套模型参数。

同一个仓库的 Windows evaluation 工作流按顺序排队，避免两个付费评测重叠。当前真实 Qwen 评测为 Agent 和 one-shot 同时设置 `reasoning_effort=medium`、流式响应及 180 秒的网络读取超时；请求耗时和超时类型保存在诊断 JSON 中。流式响应有利于保持长回答连接，但不能保证不超时。此配置与早期默认模型参数的结果不可直接作为同条件重复实验。

示例命令：

```powershell
python eval/run_benchmark.py --runs $env:BENCH_RUNS --shard-index $env:BENCH_SHARD --shard-count 5
python eval/run_one_shot.py --runs $env:BENCH_RUNS --shard-index $env:BENCH_SHARD --shard-count 5
```

## Secret 设置

在 **Settings → Secrets and variables → Actions → New repository secret** 新建：

```text
DASHSCOPE_API_KEY
```

根据 Key 地域选择 Beijing 或 Singapore。不要把 Key 放进仓库、Issue、聊天记录或 artifact。

## 模型 timeout 的处理

2026-09-29 的 25 任务 one-shot 运行中，`relative_config_paths` 的模型请求没有在配置时间内返回。旧版 Harness 把它记录成 `environment_failure`，又把所有 environment failure 当作 CI 基础设施错误，所以虽然其余 24/25 已完成，整个 one-shot job 仍返回非零。

当前版本做了三处修正：

1. `OpenAICompatibleLLM` 将 HTTP 请求超时明确报为 `模型服务请求超时`；
2. benchmark 将它分类为 `model_timeout`，与 runner / baseline / evaluator 故障区分；
3. evaluation-only retry 从最多 3 次改为最多 2 次，避免单个请求连续占用过长时间。

模型超时仍会计为该次模型 run 未 resolved，但**不会再被误判为 evaluator 崩溃**。真正的 runner error、invalid baseline 等基础设施错误仍会让 CI 返回非零。

## Mini Benchmark 的判定

每次任务运行都会：

1. 复制对应故障仓库到临时目录；
2. 初始化独立 Git baseline；
3. 运行固定测试并要求 baseline 非 0；
4. 运行 RepoPilot Agent 或同模型 one-shot baseline；
5. 检查并恢复 grader-owned protected tests；
6. Agent/one-shot 完成后才注入 hidden regression tests；
7. 再运行固定测试；
8. 保存 resolved、steps/tool calls、token usage、duration、changed files 和 failure category。

真实模型没有解出某个任务属于 benchmark 数据，不等于 CI 基础设施失败。

## 已验证结果

早期 5 任务运行：

- Qwen3.8-Max Agent：5/5 first-run resolved
- median steps：3
- median tool calls：4
- median total tokens：3554
- median duration：27.205 s

20 任务 Agent vs one-shot 第一轮中，两者都达到 20/20；one-shot 的中位 token / duration 更低，说明这批简单任务不足以证明 Agent Loop 有收益。因此后续又加入 5 个 shared-helper / cross-module challenge tasks，专门测试 Agent 是否能通过工具继续定位共享实现。

25 任务第一次运行里，Agent job 完成；one-shot 得到 24/25，其中唯一未完成的是模型服务请求超时，而不是行为修复错误。该结果不应解读为 Agent 已在行为能力上胜过 one-shot，需在 timeout 修复后的分片版本中重新对比。

## 查看诊断

真实评测会为每个 shard 上传独立 artifact，例如：

```text
agent-qwen-shard-0
oneshot-qwen-shard-0
...
agent-qwen-shard-4
oneshot-qwen-shard-4
```

每个 JSON 都包含逐任务模型调用、计划/patch、token、duration、hidden test 输出和 failure category。公开仓库的 Actions 日志和 artifact 也可能公开，因此不要放入私人代码、凭据或敏感任务。

## 下一阶段

四题定向复测已在 [Actions #21](https://github.com/Astrea-296111/RepoPilot/actions/runs/36568828589) 完成：Agent 3/4、one-shot 0/4，均没有模型超时。one-shot 的失败均为精确补丁原文不匹配；Agent 未解出的任务达到步骤上限。详细限制见 [`docs/13-真实模型Benchmark.md`](13-真实模型Benchmark.md)。

下一步用相同配置对完整 25 任务运行，并视费用与稳定性决定是否使用 `runs=3`。各 shard 的 JSON 需合并并重新计算汇总，之后再用 `eval/compare_results.py` 生成 Agent vs one-shot 的 paired comparison。比较时单独列出 `model_timeout` 和 `patch_failure`，并增加更强 one-shot 上下文对照。
