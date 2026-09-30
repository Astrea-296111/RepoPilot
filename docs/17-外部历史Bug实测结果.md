# RepoPilot 外部历史 Bug 实测结果（2026-09-30）

## 结论与可核查运行

本轮完成 **10 个独立历史 Bug ×3 次重复 ×2 种方法 =60 次 Qwen3.8-Max 真实试验**。Agent 补丁评分通过 25/30，正常结束并通过 23/30；单次补丁基线通过 28/30。**本轮没有证明多轮 Agent 优于单次调用。** 主要工程发现是：重复读文件导致无修改退出、修复成功后重复测试导致异常结束，以及公开复现通过仍可能遗漏旧行为兼容性。

- [正式 Actions 运行](https://github.com/Astrea-296111/RepoPilot/actions/runs/36677551664)：全部任务和比较作业完成，状态 success。
- 被测试提交：`ff9d52b6164b58c17d33a8dd3a17802765487965`。
- [协议](15-外部历史Bug评测协议.md)、[上游提交与许可证](../eval/external/provenance.json)、[证据清单及 SHA-256](../eval/evidence/2026-09-30/manifest.json)。
- [10 个原始模型分片与参考评分](../eval/evidence/2026-09-30/shards)、[原始比较](../eval/evidence/2026-09-30/original-external-comparison.json)、[追加终态审计](../eval/evidence/2026-09-30/external-analysis.json)。Actions artifact 有保留期限，以上文件已保存进版本库。

Actions success 表示评测流程完整运行，不表示所有模型修复都成功。模型失败保留在逐题记录里，没有删掉失败任务或只挑最好的一次。

## 范围与实验配置

任务来自 boltons、more-itertools、python-slugify 三个独立开源项目，覆盖范围/切片、组合/排列参数、树遍历共享对象、谓词窗口填充、字符解码与分隔符截断。固定每个修复提交的父版本，保留完整目标模块及必要包内导入和原始许可证；不包含完整上游仓库，也没有运行上游全部测试。

评分合计 **129 个 pytest 用例：10 个公开复现用例、119 个隐藏参数化回归用例**。这不是 129 个独立 Bug。模型运行前，Docker 参考验证确认每个旧版本的公开复现失败、上游修复通过相应公开与隐藏测试。项目自身测试为 **33 passed**。

| 项目 | 固定配置 |
|---|---|
| 模型 API 请求名称 | `qwen3.8-max`（服务端别名，不是不可变权重版本） |
| 服务地域 | DashScope 北京，OpenAI-compatible API |
| 模型参数 | temperature 0、reasoning medium、流式响应 |
| 次数 | 每个任务每种方法 3 次；Agent / one-shot 各 30 次 |
| Agent 预算 | 最多 15 步；上下文字符预算 30000 |
| 初始检索 | AST repo map + 词法/导入图；公开任务符号实现片段每文件上限 6000 字符，初始 3 文件 |
| 传输 | 读取超时 180 秒；传输/429/5xx 最多一次重试，模型行为失败不重跑挑结果 |
| 端到端耗时口径 | 任务准备 + baseline Docker 测试 + 模型/修复 + 干净 Docker 评分 |

两种方法共享任务、公开测试输出和检索/片段策略。Agent 另有规划调用、动态读文件和观察；one-shot 使用一次模型调用生成精确补丁，没有工具/修复循环。提示词形状与小文件内容的截断规则不同，不能称完全相同 prompt 或严格等量输入。因此比较的是两套完整配置；不能把差异全部归因于循环本身。分片并行与服务负载也使耗时只能作为当前运行描述。

## 总体结果

| 指标 | Agent | 单次补丁基线 |
|---|---:|---:|
| 真实试验次数 | 30 | 30 |
| 补丁评分通过（预先约定的 resolved） | 25/30（83.3%） | 28/30（93.3%） |
| 正常结束且评分通过（追加终态审计） | 23/30（76.7%） | 28/30（93.3%） |
| 每次 total tokens 中位数 | 34337.5 | 5003 |
| total tokens 合计 | 1296515 | 164566 |
| 端到端耗时中位数 | 123.904 秒 | 36.492 秒 |
| 端到端耗时最大值 | 952.422 秒 | 171.681 秒 |

`resolved` 要求：只修改允许的包内源码，固定公开与隐藏测试退出码为 0，并实际报告通过用例。它评分最后留下的补丁，不要求 Agent 会话状态为 completed。运行后读取保存的终态增加第二列口径；原始评分与分母保留不变。两个 Agent 试验补丁正确，但重复测试触发 loop_detection，所以从 25 降到 23；这是系统正常完成与代码正确性的区别。

正式运行累计记录 **1461081 total tokens**，不含此前被取消的运行，也不是费用金额。只有 10 个独立任务，三个重复相关；不能当成 30 个独立 Bug。配对结果为两者均通过 24 次、仅 Agent 通过 1 次、仅单次通过 4 次、两者均失败 1 次。Agent 补丁通过率比单次低 10 个百分点；按任务整组重采样的 95% bootstrap 差值区间约 **[-33.3, +6.7] 个百分点**。仅 10 个任务簇，区间用于提示不确定性，不能得出稳定优劣结论。

## 逐题结果

| 任务 | Agent 补丁通过 | Agent 正常结束并通过 | 单次通过 |
|---|---:|---:|---:|
| boltons_backoff | 3/3 | 3/3 | 3/3 |
| boltons_research | 0/3 | 0/3 | 3/3 |
| boltons_split | 3/3 | 3/3 | 3/3 |
| boltons_xfrange | 3/3 | 3/3 | 3/3 |
| more_nth_combination | 3/3 | 3/3 | 3/3 |
| more_nth_permutation | 3/3 | 3/3 | 3/3 |
| more_numeric_slice | 3/3 | 3/3 | 3/3 |
| more_predicate_sentinel | 3/3 | 1/3 | 3/3 |
| slugify_hex | 2/3 | 2/3 | 3/3 |
| slugify_truncation | 2/3 | 2/3 | 1/3 |

## 失败轨迹与工程含义

| 可复查记录 | 观测事实 | 含义与待验证改进 |
|---|---|---|
| `external-agent-3.json`，boltons_research，3 次 | 反复读取 research 的邻近行区间，没有修改，最终 loop_detection；单次 3 次通过 | 现有重复保护阻止了失控，但没帮助转向新的证据或动作。原始工具输出含 `remap(root, enter=_enter)`；不能断言实现完全没给模型。应对照观察压缩/函数依赖补充与重复动作后的转向策略 |
| `external-agent-0.json`，more_predicate_sentinel，重复 1、2 | 补丁公开/隐藏测试通过；继续重复执行测试，最终 loop_detection | 需要明确成功后的结束策略。追加终态指标防止把正确补丁等同于完整任务成功 |
| `external-agent-3.json`，slugify_hex，重复 1 | 直接把共享 HEX_PATTERN 的 x 改成 xX；公开新行为通过，旧解码模式隐藏用例失败 | 修复应限定 modern 分支，先识别共享常量的调用范围，兼容性用例是必要评分内容 |
| `external-agent-4.json`，slugify_truncation，重复 1 | 分隔符映射前按旧长度提前返回；公开默认分隔符通过，隐藏自定义分隔符出现 24 failed /14 passed | 长度预算需针对最终输出；公开复现不足以覆盖变长分隔符及替换顺序 |
| `external-oneshot-4.json`，slugify_truncation，重复 1、3 | 旧文本不是唯一匹配，补丁被拒绝，未执行最终评分 | 原始广义类别为 runner_or_protocol_failure，具体审计归因为补丁匹配失败；没有证据把它称作模型超时 |

上述改进是下一阶段实验方向，**当前没有宣称已经修复这些策略问题**。正式任务、提示词和模型配置没有根据本轮成功/失败再次调优后混入结果。

## 评分器与运行修正记录

首次外部运行 [36677252700](https://github.com/Astrea-296111/RepoPilot/actions/runs/36677252700) 被取消并完全排除。当时评估器把会话存储生成的 `.repopilot` 目录当成 Agent 的非法源码修改，这会系统性误判。修正只排除评分器内部目录，源码及测试改动仍受规则约束；新提交重新完整运行了 60 次。最终比较只使用正式运行，不合并取消运行或挑选其中成功记录。

执行命令的 Docker 容器禁网，根文件系统只读，限制 CPU/内存/进程数；模型 Key 留在宿主调用器，隐藏测试、参考修复和 RepoPilot 主仓库不进入 Agent 的任务挂载。公开测试通过文件工具保护和只读挂载；评分用新工作副本仅接受允许包内的 Python 源码编辑，再注入隐藏测试。该设计改善评分可信度，但没有经过恶意代码攻击验证，不能声称绝对防绕过。

## 复查与重跑

合并已经保存的 10 个分片，无需调用模型：

```bash
python eval/summarize_external.py eval/evidence/2026-09-30/shards --output eval/results/reproduced-external-comparison.json
```

先验参考校验（需要 Docker，无需模型 Key）：

```bash
docker build -t repopilot-external:fixed -f eval/Dockerfile.external .
REPOPILOT_DOCKER_IMAGE=repopilot-external:fixed python eval/run_external.py --mode reference
```

完整真实复测在 Actions 选择 **External historical bug evaluation → Run workflow**，读取已有 `DASHSCOPE_API_KEY`，会再次产生模型费用。任务来源与人工隐藏用例的固定版本在被测试提交中可查看。本报告不触发新的付费复测。

## 能说明什么，以及下一步

这组证据比单一 Demo 更扎实：有真实上游提交、参考修复、固定独立评分、重复试验、基线、成本和失败轨迹。它足以支撑面试中对当前工程原型的机制、取舍和具体失败进行讲解；**还不足以证明通用大仓库修复能力**。历史公开修复可能进入模型训练数据，不能保证无污染；隐藏用例是人工设计，不等于完整上游集成测试。

优先级是：先用当前三个失败类别做策略对照，报告补丁与终态两种口径；再锁定新的独立 Bug 扩展测试，覆盖完整仓库依赖和跨模块任务。10 个 Bug 适合本次重复实测，扩展时以覆盖面和独立任务数为主，而非只增加重复次数。增量索引、API 认证与持久化任务索引属于后续工程范围，当前没有完成。
