# RepoPilot Evaluation Report

证据类型：真实模型运行；仅适用于本报告任务集和配置。

配置：`{"runtime": "langgraph", "tool_backend": "mcp", "retrieval_mode": "hybrid", "reflection": true, "memory": true}`

源码摘要：`bc7aec51ea356a5d2ef62c33e920533af806d2949c23e664fea9c6fa029c9120`。

| 指标 | 数值 |
| --- | --- |
| 任务数 / 运行数 | 1 / 1 |
| Task Success Rate（隐藏复测通过且 Agent 完成） | 0/1 = 0.0% |
| Average Steps | 10 |
| Average Token Count（chat） | 30757 |
| Average Token Cost（chat；用户指定价格单位） | 未测 / 不适用 |
| Average Tool Call Number（含缓存/拒绝记录） | 10 |
| Average Executed Tool Calls | 10 |
| 有完整 Agent 指标的运行数 | 1 |

金额只在真实模型和输入/输出单价均明确时估算；embedding 单独记录 Token，不混入 chat 费用。基础设施失败仍计入总运行分母，缺失的 Agent 步数/Token 不伪造为零。FakeLLM 不消耗模型 Token，0 不能解释为真实模型成本。

## Failure Category

```json
{
  "loop_failure": 1
}
```

## 逐任务证据

| 任务 | 次数 | 结果 | 步数 | Token | 工具记录 | 失败类别 |
| --- | --- | --- | --- | --- | --- | --- |
| shared_rounding_policy | 1 | 失败 | 10 | 30757 | 10 | loop_failure |

评分流程：复制干净仓库 → 确认原始测试失败 → Agent 修复 → 恢复评分方拥有的测试 → 注入隐藏测试 → 独立复测。
不向真实模型暴露 scripted_fixes 或隐藏测试。长期记忆在临时副本内隔离，不跨评测任务传播参考修复。
