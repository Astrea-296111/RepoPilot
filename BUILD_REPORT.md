# 2026-10-02 平台升级

最新交付见 [平台交付说明](docs/20-platform-handoff.md) 与 [分阶段验证记录](docs/21-platform-validation.md)。下方内容保留为历史构建记录；不得将旧版本指标归到本次新配置。

# RepoPilot 构建记录

> 本文保留 2026-09-28 初始构建时的检查与限制。它不是当前能力清单；最新测试、Docker/真实模型、LangGraph/MCP/OTel 和未验证项以 [本轮验证报告](docs/18-runtime-mcp-observability-refactor.md) 为准。


日期：2026-09-28。项目在全新目录编写，核心源码为独立实现。下面只记录执行过的检查；没有把计划或未运行的 Docker/真实模型写成成功。

## 已完成

- 可安装 Python 包和 CLI；OpenAI-compatible 模型适配器、Pydantic JSON 协议与单次修复。
- Python AST Repo Map、可解释 Top-K 检索、轻量 Planner、显式 Agent Loop、Context 预算/旧历史摘要/输出截断。
- 仓库边界文件工具、精确补丁、新文件工具、命令执行和 Git Diff；默认询问审批、Docker 执行器、可选 local；超时、三连调用停止与最大步数。
- JSON 会话列表/查看/恢复、FastAPI `/health`、创建/查询任务、结构化日志和用量字段。
- 原始失败 Demo、脚本化 FakeLLM 评测、20 项自动测试、README、12 篇中文教程/面试/简历材料、两个 Dockerfile 和 Compose。

## 实际执行的命令与结果

| 命令/检查 | 结果 |
| --- | --- |
| `python --version` | Python 3.12.14 |
| `python -m pip install -e '.[dev]'` | 安装成功；本环境用户级脚本目录不在 PATH，后续用 `python -m` 或临时加入 PATH |
| `python -m pytest -q` | **20 passed, 1 warning**；警告来自 FastAPI TestClient 所依赖的 Starlette 对 httpx 的弃用提示 |
| `PATH="$HOME/.local/bin:$PATH" repopilot --help` | 退出码 0，列出 run/sessions/show/resume/serve |
| 原始 `examples/demo_repo`: `python -m pytest -q` | **1 failed**，`ValueError: UNIQUE constraint failed: users.email`；这是故意的基线 |
| `python eval/run_eval.py` | 1 个 FakeLLM 脚本化任务 `task_success=true`，基线退出码 1、最终退出码 0、6 步、7 工具调用、只改 `app/users.py`；最近一次耗时 1.342 秒 |
| 临时 Git 副本 `python -m repopilot.cli run ... --fake-demo --executor local --approval auto` | `completed`，`tests=passed`，输出一行异常类型改动的 Git Diff；在副本目录再次 `python -m pytest -q` 为 **1 passed** |
| 启动 Uvicorn 后 `curl -i http://127.0.0.1:8765/health` | HTTP **200**、`{"status":"ok"}`；自动化测试也覆盖 `/health` |

FakeLLM 不走提供方，Token 用量字段为 0。1 个脚本化任务只能说明工具和状态闭环可工作，不能用于推算真实模型成功率或成本。

## 出现过的问题与处理

1. 初版路径越界在路径不存在时先抛 `FileNotFoundError`；改为先按非严格路径解析并检查边界，测试覆盖了 `../../` 和越界符号链接。
2. 初版拒绝审批的结果没有写入 tool history；已统一记录为 Observation，测试覆盖。
3. 环境用 `pip --user` 安装，裸 `pytest` 脚本不在 PATH；Demo/评测的命令改为 `python -m pytest -q`。用户激活项目 venv 后也可用 `pytest -q`。
4. 一次手工复验从项目根目录直接运行临时副本的绝对测试文件路径，导致 `ModuleNotFoundError: app`；改在 Demo 副本的工作目录运行后得到 `1 passed`。Agent 自身的命令一直以目标仓库为工作目录。
5. 单独后台启动的服务在随后另一次命令里不可达；同一运行命令内启动服务并用 curl 实测得到 HTTP 200。自动测试的 TestClient 检查同样通过。

## 尚未实现或尚未经验证

- 当前环境没有 `docker` 可执行文件：`docker build -f Dockerfile.sandbox ...`、`docker compose build/up`、DockerExecutor 的实际容器运行和 Compose 的网络/权限**均未验证**。Dockerfile 与 Compose 已提供，但不能写「部署成功」。
- 没有真实 `LLM_API_KEY`/`LLM_MODEL`：兼容提供方的 HTTP 调用、真实模型规划与修复、真实 token/cost、跨任务成功率**未测**。
- REST 的 `/health` 和路径限制有测试，`POST /api/tasks` 的真实模型后台运行没有端到端验证；API 无认证，只能放本机/私有网络。任务 ID 查找仅在进程内，重启后可通过会话文件恢复历史。
- Docker 是减风险机制，不能保证可写仓库安全；LocalExecutor 也不能视为沙箱。`git_diff` 对未跟踪文件只列路径，不展示完整新文件内容。
- Repo Map 最多 4000 个文件；中文检索词表有限；计划测试命令由模型选择。复杂多语言仓库、SWE-bench、BM25/向量索引与质量评估仍是 Roadmap。

## 下一步建议

1. 在装有 Docker 的机器，先构建 `Dockerfile.sandbox`，用可信 Demo 副本跑 DockerExecutor；然后 `docker compose build/up` 并复测 `/health` 与有权限的任务。
2. 配置真实兼容模型，在多个独立 Bug 仓库上用干净 Git 副本多次运行；记录成功、错误类别、步骤、成本和用量，才能写真实模型指标。
3. 在大仓库补增量索引与混合检索，再用任务集比较召回率和实际修复率；API 投入多人使用前加认证与持久任务索引。

## 提交记录

项目已建立独立 Git 仓库，按模块提交核心上下文工具、Agent/API/测试、验证修正和文档。运行 `git log --oneline` 查看完整历史；原始 Demo 仍保持故意失败，评测每次复制后修复。
