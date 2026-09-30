# 02｜从零理解 Agent Loop

只调用一次 LLM 像医生没看化验单就下结论。修 Bug 要先看代码，再看失败，再检查改动，所以 `repopilot/agent/agent.py:RepoPilot._run_custom` 里有 `while state.current_step < self.settings.max_steps`。这不是为了让模型「想得更久」，而是允许它每得到一个新事实就调整下一步。

按源码读：

1. `build_repo_map` 与 `retrieve` 先给仓库一张地图和候选文件；`plan_task` 产出目标、步骤和测试命令。已有会话的计划不会再次生成。
2. `ContextManager.build` 组合任务、计划、近期观察、旧动作摘要、相关代码和缩略地图，并限制字符数。
3. `_action` 调模型、用 Pydantic 检验 JSON。第一次不合法再要求重写一次；第二次仍不合法就报错。
4. `current_step += 1`：每个模型决定算一步。若是 tool，计算工具名+参数的指纹，第 2 次连续重复送入结构化反馈，成功只读观察可复用；第 3 次要求转向并避免重放命令或写入，第 4 次硬停止。`_execute` 做审批、执行、记录输出和耗时。
5. 若是 final，或当前 revision 的计划测试真实通过后模型再次请求同一命令，**程序**按计划独立再跑一次测试。通过才取 Git Diff 并设 `completed`；失败会记录 Observation，回到循环继续修。
6. 每步 `SessionStore.save` 原子写 JSON。步数耗尽标记 `max_steps`；异常标记失败和原因。

```text
while 还有步数:
    上下文 = 任务 + 计划 + 最近观察 + 摘要 + 相关代码
    动作 = 检验(LLM(上下文))
    如果动作是工具: 审批 → 执行 → 记录观察
    如果动作是最终答复: 复验测试 → 通过就结束，否则继续
```

为什么会死循环？比如模型每次只看见「测试失败」，连续三轮重跑同一个命令，没有改变任何文件。`fingerprint` 对工具名和参数排序后编码，第二次开始提供实际进入下一轮 prompt 的 Runtime feedback，第三次要求改变策略，第四次触发停止。成功只读缓存只在同一 invocation 和工作区 revision 内有效；写入、其他 shell 命令或跨进程 resume 会使已有测试证据失效。它只防最简单的重复；轮换两种命令、改无关参数等更复杂循环尚未识别。

`max_steps` 则是总闸门：即使所有工具调用都不同，也不能无限花钱、一直改文件。工具失败也会写进观察；测试失败不是 Python 异常，而是带退出码的可解释结果。读取 `tests/test_core.py::test_agent_loop_detection` 和 `test_agent_loop_demo_end_to_end`，你能看到这两条路实际被测试。

### 这一章你面试时应该能说什么

「核心是有上限的 while 循环。每轮由模型选择一个动作，程序执行后把结果回填；final 还会做程序侧测试复验。重复动作先反馈和有界转向，连续第四次停止，max_steps 再限制总轮数。两种 runtime 共用这一规则。」

### 可能的追问

1. 为什么不能只调用一次模型？
2. 什么动作算一步？最终验证占不占步？
3. 模型一再重跑同一失败测试会怎样？
4. 如果模型交 final 但测试失败会怎样？
5. 当前 loop detection 漏掉哪种循环？


LangGraph 将这些 transition 分别实现为节点与条件边，而不是一个节点包住 while。映射、checkpoint 边界和验收见 [本轮报告](18-runtime-mcp-observability-refactor.md)。
