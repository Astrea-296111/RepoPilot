# 04｜Tool Calling：模型提议，程序动手

你可以把模型当成写工单的同学：它说「请打开 app/users.py 的前 120 行」，而不是自己绕过操作系统去读文件。程序收到 JSON 工单，检查格式和权限，再把结果交给它。工具统一有 `name`、`description`、`execute(args) -> ToolResult`，契约在 `repopilot/tools/base.py`。

例如：

```json
{"type":"tool","tool":"read_file","arguments":{"path":"app/users.py","start_line":1,"end_line":80},"reason":"确认注册逻辑"}
```

`repopilot/agent/agent.py:parse_action` 用 Pydantic 区分 tool/final，检查工具名、必须字段、额外字段；具体参数由工具自己校验。模型给出坏 JSON，`_action` 会再问一次；再坏就失败而不是无限重试。`_execute` 用工具名查字典，执行后的 `ok/output/exit_code/changed_file` 是 Observation。

工具安全边界：`Workspace.resolve` 把路径解成绝对真实路径，确认仍在仓库内，拒绝 `.git/.repopilot/.env` 和越界符号链接；`ReadFile` 最多 300 行，`SearchCode` 最多 80 条结果；`ApplyPatch` 要求旧文本出现**恰好一次**，用临时文件原子替换，避免误改多处；`WriteFile` 只创建新文件；`GitDiff` 反馈变化。

写文件属于 risky，是因为它能损坏你的工作树；`run_command` 更危险：命令在选定执行器里真正运行。CLI 默认 `ask` 逐条询问。`auto` 适合你信任的实验副本；`never` 会记录拒绝观察。这层审批并不让危险代码变安全：本地 shell 可以做用户权限能做的事；Docker 的可写挂载也能被改动。

### 这一章你面试时应该能说什么

「模型输出一个 JSON 工具调用，Pydantic 校验协议，程序查工具表执行。文件路径先 resolve 再检查仓库边界；写文件和命令必须过 approval，并把 exit code 和输出返回给下一轮。」

### 可能的追问

1. Pydantic 校验哪些内容，工具还要校验哪些内容？
2. 目录遍历 `../../` 和指向仓库外的符号链接怎样防？
3. `apply_patch` 为什么要求旧文本恰好出现一次？
4. `auto` 审批意味着什么风险？

