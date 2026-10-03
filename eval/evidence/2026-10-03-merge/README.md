# 合并验收原始证据（2026-10-03）

运行代码：`1e21e2a88d7899651eaa3ec464fbeb4b4ae2607e`。后续仅添加文档与评测归档。

- [工程 CI](https://github.com/Astrea-296111/RepoPilot/actions/runs/37099257387)：Linux 完整依赖 135 passed / 8 skipped；Windows 与 Linux 基础依赖各 87 passed / 24 skipped；Docker 5 passed；10 个历史 Bug 的失败基线和参考修复验证通过。
- [真实服务与 Compose](https://github.com/Astrea-296111/RepoPilot/actions/runs/37099257390)：8 passed，三服务构建、启动、健康检查通过。完整依赖环境跳过项由 Docker 与真实服务任务覆盖。
- `ci-platform.json/.md`：全功能 FakeLLM 25/25，证明工程流程，不代表真实模型能力。
- [修复前真实模型](https://github.com/Astrea-296111/RepoPilot/actions/runs/37098761785)：`08c363e`，原始文件在 `before-reflection-fix/`。
- [修复后真实模型](https://github.com/Astrea-296111/RepoPilot/actions/runs/37099252399)：`1e21e2a`，原始文件在 `after-reflection-fix/`。

## 真实模型逐次结果

Qwen3.8-Max；3 个固定任务 × 2 个运行组合，每组只运行 1 次；hybrid（BM25+AST）、Reflection、Memory 开启。两轮均限 10 个决策步骤，每次响应输出上限 4096 Token。Memory 在独立新仓库中启用，本次没有验证历史修复记忆的收益。未调用 embedding API，不能据此声明 FAISS 语义召回质量。

| 轮次 | 运行组合 | 任务 | 结果 | 步骤 | Token |
| --- | --- | --- | --- | ---: | ---: |
| 修复前 | custom/python | duplicate_email | 成功 | 4 | 8,806 |
| 修复前 | custom/python | relative_config_paths | 成功 | 8 | 22,838 |
| 修复前 | custom/python | shared_rounding_policy | loop_failure | 10 | 29,756 |
| 修复前 | langgraph/mcp | duplicate_email | 成功 | 4 | 8,537 |
| 修复前 | langgraph/mcp | relative_config_paths | 成功 | 8 | 23,478 |
| 修复前 | langgraph/mcp | shared_rounding_policy | loop_failure | 10 | 30,757 |
| 修复后 | custom/python | duplicate_email | 成功 | 4 | 7,573 |
| 修复后 | custom/python | relative_config_paths | 成功 | 7 | 18,896 |
| 修复后 | custom/python | shared_rounding_policy | loop_failure | 10 | 31,791 |
| 修复后 | langgraph/mcp | duplicate_email | 成功 | 4 | 7,507 |
| 修复后 | langgraph/mcp | relative_config_paths | 成功 | 8 | 22,917 |
| 修复后 | langgraph/mcp | shared_rounding_policy | loop_failure | 10 | 31,057 |

两轮均为 **4/6（66.7%）**，修复后未观察到成功率提升。两组共享金额舍入任务的补丁均通过隐藏测试，但 Agent 在 10 步内没有进入成功终态，严格记为 `loop_failure`。修复后的 LangGraph 运行已经执行计划测试并查看 diff，仍未完成最终独立复验，因此不改计成功。

12 次运行共记录 **243,913 Token**，来自响应 usage 与逐次调用记录交叉核对，包含失败运行。未配置单价，不估算货币金额；服务商账单可能有不同计费规则。报告中的 total_tokens 不包含没有返回 usage 的请求，不能代替账单。

这是小型自建任务验收，未证明 SWE-bench 或实际复杂仓库上的修复率，也不能用于宣称某个 Runtime 的性能优势。运行组合同时改变 Runtime 和工具后端，且样本很小。工作流绿色表示评测完成且没有基础设施错误，不代表模型任务全部成功。

## 可追溯性

当前源码摘要：`2229bdb0148112df9e2011e632b52752f4d64c118c3eb1bc0ee104637400e59b`。已核对修复后六份报告与当前实现一致。`ci-pytest.xml`、`ci-services.xml`、`ci-docker.xml` 保留测试计数；`ci-external-reference.json` 是参考补丁验证，不能解释为 Agent 自主修复。

归档文件直接来自 GitHub Actions artifacts，未修改模型原始回答、失败原因或评分结果。`manifest.json` 保存原始工作流、Artifact ID、归档摘要及文件 SHA-256。
