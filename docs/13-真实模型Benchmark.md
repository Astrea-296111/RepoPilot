# 13｜真实模型 Benchmark：方法、校准与当前结果

## 目标

RepoPilot 的早期 `examples/demo_repo` + FakeLLM 只能证明 Agent Harness 能走完整流程，不能说明真实模型在未知任务上的修复能力。本文先保留早期 5 任务的校准记录，再记录 25 任务对照与定向复测；这些都是自建小型 Python 任务，并非外部通用修复基准。

## 任务结构

当前任务定义在 `eval/benchmark_tasks.json`，故障仓库位于 `benchmarks/repos/`，共 25 题。下表是首批 5 题，后续增加了跨模块与共享 helper 任务：

| Task | Category | Difficulty |
| --- | --- | --- |
| duplicate_email | exception-handling | easy |
| pagination_off_by_one | boundary-condition | easy |
| config_precedence | configuration | easy |
| safe_path_traversal | path-security | medium |
| inventory_atomic_reserve | state-management | medium |

Agent 每次只在某一个临时仓库副本中运行，输入是该仓库和任务描述。

## 为什么需要 hidden tests

只运行公开测试容易让 Agent 过拟合单个断言，甚至可能通过修改测试“修复”任务。因此 V2 做两层约束：

1. `protected_paths=["tests"]`：记录 Agent 是否修改公开测试，并在最终评分前恢复这些路径。当前实现**不会仅因修改过测试就判未通过**；最终评分使用原测试与隐藏测试。报告应单独披露修改测试的记录。
2. hidden regression tests：位于主项目的 `eval/hidden_tests/`，不会复制进 Agent 的任务工作区；Agent 完成后 evaluator 才把对应 hidden test 注入临时仓库并复测。

注意：当前真实 benchmark 使用 GitHub Actions 的 LocalExecutor，因此这不是强隔离；模型理论上若主动逃逸工作目录并扫描 runner 文件系统，仍可能接触主项目文件。当前设计只避免正常 Agent 上下文直接泄露 hidden tests。更严格版本应在独立容器中运行 Agent 工具环境，并在容器退出后由宿主注入 hidden tests。

## resolved 判定

一个任务 resolved 需要同时满足：

- baseline test 修复前确实失败；
- Agent 状态为 `completed`；
- 最终评分前恢复 protected tests；
- Agent 结束后注入 hidden tests；
- 固定 `test_command` 最终退出码为 0。

成功判定不再要求“必须修改预期文件”，因为不同但正确的 patch 可能改动不同文件。

## 记录指标

逐任务记录：

- resolved
- category / difficulty
- Agent steps
- tool calls
- prompt/completion/total tokens
- duration
- changed files
- diff added/deleted lines
- protected test modifications
- model calls
- baseline / hidden test output
- failure category

汇总记录：

- first-run resolved
- run-level resolved
- median steps
- median tool calls
- median tokens
- median duration
- category breakdown
- failure category breakdown

## 第一次 5 任务运行：4/5，以及为什么不能直接相信 evaluator

第一次真实 Qwen3.8-Max 运行得到 4/5。唯一失败是 `duplicate_email`。

模型将：

```python
raise ValueError('UNIQUE constraint failed: users.email')
```

改成：

```python
raise DuplicateEmailError('UNIQUE constraint failed: users.email')
```

公开测试通过，任务描述要求的「重复注册抛出 DuplicateEmailError、正常注册行为不变」也满足。但 hidden test 额外断言异常消息必须包含实际 email 字符串；这个要求没有出现在任务描述中，因此 evaluator 偷加了规格。

处理方式不是“为了让模型通过而放宽所有测试”，而是让 hidden test 回到公开任务语义：继续验证 DuplicateEmailError 和正常注册路径，不再要求未声明的错误消息格式。

同时修正 CI 语义：

- 模型 miss：记录 benchmark 结果，真实 benchmark job 可以成功完成；
- runner error / invalid baseline：判为基础设施错误，返回非零；
- FakeLLM sanity test：使用 `--require-all`，确保 evaluator 本身的已知正确修复全部通过。

## 校准后的真实结果

GitHub Actions run：`36546370324`  
模型：`qwen3.8-max`  
设置：5 tasks × 1 run/task

结果：

| Metric | Value |
| --- | ---: |
| First-run resolved | 5 / 5 |
| Run resolved | 5 / 5 |
| Median steps | 3 |
| Median tool calls | 4 |
| Median total tokens | 3554 |
| Median duration | 27.205 s |
| Failure categories | none |

逐任务：

| Task | Resolved | Steps | Tool calls | Tokens | Duration |
| --- | --- | ---: | ---: | ---: | ---: |
| duplicate_email | yes | 3 | 4 | 3423 | 26.511 s |
| pagination_off_by_one | yes | 3 | 4 | 3554 | 27.065 s |
| config_precedence | yes | 3 | 4 | 3534 | 27.205 s |
| safe_path_traversal | yes | 4 | 5 | 11103 | 150.986 s |
| inventory_atomic_reserve | yes | 5 | 6 | 6896 | 45.650 s |

## 这些数据能说明什么

可以说明：

- RepoPilot 已经在真实 Qwen 模型上完成跨多个任务的端到端闭环；
- evaluator 能验证 baseline failure、受保护测试和 hidden regression tests；
- 不同任务的 token / duration 差异明显，具备后续成本和失败分析基础。

不能说明：

- RepoPilot 的通用修复成功率是 100%；
- 对大型真实仓库同样有 100%；
- 比 one-shot 更好；
- 达到任何 SWE-bench 成绩。

上面仅为早期 5 题的一轮校准记录；后续新增任务与 one-shot 对照的数据见下节。

## 25 任务与四题定向复测

2026-09-29 的完整 25 任务运行 [#18](https://github.com/Astrea-296111/RepoPilot/actions/runs/36562112955) 与 [#19](https://github.com/Astrea-296111/RepoPilot/actions/runs/36562212124)：Agent 分别 24/25、25/25；one-shot 两次均 21/25。两次 one-shot 的相同 4 题都因模型请求到 180 秒未返回而记为 `model_timeout`，不能将这个差值解释成修复能力差异。Agent 其中一次在 `shared_rounding_policy` 达到最大步数。

为了区分模型请求超时与实际补丁问题，[#21 定向复测](https://github.com/Astrea-296111/RepoPilot/actions/runs/36568828589) 给 Agent 与 one-shot 同时设置 Qwen3.8-Max 的 `reasoning_effort=medium`、流式响应及相同的 180 秒网络读取超时，并只运行此前超时的 4 题，每题一次。

| 任务 | Agent | One-shot |
| --- | --- | --- |
| `shared_rounding_policy` | 达到 15 步，未解出 | `old_text` 与原文件不匹配 |
| `shared_identifier_normalization` | 解出 | `old_text` 与原文件不匹配 |
| `relative_config_paths` | 解出 | `old_text` 与原文件不匹配 |
| `shared_feature_flag_precedence` | 解出 | `old_text` 与原文件不匹配 |

这轮配对结果为 Agent **3/4**、Top-K one-shot **0/4**；没有 `model_timeout`。Agent 中位用量 **16048.5 tokens**、耗时 **115.523 秒**；one-shot 分别为 **2112.5 tokens**、**26.57 秒**。one-shot 一次生成补丁，依赖仓库地图和 Top-K 文件；在这几题里它给出的精确 `old_text` 没有出现在对应目标文件中。Agent 能继续读文件并尝试修改，但因此成本更高。这个对照同时包含**可用上下文和交互次数差异**。

本轮只复测 4 个挑选出的难题，而且每题仅一次；改变推理力度后，不能把它与 #18/#19 合并成同条件的 25 题成功率。`resolved` 也仅表示通过项目自建的固定测试与隐藏测试。

## 上下文消融：完整源码与导入图

[Actions #24](https://github.com/Astrea-296111/RepoPilot/actions/runs/36572978243) 仍使用同一 Qwen3.8-Max 参数和四道定向任务，给单次调用提供任务副本中的全部公开 Python 文件原文（包括公开测试，隐藏测试直到评分时才注入），结果 **4/4 resolved**，中位 **1372.5 tokens**、**9.672 秒**、**1 个补丁**。这与 #21 的 Agent 3/4、Top-K one-shot 0/4 各为一次采样，不能做显著性或因果推断，但足以说明原四题不支持“Agent Loop 优于 one-shot”的技术亮点表述；在这些小仓库里，扩大可用上下文后单次调用表现更好。

进一步检查发现，Top-K 在这四题均未选中已知修复所在的共享 helper。新增 `eval/measure_retrieval.py`，以 `scripted_fixes.json` 的已知补丁路径为**离线参照**，统计固定 `top_k=4` 的文件召回；它不把修复路径提供给模型，也不把该指标当成真实修复率。

| 文件检索 | 参考修复路径全部命中 | 平均原文字符数 | 平均选中文件数 |
| --- | ---: | ---: | ---: |
| 词法 Top-K | 20/25 | 409.7 | 2.16 |
| 导入关系补全 | 25/25 | 440.2 | 2.36 |

导入关系补全从强词法匹配开始，为其直接依赖预留名额；若完全没有词法匹配，再按仓库内 Python 导入次数选择共享文件。这是针对自建任务集开发的设计内诊断；`scripted_fixes.json` 只代表一种正确修法，也不能外推 25/25 到其他仓库。真实模型对 graph 模式的修复结果要以单独 Actions 运行报告为准。

[Actions #26](https://github.com/Astrea-296111/RepoPilot/actions/runs/36574356369) 对原本漏检参考修复文件的五道共享实现题，以 graph 模式运行真实 Qwen3.8-Max one-shot：**5/5 resolved**，中位 **1096 tokens**、**8.641 秒**、**1 个补丁**；逐题报告的 `context.source_paths` 均包含该题的参考 helper。每题仍只有一次，五题也是定位问题后选择的开发集，不能把这个数字外推为泛化成功率。新版本 Agent 已使用导入图上下文，需另行复测多步轨迹。

## 下一步实验设计

1. 固定本轮模型参数，完整运行 25 题并按题重复至少 3 次，合并 shard 后报告配对结果、超时和成本；此项会产生付费模型用量。
2. 对完整源码与导入图 one-shot 分别做重复运行，区分上下文不足与不能多轮探索。
3. 加入少量未用于开发的外部仓库任务，并保持任务描述与隐藏断言一致。
4. 将 Agent 工具执行与 evaluator 分离，防止工具直接访问隐藏测试。
5. 在面试或简历中注明任务集自建、样本量和配置；不写成 SWE-bench 成绩或通用修复成功率。
