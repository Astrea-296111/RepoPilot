# RepoPilot

**一个可以读仓库、改代码、跑测试并复查结果的轻量 Coding Agent。** 输入任务和仓库路径后，RepoPilot 先做代码地图与检索，再让模型规划；随后按「模型选择工具 → 程序执行 → 将观察送回模型」循环工作。它提供 CLI、REST API、JSON 会话、Docker/本地执行器和一个可复现的坏例子。

## 为什么做

单次模型修复也能在补丁后运行测试，但无法根据失败继续查找和修复。本项目把决定与执行分开：模型只返回受 Pydantic 校验的 JSON；Python 负责工具、审批、路径检查和最终测试。核心循环见 [`repopilot/agent/agent.py`](repopilot/agent/agent.py)。它适合学习和小规模实验，不承诺自动修复任意真实仓库。

## 核心能力

| 模块 | V1 做了什么 |
| --- | --- |
| Repo Map / 检索 | AST 提取 Python 类、函数、签名、import；文件名、符号、文本 Top-K 加同仓库导入关系补全；中文 Demo 有有限词表 |
| Planner / Agent | 结构化计划、显式循环、失败观察、JSON 一次修复、三连重复停止、`max_steps` |
| Context | 任务/计划、近期观察、早期摘要、相关代码、截断地图，总字符预算 |
| Tools | `read_file`、`search_code`、`apply_patch`、`write_file`、`run_command`、`git_diff` |
| 执行/审批 | 默认 Docker 和 `ask`；可选 local、auto、never；命令限时、输出限长 |
| 接口/记录 | CLI、无认证的本地 FastAPI、逐步保存 JSON transcript 和 token usage（若服务返回） |

## 架构图

```text
用户任务 ──> Repo Map + Retrieval ──> Planner
                                      │
                                      v
                              Context Manager
                                      │
                                      v
                              Agent Loop + LLM
                                      │
                           校验 JSON / Approval
                                      │
               ┌──────────────────────┼────────────────────┐
               v                      v                    v
             Files                  Search             Command/Git
                                      │                    │
                                      └──── Observation ◀──┘
                                               │
                                      失败重试 / 最终复验
                                               │
                                      Session + Git Diff
```

## Agent 执行流程

`run()` 先生成 Repo Map 和 Top-K，`plan_task()` 返回 `goal/steps/test_command`。每一步构造有预算的上下文，调用模型一次；模型选工具后校验 JSON，检查权限，执行并把观察写入会话。模型要求结束时，程序**重新执行计划的测试命令**，测试失败就把结果送回下一轮。三次相同调用会停止；超过步数会失败。注意测试通过只能验证所运行的测试，不能证明代码完全正确。

## 快速开始

Python 3.11+、Git。macOS/Linux：

```bash
cd RepoPilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
repopilot --help
```

Windows PowerShell：

```powershell
cd RepoPilot
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
repopilot --help
```

在 `.env` 配置 `LLM_BASE_URL`（应包含 `/v1`）、`LLM_API_KEY`、`LLM_MODEL`；无需真实密钥可运行下面的 FakeLLM Demo。真实模型默认先使用 Docker：

```bash
docker build -f Dockerfile.sandbox -t repopilot-sandbox:dev .
repopilot run /path/to/your-git-repo "修复重复邮箱注册失败的问题" --executor docker --approval ask
```

Docker 镜像预装 `pytest`；项目有额外测试依赖时，自行扩展 `Dockerfile.sandbox`，并通过 `REPOPILOT_DOCKER_IMAGE` 指向新镜像。Docker 命令在容器内禁网、限制资源，工作区以可写方式挂载。模型调用发生在主程序，不在这个无网络容器里。

## 可复现 Demo

保持原始 Demo 的 Bug。先看失败：

```bash
cd examples/demo_repo
python -m pytest -q    # 预期 1 failed
cd ../..
```

**先复制 Demo，以免修改交付的基线：**

```bash
cp -R examples/demo_repo /tmp/repopilot-demo
cd /tmp/repopilot-demo
git init && git add . && git -c user.email=demo@example.invalid -c user.name=Demo commit -m baseline
cd -
python -m repopilot.cli run /tmp/repopilot-demo "修复重复邮箱注册失败的问题" --fake-demo --executor local --approval auto
```

Windows 请把复制路径换成自己的临时文件夹并执行 `git init/add/commit`。`--fake-demo` 是专为这一个已知 Bug 编写的固定动作序列，只证明 harness 的工作流；它**没有**证明真实模型能自主找到修复。真实模型去掉 `--fake-demo`，默认保留 `--executor docker --approval ask`。`--approval auto` 和本地执行仅在可信副本上使用。

运行旧版单任务 sanity test：

```bash
python eval/run_eval.py
```

更有意义的评测使用 25 任务 Mini Benchmark：

```bash
# 无 Key：验证评测器本身，25 个任务都必须通过
python eval/run_benchmark.py --fake --runs 1 --require-all
python eval/run_one_shot.py --fake --runs 1 --require-all

# 配置真实 OpenAI-compatible 模型后
python eval/run_benchmark.py --runs 1
```

当前包含 25 个 Python Bug 任务，涵盖单文件修复和共享 helper、跨模块任务。每个任务先确认原始测试失败；Agent 结束后恢复受保护测试，再注入 Agent 运行时未放入任务工作区的 hidden regression tests 进行独立复测。评测结果记录 steps、tool calls、token usage、duration、changed files 和失败类别。另有同模型 one-shot 对照；这仍是项目自建的小型任务集，不能外推到真实大型仓库。

2026-09-29 的首批 5 题 GitHub Actions Qwen3.8-Max 实测（每任务 1 次）：**5/5 首轮 resolved**；中位数 3 个 Agent steps、4 次工具调用、3554 tokens、27.205 秒。这个数字只描述当时 5 个小型任务，不能外推为通用软件修复成功率，也不是 SWE-bench 成绩。详细方法和结果见 [docs/13-真实模型Benchmark.md](docs/13-真实模型Benchmark.md)。

之后扩至 25 任务并加入 one-shot 对照。旧配置的两轮 25 题中，one-shot 各有 4 次模型超时；调整推理力度与流式传输后，[四题定向复测](https://github.com/Astrea-296111/RepoPilot/actions/runs/36568828589) 得到 Agent 3/4、Top-K one-shot 0/4；但[完整公开 Python 上下文复测](https://github.com/Astrea-296111/RepoPilot/actions/runs/36572978243)让 one-shot 达到 4/4，[导入图补全五题](https://github.com/Astrea-296111/RepoPilot/actions/runs/36574356369)得到 5/5。采用导入图的[Agent 五题复测](https://github.com/Astrea-296111/RepoPilot/actions/runs/36575414927)也是 5/5，但两题曾改公开测试（评分前恢复，严格无测试改动口径为 3/5）。每题只跑一次，原始四题不能证明 Agent Loop 优于单次调用；详见 [评测方法与限制](docs/13-真实模型Benchmark.md)。

## 目录结构

```text
repopilot/
  agent/       state.py, planner.py, agent.py, prompts.py
  context/     repo_map.py, retrieval.py, manager.py
  tools/       base.py, filesystem.py, search.py, shell.py, git.py
  llm/         base.py, openai_compatible.py
  sandbox/     docker.py
  session/     store.py
  api/         server.py
  cli.py       config.py
examples/demo_repo/  benchmarks/repos/  tests/  eval/  docs/
Dockerfile  Dockerfile.sandbox  docker-compose.yml
```

## 关键设计和取舍

- Repo Map 是目录和符号的缩略图，需要细节再 `read_file`，避免整个仓库占满上下文。默认最多扫描 4000 个文本文件，每个文件不超过 512 KB；超大仓库需增量索引。
- 检索为可解释的简单加权规则，不含 embedding；中文词表只覆盖少量 Demo 词。后续可加入 BM25 + 向量 + AST 关系。
- `apply_patch` 精确匹配一处旧文本，写前校验目录边界；新文件只能用 `write_file` 创建。不会自动覆盖大文件。
- 会话每步存到目标仓库的 `.repopilot/sessions`，`repopilot sessions REPO`、`repopilot show ID --repo REPO` 查看，`repopilot resume ID --repo REPO` 用真实模型继续未完成会话；恢复时 `executor/approval` 必须与原会话一致，终止前的工具不重放。API 的任务 ID 查找只在进程内，服务重启后用 CLI 查历史。
- `git_diff` 显示已跟踪文件的 staged/unstaged diff，未跟踪文件只列文件名；请在 Git 仓库中使用。

## 安全说明

默认 `ask` 对写文件和运行命令逐次确认；`never` 禁止这些操作；`auto` **仅对可信代码仓库**。文件工具限制路径和大小，但 `run_command` 本身能访问执行器允许访问的资源。本地执行器会以当前用户身份运行模型选出的 shell 命令，风险最高。Docker 也不是完美安全沙箱：宿主 Docker daemon、内核、可写挂载、镜像供应链和宿主 UID 都是边界；不要把 Docker socket 挂给不可信服务。超时会尝试移除容器；恶意代码仍可能伤害挂载仓库。先备份并用 Git 检查 diff。

REST API 无用户系统和认证，只绑定本机/私有网络；`REPOPILOT_API_ROOT` 限制可选仓库，API 默认 `approval=never`，请求 `auto` 才能修改。`executor=local` 还需服务端显式设置 `REPOPILOT_API_ALLOW_LOCAL=1`。Compose 使用容器内 local 执行器（必须请求 `executor=local`）；不包含宿主 Docker socket。服务容器仍持有模型 Key，且本地命令与服务共享容器；只接收可信请求。命令子进程只继承少量基本环境变量，不代表能抵御同容器恶意代码。

## Docker 部署和 API

```bash
cp -R examples/demo_repo workspaces/demo_repo
git -C workspaces/demo_repo init
git -C workspaces/demo_repo add .
git -C workspaces/demo_repo -c user.email=demo@example.invalid -c user.name=Demo commit -m baseline
# Linux: 将 .env 的 REPOPILOT_HOST_UID / REPOPILOT_HOST_GID 改成 id -u / id -g 的值
docker compose build
docker compose up -d
curl http://127.0.0.1:8000/health
```

服务镜像与 CLI 的沙箱镜像是两个不同镜像。Compose 只挂载 `workspaces/` 的仓库副本到 API 容器，不挂载项目 `.env` 文件或 Docker socket；示例请求（配置密钥后，从宿主访问；路径是**容器内路径**）：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks -H 'Content-Type: application/json' \
  -d '{"repo_path":"/workspace/repos/demo_repo","task":"修复重复邮箱错误","executor":"local","approval":"auto"}'
curl http://127.0.0.1:8000/api/tasks/TASK_ID
```

这会修改 `workspaces/demo_repo` 副本。Compose 的容器内 local 模式不是 `DockerExecutor`，隔离粒度为整个 API 容器。API 默认 DockerExecutor 适用于直接在已安装 Docker 的宿主运行 API。不要将这个无认证接口暴露公网。主机卷写权限需匹配容器用户 UID/GID（在 `.env` 设置 `REPOPILOT_HOST_UID/GID`）。

## 测试

```bash
python -m pytest -q
python eval/run_eval.py
python eval/run_benchmark.py --fake --runs 1 --require-all
```

`docs/07-项目完整执行流程.md` 有本次真实日志和限制，`BUILD_REPORT.md` 有构建自检。

## GitHub Actions 实测

在仓库 **Settings → Secrets and variables → Actions** 新建 repository secret `DASHSCOPE_API_KEY`。打开 **Actions → Windows evaluation → Run workflow**；先保持 `run_real_model=false` 运行无密钥测试，再选择 `true` 和 Key 所属地域运行 Qwen3.8-Max。`task_ids` 留空运行 25 题，或填写逗号分隔的任务 ID 定向复测。真实模型会消耗 API 额度。普通 push 只跑项目测试和脚本化 25 任务 benchmark；手动开启真实模型，或提交信息显式包含 `[qwen-eval]`，才会运行付费 Qwen benchmark。详情见 [`docs/12-GitHub-Actions实测.md`](docs/12-GitHub-Actions实测.md)。

为检验 Top-K 文件缺失是否影响 one-shot，可选 `oneshot_context=graph`（Top-K 与直接导入的本地文件）或 `full`（该题公开 Python 文件全文），并取消 `run_agent` 仅运行这一组；Agent 单独复测则取消 `run_oneshot`。报告记录实际输入文件与字符数。`python eval/measure_retrieval.py` 可离线评估已知修复文件的召回。多个 shard 的结果用 `eval/merge_shards.py` 校验并合并，再运行 `eval/compare_results.py`，脚本会拒绝缺失配对任务或模型配置不一致的报告。

面试项目讲述、数字的严格含义和后续优先级见 [`docs/14-秋招项目讲述与量化.md`](docs/14-秋招项目讲述与量化.md)。

## Roadmap

在相同模型配置下做每题多次重复运行，并合并 shard 做配对比较与 ablation；接入少量外部任务作为 smoke tests；BM25/Embedding 混合召回；更好的命令允许列表和审计；增量索引；容器可写区隔离及更严格资源/网络权限；认证和持久化 API 索引。

## 开源参考与 Attribution

借鉴 `rasbt/mini-coding-agent` 的最小循环、`SWE-agent/mini-swe-agent` 的 issue→环境观察→重试思路、`Aider` 的 repository map 思路。项目核心代码独立编写，未复制它们的实现；详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。可学习的顺序从 [`docs/00-项目总览.md`](docs/00-项目总览.md) 开始。

- [外部历史 Bug 评测：10 个真实 Bug / 3 个项目 / 3 次重复](docs/15-外部历史Bug评测协议.md)
