# RepoPilot

**一个能理解仓库、修改代码、运行测试并根据失败继续修复的轻量 Coding Agent。**

保留自研 Agent Loop，同时支持 **LangGraph Workflow、MCP 工具后端、Hybrid RAG、Reflection、SQLite 修复记忆、SQLAlchemy 持久化和异步任务 API**。适合学习、工程验证和可信仓库上的辅助开发；目前不是可直接开放给多租户的生产服务。

完整交付说明：[架构、文件清单、执行流程和面试讲解](docs/20-platform-handoff.md)。升级前分析：[设计与基线](docs/19-platform-upgrade-plan.md)。逐阶段结果：[验证记录](docs/21-platform-validation.md)。历史评测证据保留在 `eval/evidence/`，不能当作本次配置的模型成绩。

最新验收：[合并前故障修复、真实模型评测与验证边界](docs/22-merge-readiness.md)。原始记录：[2026-10-03 合并验收](eval/evidence/2026-10-03-merge/README.md)。

## 能力与边界

| 能力 | 实际实现 | 为什么引入 |
| --- | --- | --- |
| Custom Runtime | 自研结构化决策、审批、工具观察、循环检测、独立测试复验 | 清楚控制执行语义，保留可比较的基线 |
| LangGraph | prepare / plan / decide / tool / reflection / verify / finalize 节点与条件边 | 显式表达失败分支，支持进程内节点检查点 |
| Reflection | 每个工具轮后反思；最终测试失败进入 Reflection → Planner | 把失败原因、搜索需求、下一步保存为状态和上下文 |
| MCP | 官方 Python SDK v2 Client，通过 stdio 连接 filesystem/git/shell server | 工具逻辑与 Agent 编排分离，支持协议复用 |
| Hybrid RAG | AST 分块、BM25、真实 embedding、FAISS、RRF 和 import 重排 | 结合标识符精确检索与语义检索，展示召回理由 |
| Memory | SQLite FTS5，记录 task/repo/solution/error/fix | 召回当前仓库已验证的类似修复，减少重复调查 |
| Database | SQLAlchemy Task/Session/Step/ToolCall/TokenUsage/Event | 跨进程查询、恢复、审计和事件续读 |
| API/Queue | FastAPI、asyncio worker、本地队列或 Redis、SSE | 提交立即返回，长任务后台执行，进度可实时读取 |
| Evaluation | 25 个小型 Bug 仓库、隐藏复测、JSON+Markdown、配置对照 | 分开验证工程流程和真实模型能力 |
| Docker | 独立 DockerExecutor；api/redis/postgres Compose | 限制命令执行资源，提供可复现服务部署 |

## 安装

Python 3.11+、Git；运行 DockerExecutor 还需要 Docker。

```bash
python -m venv .venv
source .venv/bin/activate                 # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev,full]'
cp .env.example .env                     # PowerShell: Copy-Item .env.example .env
repopilot --help
```

基础安装 `pip install -e '.[dev]'` 支持 custom/python/legacy 检索和数据库。可选 extras：`langgraph`、`mcp`、`rag`、`server`、`observability`；`full` 安装全部。

真实模型配置 `LLM_BASE_URL`（包含 `/v1`）、`LLM_API_KEY`、`LLM_MODEL`。Reflection 多出模型调用；Memory 和新检索默认关闭，便于与原配置比较。

可设置 `LLM_MAX_OUTPUT_TOKENS` 限制每次模型响应的输出 Token。CLI 的 `--reflection/--no-reflection`、`--memory/--no-memory` 显式覆盖环境配置；省略开关时才继承环境变量。

## 无密钥演示

演示脚本复制原始 Bug 仓库并初始化 Git，不会修掉仓库中保留的失败基线：

```bash
python eval/demo.py --runtime custom
python eval/demo.py --runtime langgraph --tool-backend mcp --retrieval hybrid --reflection --memory
```

这里的 FakeLLM 执行预先写好的动作，只能证明组件接通、补丁和测试流程正确；不能据此宣称真实模型修复率或 Token 节省。未配置 embedding 模型时，`hybrid` 明确报告 `bm25+ast`。

## 运行真实任务

```bash
docker build -f Dockerfile.sandbox -t repopilot-sandbox:dev .
repopilot run /path/to/git-repo "修复重复邮箱注册错误" --runtime custom --executor docker --approval ask
repopilot run /path/to/git-repo "修复重复邮箱注册错误" --runtime langgraph --tool-backend mcp --retrieval hybrid --reflection --memory --executor docker --approval ask
```

两种 Runtime 共用工具、审批、循环限制、测试证据失效和最终独立复验。Reflection 的 `success` 只代表模型意见；完成状态仍要求程序实际执行测试并成功生成 Git diff。失败重规划保留最初的测试命令。默认最多 15 个决策步骤，重复行动有有界反馈和停止机制。

`--approval never` 禁止写入和命令，`auto` 自动允许；`--executor local` 仅用于可信仓库副本。命令超时为 1–120 秒，输出有长度限制。

## 看懂检索结果

```bash
repopilot retrieve /path/to/repo "修复用户注册重复邮箱" --top-k 5
```

输出包含 mode、cache_hit，以及每个文件的 score、BM25/向量/AST 分项、命中行号和原因。Agent 真正使用命中的代码片段构造上下文。

- 配置 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_API_KEY` 后，代码块发送到该服务生成真实 embedding；FAISS 使用归一化向量的内积检索。
- 未配置 embedding 模型时采用 BM25+AST。请求失败时明确报错，不用伪向量冒充语义能力。
- 两路检索独立召回、RRF 融合，再结合符号匹配和本地 import 关系重排。分数是排序信号，不是正确概率。
- 缓存位于目标仓库 `.repopilot/repo_index/<内容与模型摘要>/`，包含 `ast_index.json`、`bm25_index.json`、`chunks.json`、`manifest.json`，向量模式还包含 `faiss.index`。
- 源码或模型标识变化会重建一代完整索引。当前不是逐块增量索引；旧代可直接删除，成本优化留待大仓库验证。

## MCP 工具

`--tool-backend python` 为默认；`mcp` 使用官方 SDK 客户端和真实 stdio 子进程，复用同一组 Python 工具与执行器。

| Server | Tools |
| --- | --- |
| filesystem | read_file、search_code、write_file、apply_patch |
| git | git_diff、git_status |
| shell | run_command |

原命令 `repopilot mcp REPO` 仍只提供 repo_map/read_file/search_code/git_diff。分组服务器可独立运行：

```bash
python -m repopilot.mcp_server.filesystem_server /path/to/repo
python -m repopilot.mcp_server.filesystem_server /path/to/repo --allow-write
python -m repopilot.mcp_server.shell_server /path/to/repo --allow-shell --executor docker
```

Agent 客户端先检查审批，服务器再次检查写权限、路径和保护文件。协议异常不自动重放写入；Agent 需要重新观察当前仓库。子进程在单次运行结束时关闭。当前内置后端连接受控的三个本地服务器；任意第三方远程 MCP 注册、OAuth 和工具发现路由尚未实现。

## 会话、数据库和 Memory

```bash
repopilot sessions /path/to/repo
repopilot show SESSION_ID --repo /path/to/repo
repopilot resume SESSION_ID --repo /path/to/repo --executor docker --approval ask
```

CLI 默认 SQLAlchemy + `.repopilot/repopilot.db`；设置 `REPOPILOT_DATABASE_URL` 可使用 PostgreSQL（安装 `server` extra）。Task 保存状态与仓库互斥键，Session 保存可恢复快照，Step/ToolCall/TokenUsage 支持审计，Event 支持 SSE 续读。

旧 `.repopilot/sessions/*.json` 在读取时导入；已有数据库状态优先。`show` 继续输出 JSON。恢复时复用原 runtime/backend/retrieval/reflection/memory，executor/approval 必须与原任务一致；跨进程恢复从下一次决策开始，不能保证崩溃瞬间工具的 exactly-once 语义。LangGraph InMemorySaver 仅在当前进程有效。

`--memory` 启用 `.repopilot/memory.db`。短期记忆来自当前会话近期观察和早期摘要；长期记忆记录历史修复，通过 FTS5 召回。只召回同仓库中测试通过的经验；失败经验可审计。历史补丁是参考，不自动套用，当前任务必须重新验证。暂不跨仓库共享、不做向量记忆。

数据库当前为初始建表，不能自动迁移任意未来 schema。后续改表需要新增迁移脚本。

## 异步 API 与 SSE

```bash
export REPOPILOT_API_ROOT=/path/to/repos
repopilot serve
curl -X POST http://127.0.0.1:8000/api/tasks -H 'Content-Type: application/json' \
  -d '{"repo_path":"/path/to/repos/demo","task":"修复重复邮箱","executor":"docker","approval":"auto","runtime":"langgraph","tool_backend":"mcp","retrieval":"hybrid","reflection":true,"memory":true}'
curl http://127.0.0.1:8000/api/tasks/TASK_ID
curl -N http://127.0.0.1:8000/api/tasks/TASK_ID/stream
curl -N -H 'Last-Event-ID: 3' http://127.0.0.1:8000/api/tasks/TASK_ID/stream
```

POST 返回 HTTP 202 和 task_id（保留 id）；GET 返回 status/steps/logs；SSE 发送持久事件，终态发出 end，支持 Last-Event-ID 或 after 参数。API 默认 approval=never，不能交互询问。允许 local 还需 `REPOPILOT_API_ALLOW_LOCAL=1`。

默认使用本地有界 asyncio 队列；设置 `REPOPILOT_REDIS_URL` 启用 Redis。数据库 pending 行作为待投递记录，Redis 只负责交接；数据库条件更新去重领取，避免重复排队直接重复执行。每个数据库只允许一个 API coordinator，内部默认 2 个 worker；请勿开多个 Uvicorn workers。最多 100 个活跃任务，超额返回 429，同仓库并发返回 409。

服务重启会重新投递 pending；已领取的任务标为 interrupted，要求检查工作区后手动恢复。正常关闭等待当前任务结束；无法安全强杀正在修改仓库的 Python 线程。SSE 当前轮询数据库事件，不是分布式推送平台。

领取事务同时更新任务、快照和事件。领取前读取失败由 outbox 重投；领取结果不确定时持久化 interrupted；执行后的结果保存与 ACK 可重试，但不重跑 Agent。Redis 接收响应丢失时，pending outbox 会原子恢复滞留消息；可能出现的重复投递仍受数据库条件领取约束。数据库持续不可用期间保留任务所有权，停止时留下未确认任务供重启检查。

## Docker Compose

```bash
# 将可信仓库副本放入 workspaces，并初始化 Git
cp -R examples/demo_repo workspaces/demo_repo
git -C workspaces/demo_repo init
git -C workspaces/demo_repo add .
git -C workspaces/demo_repo -c user.name=Demo -c user.email=demo@example.invalid commit -m baseline
# Linux：.env 的 REPOPILOT_HOST_UID/GID 设置为 id -u / id -g 的输出
docker compose up -d --build --wait
curl http://127.0.0.1:8000/health
```

包含 api、redis、postgres，配置健康检查和持久卷；仅 API 8000 端口绑定 127.0.0.1。Compose 请求 repo_path 使用 `/workspace/repos/demo_repo`，executor 使用 `local`。这个模式在 API 容器内执行代码，隔离粒度是整个服务容器；CLI 的 DockerExecutor 才是逐命令临时容器。没有挂载宿主 Docker socket。

API 无用户系统和认证，不能直接暴露公网。Docker 不是绝对安全边界；可写仓库、同容器密钥和宿主 daemon 都需纳入部署考虑。文件工具拒绝越界、内部管理目录及 `.env`，shell 能访问执行器允许的资源。

## 测试与评测

```bash
python -m pytest -q
python eval/run_benchmark.py --fake --require-all
python eval/run_benchmark.py --fake --runtime langgraph --tool-backend mcp --retrieval hybrid --reflection --memory --require-all --output eval/results/platform.json
python eval/measure_retrieval.py --hybrid --json-out eval/results/retrieval.json
```

评测每次复制干净 Bug 仓库，先验证失败，再修复；最终恢复评分方拥有的测试并加入隐藏测试。自动产生同名 JSON/Markdown，包含 Task Success Rate、Average Steps、Average Token Count、Tool Calls、Failure Category。

真实模型去掉 `--fake`。金额只有显式提供 `--input-price-per-million` 和 `--output-price-per-million` 才估算；价格单位由调用者指定，embedding Token 单列。初始化失败仍计入成功率分母，缺失的步骤和 Token 不伪造为 0。

GitHub Actions 覆盖 Windows、Linux 基础/完整依赖、DockerExecutor、外部参考补丁，以及真实 PostgreSQL+Redis API、Compose。自动流程不调用付费模型，真实模型评测须显式触发。

Actions 的 **Bounded real-model platform evaluation** 可手动勾选 `run_real_model`，使用 `DASHSCOPE_API_KEY` Secret 跑 3 个固定任务 × 2 种组合；每次最多 10 步、单次输出上限 4096 Token。维护者也可在 push 提交说明中加入 `[platform-real-eval]` 显式触发。普通 PR、push 和 merge 不触发这组付费请求。结果保存在每个任务的 JSON/Markdown artifact；这是小样本真实流程验证，不能替代完整基准或多次运行统计。

## 源码入口

`agent/` 保留共享状态转换；`runtime/` 选择编排；`tools/` 实现工具与后端；`mcp_server/` 负责协议；`context/` 构造地图、索引和上下文；`memory/` 与 `database/` 提供记忆和持久化；`api/` 负责队列与流；`eval/` 保留原有基准和新增报告。

开源参考见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。旧版学习文档从 [docs/00-项目总览.md](docs/00-项目总览.md) 开始，理解升级代码请优先阅读本 README 与新交付文档。
