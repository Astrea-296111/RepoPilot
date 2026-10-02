# 2026-10-02 平台工程验证快照

`platform-custom.*`：custom/python + hybrid + Reflection + Memory，25 个脚本化任务。
`platform-langgraph-mcp.*`：langgraph/MCP + hybrid + Reflection + Memory，25 个脚本化任务。
`platform-retrieval.json`：最终两跳依赖重排的离线 Top-4 诊断。

前两份报告记录本地已执行的 Phase 8 组合测试；其中 LangGraph/MCP 报告运行于最后一次依赖重排调整之前。最新提交会在 GitHub Actions 重新执行完整组合，并产生新的 JSON/Markdown artifact；以 `docs/21-platform-validation.md` 的 SHA/工作流链接定位最终结果。新 runner 还会记录 source_sha256，便于将结果与运行代码对应。

这些是 FakeLLM 工程验证，不能当成真实模型能力或付费 Token 成本。检索诊断用于本轮迭代，不是保留集。
