# RepoPilot 增量升级设计与基线

## Phase 1：先读代码，不改实现

基线：`0cc4886`（GitHub main，2026-10-02 检出）。附件为早期版本，以远端完整源码为准。
执行：`python -m pip install -e '.[dev,full]'`；`python -m pytest -q`。
结果：**89 passed, 5 skipped，44.12 秒**。5 项需要 Docker；本机无 Docker。
常规执行沙箱下 FastAPI TestClient 等待未结束；允许本机通信后完成全量测试。

| 当前模块 | 代码入口与实际能力 | 本轮缺口 |
| --- | --- | --- |
| 自研循环 | `agent/agent.py`：结构化规划、决策、审批、工具观察、循环检测、最终独立复验 | 独立 Runtime 接口、模型 Reflection |
| LangGraph | `runtime/langgraph.py`：六个节点、条件边、InMemorySaver，复用共享状态转换 | Reflection 与失败后的重规划 |
| 工具 | `tools/`：路径限制、精确补丁、命令超时、Git diff；DockerExecutor 隔离命令 | Agent 的 MCP Client 后端、写入和 shell 协议工具 |
| MCP | `mcp_server.py`：官方 SDK v2，只读 stdio server，已有真实客户端集成测试 | 按文件/Git/shell 分组的服务器与双端权限约束 |
| 上下文 | AST 符号/签名/import，关键词 Top-K，import 依赖扩展，字符预算 | BM25、语义 embedding、FAISS、索引失效与可解释分数 |
| Session/API | 每步原子 JSON；BackgroundTasks 执行；任务 ID 仅在内存 | 数据库、持久任务查询、队列、SSE、仓库互斥 |
| 评测 | 25 个小型 bug 仓库、隐藏测试、one-shot 对照、10 个外部历史 bug | 新配置选择、平均指标、自动 Markdown 报告 |
| 部署 | Docker 沙箱与单 API Compose；无宿主 Docker socket | Redis、PostgreSQL、健康检查与运行文档 |

已检查源码、测试、评测 runner、CI 与部署入口；不更改原始 bug fixture、隐藏评分测试和历史评测证据。

## Phase 2：扩展边界

1. **共享状态转换，两种编排**：保留 `RepoPilot._run_custom`；`CustomRuntime` 作为显式入口；LangGraph 使用真实节点。旧 `runtime.langgraph` 导入兼容。
2. **Reflection 是推理建议**：可选开启，每轮工具后和最终测试失败后调用模型，结构化保存 success/reason/next_action/needs_search；失败边进入 Reflection → Planner。模型的 success 不能替代程序测试；重规划不能降低最初的测试命令。
3. **MCP 是协议边界**：保留原只读入口；新增 filesystem/git/shell server，复用现有工具实现。Agent 使用官方 SDK 客户端通过 stdio 调用，返回原 `ToolResult`。客户端审批与服务器写权限同时检查。
4. **Hybrid RAG**：AST 分块；BM25 与向量并行召回、RRF 融合、AST 相关性重排和文件聚合。FAISS 仅负责向量索引，embedding 使用配置的 OpenAI-compatible endpoint；无 embedding 配置时明确为 BM25+AST，不用随机/哈希向量冒充语义能力。缓存包含内容摘要和模型标识；代码修改后重建失效索引。
5. **持久化**：SQLAlchemy 的 Task/Session/Step/ToolCall/TokenUsage；CLI 默认 SQLite，API 支持 PostgreSQL；旧 JSON 只作为导入兼容路径。Memory 为单独 SQLite，默认按仓库召回已通过验证的经验，失败记录可审计。
6. **异步服务**：asyncio worker 使用线程运行同步 Agent；本地有界队列或 Redis 队列；数据库是状态来源，SSE 重放持久事件。相同仓库不能同时运行两个修改任务。中断的运行不自动重放 shell/patch。
7. **保留基线**：custom/python/原检索仍为兼容默认；新能力可独立启用。数据库成为默认 Session 后端；JSON 导出继续可用。不要把 framework smoke test 当模型修复成功率。

## 验证与依赖理由

每个模块后跑 pytest。Reflection 验证失败闭环与测试约束；MCP 跑真实 stdio 客户端和受限写工具；RAG 检查真实 FAISS 排序、embedding API 协议、索引失效；Memory/DB 检查持久恢复和隔离；API 检查异步接受、状态查询、SSE、重启、并发冲突；最终运行 25 任务脚本化评测。

LangGraph：显式状态边和检查点；MCP：协议互操作；rank-bm25：词项召回；FAISS：向量检索；SQLAlchemy：可查询持久状态；Redis：队列交接；PostgreSQL：服务端关系存储。不上 Celery（当前 asyncio worker 已满足单服务队列）；不引入第二套 Agent 框架或独立向量数据库。

真实模型、真实 embedding 质量和 Docker 部署分别记录是否实测；只记录可复现结果，不能把旧版本的评测数字标成新版本性能。
