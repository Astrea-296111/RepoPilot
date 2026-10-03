# RepoPilot Evaluation Report

证据类型：**脚本化工程验证；不代表真实模型修复成功率。**

配置：`{"runtime": "langgraph", "tool_backend": "mcp", "retrieval_mode": "hybrid", "reflection": true, "memory": true}`

源码摘要：`2229bdb0148112df9e2011e632b52752f4d64c118c3eb1bc0ee104637400e59b`。

| 指标 | 数值 |
| --- | --- |
| 任务数 / 运行数 | 25 / 25 |
| Task Success Rate（隐藏复测通过且 Agent 完成） | 25/25 = 100.0% |
| Average Steps | 2 |
| Average Token Count（chat） | 0 |
| Average Token Cost（chat；用户指定价格单位） | 未测 / 不适用 |
| Average Tool Call Number（含缓存/拒绝记录） | 3 |
| Average Executed Tool Calls | 3 |
| 有完整 Agent 指标的运行数 | 25 |

金额只在真实模型和输入/输出单价均明确时估算；embedding 单独记录 Token，不混入 chat 费用。基础设施失败仍计入总运行分母，缺失的 Agent 步数/Token 不伪造为零。FakeLLM 不消耗模型 Token，0 不能解释为真实模型成本。

## Failure Category

```json
{}
```

## 逐任务证据

| 任务 | 次数 | 结果 | 步数 | Token | 工具记录 | 失败类别 |
| --- | --- | --- | --- | --- | --- | --- |
| duplicate_email | 1 | 通过 | 2 | 0 | 3 | — |
| pagination_off_by_one | 1 | 通过 | 2 | 0 | 3 | — |
| config_precedence | 1 | 通过 | 2 | 0 | 3 | — |
| safe_path_traversal | 1 | 通过 | 2 | 0 | 3 | — |
| inventory_atomic_reserve | 1 | 通过 | 2 | 0 | 3 | — |
| normalize_username | 1 | 通过 | 2 | 0 | 3 | — |
| ttl_expiry_boundary | 1 | 通过 | 2 | 0 | 3 | — |
| retry_backoff | 1 | 通过 | 2 | 0 | 3 | — |
| slugify_text | 1 | 通过 | 2 | 0 | 3 | — |
| authorization_owner | 1 | 通过 | 2 | 0 | 3 | — |
| discount_order | 1 | 通过 | 2 | 0 | 3 | — |
| csv_header_mapping | 1 | 通过 | 2 | 0 | 3 | — |
| deep_merge_nested | 1 | 通过 | 2 | 0 | 3 | — |
| inclusive_date_span | 1 | 通过 | 2 | 0 | 3 | — |
| parse_bool_env | 1 | 通过 | 2 | 0 | 3 | — |
| account_transfer_atomic | 1 | 通过 | 2 | 0 | 3 | — |
| rate_limit_boundary | 1 | 通过 | 2 | 0 | 3 | — |
| extension_filter | 1 | 通过 | 2 | 0 | 3 | — |
| average_empty | 1 | 通过 | 2 | 0 | 3 | — |
| dedupe_preserve_order | 1 | 通过 | 2 | 0 | 3 | — |
| shared_rounding_policy | 1 | 通过 | 2 | 0 | 3 | — |
| shared_identifier_normalization | 1 | 通过 | 2 | 0 | 3 | — |
| shared_retry_policy | 1 | 通过 | 2 | 0 | 3 | — |
| relative_config_paths | 1 | 通过 | 2 | 0 | 3 | — |
| shared_feature_flag_precedence | 1 | 通过 | 2 | 0 | 3 | — |

评分流程：复制干净仓库 → 确认原始测试失败 → Agent 修复 → 恢复评分方拥有的测试 → 注入隐藏测试 → 独立复测。
不向真实模型暴露 scripted_fixes 或隐藏测试。长期记忆在临时副本内隔离，不跨评测任务传播参考修复。
