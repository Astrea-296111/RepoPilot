# RepoPilot：项目 STAR、简历与面试讲述

依据 2026-09-30 的实际代码、integration tests 和固定评分。安装、命令、commit、Actions、raw shard、最新模型结果与限制见 [18｜重构验证报告](18-runtime-mcp-observability-refactor.md)。早期实测另见 [17｜历史外部结果](17-外部历史Bug实测结果.md)，不与定向任务分母合并。

## 3 条中文简历 bullet

**RepoPilot｜Coding Agent / Agent Runtime 与评测系统**

Python、FastAPI、Pydantic、LangGraph、MCP、OpenTelemetry、Docker、GitHub Actions、Pytest、AST。

- 设计可解释的 Plan–Act–Observe–Verify Coding Agent，自研有界 runtime，以 Pydantic JSON 协议管理 6 类工具；提供六节点 LangGraph 等价状态机，复用 context、审批、Workspace 与独立测试复验，支持 CLI/API selector 和 JSON 会话恢复，避免维护两套业务策略。
- 将仓库地图、代码搜索、文件读取与 Git diff 封装为 4 个只读 MCP tools，通过官方 client 验证 stdio 调用、越界拒绝和生命周期；以默认关闭的 OpenTelemetry 记录 LLM/tool/verification 的 token、耗时与失败 metadata，完成真实 console、memory 与 OTLP HTTP export 验证。
- 构建 3 个项目、10 个历史 Bug、129 个固定 public/hidden 用例的 Agent / one-shot 重复对照评测；通过轨迹定位重复读取和测试成功后终止失效，落实只读观察复用、结构化转向与最终独立验证，保存所有试验、评分分母和成本，依据实测判断多轮策略取舍。

这三条优先表达机制与验证，避免未经支持的“修复率提升”。FakeLLM 25/25 是链路回归；本轮真实指标须同时引用报告中的 scope、模型、日期、commit、run 和原始数据。写“独立开发”或具体个人职责前，应按自己的实际参与核实。

## 90 秒项目介绍

我做的 RepoPilot 是一个能读 Python 仓库、修改代码并实际跑测试的 Coding Agent。核心问题是让模型决定、真实执行和可验证结果连起来，而不是生成一段看起来正确的补丁。我先用 AST 仓库地图、词法和导入图准备上下文，再用 Pydantic 校验模型的 JSON 动作，由程序执行读、搜、改、测工具；测试失败回到下一轮，结束前独立复验。

我保留了自研循环，同时用 LangGraph 的六个节点和条件边重建相同状态机，两者共用工具、审批、安全策略和会话逻辑。这样可以解释框架抽象对应哪一段代码，而不是把旧循环包进一个节点。对外工具用官方 MCP SDK，只开放四项只读能力；OpenTelemetry 默认关闭，记录 token、耗时和失败 metadata，已经实际验证 stdio client、console 和 OTLP 出口。

评测让我发现更重要的问题：旧轮十个历史 Bug、每方法三次试验中，Agent 补丁通过 25/30，正常结束且通过只有 23/30，one-shot 是 28/30。我据此修复重复动作反馈和测试成功后的终止，同时保留最终独立验证，先固定风险任务回归再做对照。这个项目的价值是能解释状态、执行、评分和代价，也能诚实说明多轮 Agent 的适用边界。

这段约 90 秒，语速因人而异。准备面试时，应将最后一段替换为 [本轮报告](18-runtime-mcp-observability-refactor.md) 的最终同范围结果；不要把旧轮数字直接说成新策略效果。

## Custom Runtime vs LangGraph Runtime 追问表

| 常见追问 | Custom 实际实现 | LangGraph 实际实现 | 回答重点 |
|---|---|---|---|
| 控制流在哪里？ | `_run_custom` while，route 控制 continue / verify | StateGraph 六节点与 conditional edges | 业务 transition 相同，orchestration 不同 |
| 是不是只包一层旧 Agent？ | 循环逐项调用共享方法 | 每 node 调一个共享 transition；测试禁止 `_run_custom` | 用 graph 源码与测试证明真实路由 |
| state 是什么？ | Pydantic AgentState | JSON-compatible GraphState 包含 AgentState snapshot | 图中不序列化 model、tool client 或凭据 |
| 工具怎么执行？ | `_tool_step` + `_execute` | guarded `tool_execute` 节点 | 共用 approval、Workspace、Local/Docker |
| final 如何可信？ | `_verify` 实际跑计划测试 | `verify` node 同一方法，失败返回 decide | success 由环境证据决定，模型不是 grader |
| 重复动作如何恢复？ | 第二次 feedback/cache，第三次 redirect，第四次 stop | 同一 `_tool_step` 策略 | 没有两套阈值或无限放宽预算 |
| checkpoint 能跨进程吗？ | 原子 JSON SessionStore | InMemorySaver 进程内；跨进程 JSON bridge | 不宣称持久数据库或 exactly-once |
| 如何限制循环？ | 默认 max_steps=15 | 同一 decision budget + `3 * max_steps + 10` recursion limit | node 计数与模型决定计数不同 |
| 是否更快、更准？ | Paid benchmark 使用 Custom | 已通过同任务 deterministic/CLI/API/Docker | 没有真实模型同规模 runtime 性能证据，不声称胜出 |
| 为什么不只保留一套？ | 小状态机可直接审计、解释成本低 | 条件边与 checkpoint 的框架抽象可对照 | 共享业务以降低维护成本；复杂工作流再决定主入口 |

## 10 个最可能被追问的问题

### 1. 为什么不直接一次调用 LLM 生成补丁？

一次调用简单且可能更省 token。Agent 的价值在于根据新的文件和测试结果继续查找、修正与复验，但需要付出多轮成本。当前固定任务不能自动证明 Agent 更优，应看 one-shot 对照、失败轨迹和使用场景。源码：[agent.py](../repopilot/agent/agent.py)，指标：[18](18-runtime-mcp-observability-refactor.md)。

### 2. 怎么证明 LangGraph 是真 graph？

`StateGraph(GraphState)` 注册 prepare_repo_context、plan、agent_decide、tool_execute、verify、finalize 六个 node；决策、工具和验证的 route 决定条件边，失败返回 decision。node 只执行一项共享 transition。`test_graph_success_and_custom_semantics` 禁止旧循环运行，仍能完成；另测工具失败、验证失败与预算停止。源码：[runtime/langgraph.py](../repopilot/runtime/langgraph.py)、[测试](../tests/test_langgraph_runtime.py)。

### 3. 会话恢复和 checkpoint 有什么区别？

InMemorySaver 保存 node snapshot，测试在同进程的 tool node 后中断再恢复，不重放已执行工具。JSON SessionStore 是跨进程 bridge，从下一次模型决策继续，并核对 runtime、repo、executor、approval 和 task；已有 passing test evidence 被清除，步骤预算不归零。没有事务保证，崩溃窗口不能承诺工具 exactly-once。

### 4. 重复读取为什么要缓存，什么时候不缓存？

相同成功只读观察，在本次 invocation、相同应用内 revision、相同 fingerprint 下可复用；参数或 revision 变化、工具失败、跨进程 resume 都不复用，复用前仍检查路径。第二次和第三次的反馈进入实际 prompt，第四次硬停止。应用 revision 尚不能识别所有外部并发编辑，所以不能称全面一致缓存。源码：[recovery tests](../tests/test_runtime_recovery.py)。

### 5. 测试通过后为什么还要独立验证？

模型可能误报、之后改文件或实际运行过其他命令。只有当前 revision 的计划测试真正 passed 才有成功证据；再次请求同一测试会进入独立 verify，仍然执行命令，不返回缓存。验证失败回模型；文件修改/非测试命令/resume 使旧证据失效。测试序列明确验证先通过、final 又失败、继续修复的路径。

### 6. 如何避免 Agent 改测试骗过评分？

评测运行期将 public tests 设为文件工具 protected paths、Docker 只读 mounts。评分另建干净副本，恢复公开测试，只接受允许的源码变更，然后注入运行期从未放进 Agent 工作区的 hidden tests。上游已知参考修复必须全通过、破损版本必须失败。hidden 与 runner 同属宿主评分环境，尚不是完整对抗隔离。源码：[run_external.py](../eval/run_external.py)、[Docker tests](../tests/test_docker_integration.py)。

### 7. MCP 为什么只暴露四个只读工具？如何验证？

对外需要标准化仓库观察，开放 shell/write 会扩大默认权限。四工具重用 Workspace、大小和输出限制，Git 禁止 external diff/textconv 并排除私有 diff；readonly annotation 也受检查。官方 Client 实际启动 CLI stdio，list_tools、调用四工具、拒绝越界和私有文件并正常关闭。未声称已接入 Cursor/Claude Code。源码：[MCP integration](../tests/test_mcp_integration.py)。

### 8. OTel 是否会泄密、拖慢或者让任务失败？

默认关闭并 lazy import。启用时只接受明确 scalar allowlist，不记录源码、prompt、密钥、hidden test 或 exception body；独立 provider 不覆盖宿主 global provider。exporter exception 被隔离、flush bounded；memory tests 检查树/token/error/privacy，真实 local HTTP test 解码 OTLP protobuf。只验证这层协议与故障情形，未证明生产高吞吐或 SaaS。源码：[observability.py](../repopilot/observability.py)。

### 9. 你的成功率、token 与耗时如何计算？

patch resolved 是最终干净评分通过；completed+resolved 还要求 Agent 正常结束。外部每方法是 10 bugs ×3 repeats=30 trials，只有 10 个独立 Bug。Token 用 provider usage 累积，端到端耗时来自包含执行/验证的 trial timer；不能混成单次模型 latency。工具 observation 数与实际 dispatch 数分开，定向 4 题不能并入全量 10 题分母。模型 alias 可变化，历史比较仅描述性，不声称显著因果提升。

### 10. 现在最值得继续改什么，为什么不加更多框架或向量库？

优先增加独立 Bug、完整仓库集成和共享行为兼容性对照，并改善非连续/参数漂移的循环识别、外部编辑一致性、命令策略与 API 认证。已有 AST/词法/import 检索要用 recall 和任务指标判断；当前没有 embedding/BM25 的实验支持，不为关键词增加依赖。LangGraph 并不自动改善模型推理，OTel 也不自动提升修复率。

## STAR 讲述骨架

**S：** 补丁看起来正确不等于修复完成，相关实现可能不在最初上下文里，公开复现也可能漏旧行为回归。

**T：** 建立可执行、可解释、可恢复、可核查的修复闭环，并用相同模型 one-shot 判断多轮价值。

**A：** 自研 bounded runtime 与结构化动作；共享 transition 的 LangGraph 对照；只读 MCP；optional OTel；Docker/测试保护/独立评分。根据真实轨迹先复现重复与终止失效，再落实 feedback、只读复用、证据失效和独立验证，按固定 scope 保留全部 raw 结果。

**R：** 基础与完整依赖 CI、官方 MCP stdio、OTLP、真实 Docker 均有验证；脚本化 25 题三个方法全过。真实模型结果按 [18](18-runtime-mcp-observability-refactor.md) 的日期和分母回答，保留仍存在的兼容性失败与成本限制，不将框架采用等同于效果提升。

## 措辞边界

这是单 Agent 的两种 orchestration；没有 Multi-Agent、Langfuse、LangChain 应用链、向量 DB、BM25、Kubernetes 或 SWE-bench 实测。字符预算不是精确 token budget，文件召回不是修复率；Docker 测试不是绝对安全保证；没有业务上线数据，不虚构用户、收入或节省工时。
