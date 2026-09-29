# 05｜Context Engineering：有限桌面放哪些纸

假设考试桌面只能放十张纸。题目、解题计划、参考目录、最近的错误截图、之前做过的尝试，哪张纸放上去？模型的 **Context Window** 也是有限的桌面：传入的文字越多，费用和注意力负担越大，还可能超过上限。

在 `repopilot/context/manager.py:ContextManager.build`，每轮拼：

```text
必须：User Task + Plan + step/test_status/changed_files
优先：最近 4 次工具观察（每条截断）
其次：更早操作的规则摘要（最多 15 条）
然后：Top-3 相关文件的开头
最后：Repo Map 的剩余空间
```

**Truncation（截断）**：测试一次可能吐出五万字符。`repopilot/tools/shell.py:bounded_output` 总输出限长，保留头、尾与含 `error/failed/traceback/exception` 的行；只留尾部容易漏掉最早的栈信息。规则不懂复杂日志格式，重要信息仍可能被剪掉。

**Recent window（近期窗口）**：最新 4 次观察写得相对完整，因为它们往往解释眼前失败。**Summary（历史摘要）**：更早只留「哪个工具、参数概略、成功还是失败」，而不是整段旧日志。比如从「已确认注册函数在 app/users.py；测试期待 DuplicateEmailError；上次返回 ValueError」这三个事实继续，不必反复输入整份测试栈。

**Budget（预算）**：`MAX_CONTEXT_CHARS` 默认 30000，是真实字符数，不是准确 token 数。优先保留任务与近期观察，地图放后面；预算不足则截断低优先级内容。高优先级条目自身也可能被剪短，所以真实大任务应升级为更谨慎的分段摘要和模型 tokenizer。

**Relevant context（相关上下文）**：检索只挑有希望的文件片段，模型需要细节时再 `read_file`。如果检索错了，可用 `search_code` 在循环中继续找；初始候选只是线索，并非唯一可访问文件。测试 `test_context_budget_keeps_recent_observation` 验证超长地图下仍保留任务与最近失败。

### 这一章你面试时应该能说什么

「我把上下文当作固定容量的工作桌面。任务、计划、最近失败优先，旧历史压缩，地图和相关代码按预算截断。实现用字符近似，不假装有精准 token 管理。」

### 可能的追问

1. 只保留最近几轮会丢什么？
2. 测试输出特别长时保留哪些部分？
3. 字符预算和 token 预算有什么差别？
4. 检索错了能在循环中纠正吗？

