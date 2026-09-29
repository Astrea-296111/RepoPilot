# 在 GitHub Actions 运行 RepoPilot

工作流：`.github/workflows/windows-eval.yml`。只支持手动触发，基于 Windows 的 Python 3.12 环境。不会把模型 Key 写入代码或提交，也不会修改仓库中的原始 Demo。真实模型调用会产生阿里云费用。

## 启动

1. 打开仓库 **Settings → Secrets and variables → Actions → New repository secret**，名称填 `DASHSCOPE_API_KEY`，值填阿里云百炼 API Key。Key 所属地域需要与运行时选的地域一致。不要把 Key 发到 Issue、聊天或日志。
2. 打开 **Actions → Windows evaluation → Run workflow**，选择 `main`。
3. 初次验证保留 `run_real_model=false`，点击绿色 **Run workflow**。`Tests and scripted evaluation` 会运行项目测试和无密钥 FakeLLM Demo。
4. 真正测 Qwen3.8-Max 时改为 `run_real_model=true`，选择 `beijing` 或 `singapore`，再点击 **Run workflow**。两个 job 会并行，真实模型的 job 名为 `Qwen3.8-Max on a temporary Demo copy`。

脚本先在系统临时目录复制 `examples/demo_repo` 并初始化 Git，确认原始测试失败，然后让真实模型修复，最后独立复测和检查修改文件。此模式在可信 Demo 副本上使用 `local` 执行器和自动审批；不要把它直接改成针对不受信任的仓库执行。

## 查看结果和排错

打开该次 workflow run：每个步骤的日志显示依赖安装、单测、脚本化测试与真实评测是否成功。真实评测结束后，页面底部 **Artifacts** 中下载 `qwen-diagnostics`，内含 `actions-qwen.json`。即使评测失败，上传步骤仍会尝试保存结果。JSON 记录基线/最终测试、计划、模型回复、每次工具的参数和输出、步骤耗时、Token 用量（若 API 返回）、Git 状态及 Diff；API Key 会按原文替换为 `[REDACTED]`，不包含完整原始会话。

**这是公开仓库：Actions 日志和 Artifact 可被他人看到。** 工作流只运行仓库自带的公开 Demo。不要把私人仓库内容、其他凭据或敏感数据放入任务、Demo 或输出。诊断 Artifact 保留 7 天；需要我帮你排错时，给我 workflow run 的 GitHub 链接，或下载并上传该 JSON。只提供 API Key 不会让我自动看到你本机的运行内容。

如果 Key 缺失，真实 job 会失败并在 JSON 写明 `Missing DASHSCOPE_API_KEY`。401/403 请检查地域、额度、模型访问权限和 Key；连接错误请看运行日志。模型不遵循 JSON 工具协议或修复测试未通过时，查看 `model_calls` 与 `agent.tool_history`。该评测只有一个已知 Demo，不代表真实仓库成功率。
