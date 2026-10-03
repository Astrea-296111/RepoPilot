# 合并前修复与真实模型验收

2026-10-03，用户授权修复审查问题、使用现有 LLM API Secret 进行付费评测，并在验收后合并 PR #1。

## 审查问题与修复

| 问题 | 修复 | 回归覆盖 |
| --- | --- | --- |
| 领取后数据库读取失败，消息被确认但任务和仓库锁滞留 | 先读后领；领取事务同时更新 Task、Session、Event；结果保存成功后再 ACK | load/request 短暂失败后恢复、领取提交前/后响应丢失、同仓库后续提交 |
| Redis 已移动消息但接收响应丢失，known 去重阻止重投 | pending outbox 原子检查 ready 并回收 processing；数据库条件领取阻止重复执行 | 真实 Redis 丢响应、满队列保留滞留项、重复投递与重复 ACK |
| --no-reflection / --no-memory 无法覆盖环境变量 | 三态开关区分省略、开启、关闭 | 4 组 CLI/environment 组合 |

Worker 保留本地任务所有权，领取结果不确定时标记 interrupted，不重新执行。执行失败后的终态保存与 ACK 分别重试；数据库持续不可用时保留未确认任务，关闭后由重启恢复规则接管。此设计不声称工具副作用 exactly-once。

新增真实 Redis 故障注入测试需要服务，和 Docker/真实服务测试一起交给 CI。最终测试计数与工作流链接在验收后补充。

## 真实模型验收范围

使用仓库既有 `DASHSCOPE_API_KEY` Secret 和 DashScope 兼容接口；不输出、复制或归档密钥。

- 模型：既有评测配置 `qwen3.8-max`，medium reasoning，streaming usage。
- 固定任务：duplicate_email、shared_rounding_policy、relative_config_paths。
- 组合：custom/python 与 langgraph/mcp；两组均启用 hybrid、Reflection、Memory。
- 每次 1 run、最多 10 个决策步骤、上下文上限 16000 字符、每次输出上限 4096 Token；单请求超时 90 秒、单任务进程超时 900 秒；最多并发 2 个任务。
- 未配置真实 embedding 模型，因此本次 hybrid 为 BM25+AST；不据此声明向量召回收益。
- 通过恢复评分方测试、注入隐藏测试并独立运行评分来确定结果；不要求模型成绩 100% 才允许代码合并，但工程/基础设施故障必须排查。

最终 CI、真实模型结果与合并状态在验收完成后追加；原始响应、Token 和失败类别保存在工作流 artifacts。
