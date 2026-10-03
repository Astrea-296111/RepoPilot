# 合并前修复与真实模型验收

2026-10-03，用户授权修复审查问题、使用现有 LLM API Secret 进行付费评测，并在验收后合并 PR #1。

## 审查问题与修复

| 问题 | 修复 | 回归覆盖 |
| --- | --- | --- |
| 领取后数据库读取失败，消息被确认但任务和仓库锁滞留 | 先读后领；领取事务同时更新 Task、Session、Event；结果保存成功后再 ACK | load/request 短暂失败后恢复、领取提交前/后响应丢失、同仓库后续提交 |
| Redis 已移动消息但接收响应丢失，known 去重阻止重投 | pending outbox 原子检查 ready 并回收 processing；数据库条件领取阻止重复执行 | 真实 Redis 丢响应、满队列保留滞留项、重复投递与重复 ACK |
| --no-reflection / --no-memory 无法覆盖环境变量 | 三态开关区分省略、开启、关闭 | 4 组 CLI/environment 组合 |

Worker 保留本地任务所有权，领取结果不确定时标记 interrupted，不重新执行。执行失败后的终态保存与 ACK 分别重试；数据库持续不可用时保留未确认任务，关闭后由重启恢复规则接管。此设计不声称工具副作用 exactly-once。

新增真实 Redis 故障注入测试需要服务，和 Docker/真实服务测试一起交给 CI。本地最终完整回归：**135 passed、8 skipped，91.37 秒**；跳过的是 5 个 Docker、3 个真实服务测试，由独立 CI 验证。故障恢复、CLI、数据库和 LLM 请求格式针对性回归为 18 passed。

## 真实评测发现的 Reflection 问题

首轮使用 `08c363e`，6 次运行完成 4 次。两组 `shared_rounding_policy` 虽然产生了通过隐藏测试的补丁，但反复读取文件，在 10 步预算内没有完成 Agent 验证与终态流程，严格记为 `loop_failure`，不能改计成功。

检查模型轨迹发现 Reflection 只收到最近两次工具观察，重复建议检查早先已读文件。`1e21e2a` 增加有界早期观察摘要，保留工具目标、成功状态和输出片段，附带工作区/测试版本，提示模型在合理补丁后优先执行原定测试。同时用字段级裁剪保证长输入依然是合法 JSON，替代直接截断序列化字符串。新增回归覆盖早期证据、后续补丁及极长控制字符输出；Reflection 两 Runtime 相关测试 8 passed。

复测使用相同的 3 个任务、两种运行组合和 10 步预算。首轮原始记录一并保留，单次小样本前后比较不能证明普遍性能提升。

## 真实模型验收范围

使用仓库既有 `DASHSCOPE_API_KEY` Secret 和 DashScope 兼容接口；不输出、复制或归档密钥。

- 模型：既有评测配置 `qwen3.8-max`，medium reasoning，streaming usage。
- 固定任务：duplicate_email、shared_rounding_policy、relative_config_paths。
- 组合：custom/python 与 langgraph/mcp；两组均启用 hybrid、Reflection、Memory。
- 每次 1 run、最多 10 个决策步骤、上下文上限 16000 字符、每次输出上限 4096 Token；单请求超时 90 秒、单任务进程超时 900 秒；最多并发 2 个任务。
- 未配置真实 embedding 模型，因此本次 hybrid 为 BM25+AST；不据此声明向量召回收益。
- 通过恢复评分方测试、注入隐藏测试并独立运行评分来确定结果；不要求模型成绩 100% 才允许代码合并，但工程/基础设施故障必须排查。

## 最终验收

程序代码提交：`1e21e2a88d7899651eaa3ec464fbeb4b4ae2607e`，此后仅归档文档和报告。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Linux Python 3.12 完整依赖 | 135 passed / 8 skipped | [工程 CI](https://github.com/Astrea-296111/RepoPilot/actions/runs/37099257387) |
| Windows / Linux 基础依赖 | 各 87 passed / 24 skipped | 同上 |
| Docker Sandbox | 5 passed，双 Runtime Demo 通过 | 同上 |
| 10 个历史 Bug 的失败基线/参考修复 | 通过；不是 Agent 自主修复成绩 | 同上 |
| Redis/PostgreSQL/API | 8 passed，包括 Redis 接收响应丢失 | [服务 CI](https://github.com/Astrea-296111/RepoPilot/actions/runs/37099257390) |
| Compose | 构建、三服务启动和健康检查通过 | 同上 |
| 全功能 FakeLLM | 25/25 | 工程 CI |
| 真实模型最终配置 | 4/6，2 次 max_steps；原始评分未修改 | [真实评测](https://github.com/Astrea-296111/RepoPilot/actions/runs/37099252399) |

真实模型前后两轮均为 4/6，不能声称 Reflection 修改提高成功率。两轮 12 次运行共记录 243,913 Token，包含失败运行；没有提供商单价，因此不虚构金额。两个共享逻辑任务的补丁通过隐藏测试，但没有完成 Agent 成功终态，仍记失败。此结果表明真实 API、两条运行路径和付费调用已接通，也说明当前模型仍有重复调查、预算分配和任务收尾效率问题。

[原始 JSON/Markdown、测试 XML、源码摘要和 Artifact 清单](../eval/evidence/2026-10-03-merge/README.md) 已归档。最终六份真实模型报告的源码摘要与当前实现一致。评测采用 BM25+AST，未验证真实 embedding 质量或 Memory 历史召回收益。

审查中的两个 P1 故障恢复问题和 CLI 配置问题已修复并回归通过，工程验收满足本次合并标准。模型小样本未全部成功是明确保留的能力边界，不能把工作流绿色当成模型 100% 成功率。[PR #1](https://github.com/Astrea-296111/RepoPilot/pull/1) 为合并状态与最终提交的权威记录。
