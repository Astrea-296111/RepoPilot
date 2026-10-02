# RepoPilot 平台升级验证记录

日期：2026-10-02。基线 `0cc4886`。升级 PR：[PR #1](https://github.com/Astrea-296111/RepoPilot/pull/1)。本记录只把已执行结果写成通过。

## 逐阶段汇报

| 阶段 | 改动和主要文件 | 当阶段全量 pytest | 下一步 |
| --- | --- | --- | --- |
| Phase 1 | 只读分析源码、测试、评测、CI；无源码修改 | 89 passed / 5 skipped | 确定可复用边界 |
| Phase 2 | docs/19-platform-upgrade-plan.md，明确共享状态转换与可选开关 | 沿用基线；尚未改运行代码 | Runtime |
| Phase 3 | runtime、agent/reflection、AgentState、Context、CLI | 95 passed / 5 skipped | MCP |
| Phase 4 | tools/backends、三个 MCP Server、git_status、CLI | 100 passed / 5 skipped | Hybrid RAG |
| Phase 5 | chunks、embeddings、hybrid、检索展示和失效重建 | 107 passed / 5 skipped | Memory / Database |
| Phase 6 | database、memory、SessionStore 和旧 JSON 导入 | 114 passed / 5 skipped | API / Docker |
| Phase 7 | api/queue、api/tasks、SSE、coordinator、Compose、服务 CI | 119 passed / 7 skipped | 组合评测和交付文档 |
| Phase 8 第一轮 | 新评测开关与 Markdown、全功能 CLI、真实 HTTP SSE 测试 | 123 passed / 7 skipped | 修正共享依赖检索并复验 |
| Phase 8 后续 | 两跳依赖重排、严格 Reflection schema、报告源码摘要 | 相关 22 项通过；最新全量结果见下文 | 归档 CI 和交付 |

前 5 个跳过项需要 Docker；后增加 2 个真实 Redis/PostgreSQL 测试，当前本机无对应服务。已在 GitHub Actions 使用真实容器执行，不把跳过当通过。

最后一次本机扩大权限测试因自动审批服务使用额度不足而未执行；此前已完成的 123 项与后续普通沙箱的 22 项结果有效。该限制不是代码测试失败，最终完整配置由 GitHub Actions 复验。

## 已完成的 CI

首个完整平台提交 `b35738e`：

- [Platform services](https://github.com/Astrea-296111/RepoPilot/actions/runs/37010513974)：真实 PostgreSQL + Redis API、LangGraph/MCP/hybrid/Memory、状态持久化、SSE 测试通过；服务测试共 7 项。
- 同一工作流的 Compose job：`docker compose config`、镜像构建、三服务启动、健康检查及 HTTP `/health` 通过。
- [Windows evaluation](https://github.com/Astrea-296111/RepoPilot/actions/runs/37010513907)：Windows、Linux Python 3.11 基础依赖、Python 3.12 完整依赖、25 任务脚本化评测通过。
- 上述工作流的 Docker job：真实 DockerExecutor、受保护挂载、资源限制、禁网、超时、双 Runtime Demo，以及不变的外部历史 Bug 参考修复验证通过。
- 付费模型 jobs 未触发。外部历史 Bug 的参考修复通过不等于新 Agent 自主修复通过。

后续提交增加报告、实时 SSE 及检索修正，不能直接沿用旧 SHA 的绿色状态；最新提交的 CI 结果会追加到本节。

## 25 任务组合评测

本地工程验证快照保存在 [eval/evidence/2026-10-02-platform](../eval/evidence/2026-10-02-platform/)。两组都启用 hybrid、Reflection、Memory：

| 编排 / 后端 | 成功 / 运行 | 平均步骤 | 平均工具调用 | chat Token | 金额 |
| --- | --- | --- | --- | --- | --- |
| custom / python | 25 / 25 | 2 | 3 | 0 | 不适用 |
| langgraph / mcp | 25 / 25 | 2 | 3 | 0 | 不适用 |

每个任务使用已知补丁的 FakeLLM，2 步通常是 patch + final；程序执行补丁、独立测试及 Git diff 共 3 次工具调用。结果证明工程组合可工作，**不是模型修复能力**。无实际模型请求，Token=0 不能用于宣传成本下降。

评测流程保留原协议：确认原始仓库失败 → Agent 修复 → 恢复评分方测试 → 注入隐藏测试 → 独立评分；不修改基线 fixture 和历史证据。每个任务的 Memory 在临时副本中隔离。

报告自动生成 JSON 与 Markdown；失败类别包含环境、模型传输/超时、协议、循环、Agent 与行为失败。未指定单价时不生成虚构费用；初始化失败仍计入总运行分母，缺失的步骤与 Token 不伪造为零。

## 检索诊断与发现

命令：`python eval/measure_retrieval.py --hybrid --json-out eval/results/platform-retrieval.json`。

| 模式 | Top-4 包含全部参考修复文件的任务数 | 平均选中文件数 | 平均源码字符 |
| --- | --- | --- | --- |
| 原关键词检索 | 20 / 25 | 2.16 | 409.7 |
| 原关键词 + import 图 | 25 / 25 | 2.36 | 440.2 |
| 新 BM25 + AST/import 重排 | 25 / 25 | 2.48 | 450.1 |

初版新检索只有 23/25，原因是关键词命中测试/调用方后，共享 helper 在 Top-4 之外。修正为最多两跳、最多 32 个依赖候选，并考虑源文件入度，保留原 import 图对共享实现的覆盖。该诊断参与了迭代，不是独立保留集；不能宣传为泛化指标。

以上离线对比没有调用真实 embedding。FAISS 用真实索引和可控 fixture 向量验证排序/存取，embedding HTTP 协议用受控响应验证；这两类测试不能证明真实模型语义召回质量，也不能把新方案相对原 import 图写成“召回率提升”。

## 交付边界

已验证真实协议、实际状态编排、数据库关系保存、队列交接、SSE 流、容器启动和工程回归。当前仍没有本轮真实模型成本/成功率、真实 embedding 质量、生产负载与多租户认证验证。LangGraph 的持久恢复桥接使用 AgentState 数据库，非持久 LangGraph checkpoint；MCP 连接内置三个本地 Server；索引是整代失效重建；Memory 为同仓库 FTS5。

新用户先运行无密钥 Demo；随后在可信仓库副本配置真实模型，使用固定任务集做重复对照，再决定是否开启 Reflection、向量检索或 Memory。简历可写工程实现、测试覆盖和评测设计，不应填入未测的业务指标。
