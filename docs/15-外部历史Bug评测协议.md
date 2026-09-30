# 外部历史 Bug 评测协议（运行前固定）

## 范围与来源

在 boltons、more-itertools、python-slugify 三个此前未用于开发的项目中，选择 10 个已被上游修复的真实历史 Bug。固定父提交源码、修复提交与来源 URL（`eval/external/provenance.json`）。快照保留完整目标模块及直接包内导入，保留许可证；不包含完整上游仓库。公开复现与独立边界回归用例先固定，再调用真实模型。隐藏用例是评测器编写的行为测试，不等同于完整上游测试集。

这些历史提交公开可查，可能存在模型训练数据污染，不能声称无污染私有留出集。来源规模是 3 个项目、10 个独立 Bug，重复不能扩大为 30 个独立 Bug。

## 对照配置

Qwen3.8-Max，北京 DashScope，medium reasoning，stream=true，180 秒请求超时。同一任务各重复 3 次，Agent 与单次补丁基线各 30 次，共 60 次。Agent 最大 15 步，上下文上限 30,000 字符。仅连接失败、429/服务端错误可做最多一次传输重试；模型行为失败不重跑择优。

两者使用同一任务、公开失败输出、AST repo map、import graph 文件检索和公开符号片段。大模块采用根据任务符号自动选取 AST 函数/类实现的片段，不使用参考修复位置。Agent 后续可读文件、搜代码、运行测试并多轮修补；one-shot 只能调用一次模型、应用最多 5 个精确补丁，然后交给同一评分器。

## 隔离与评分

- 每次试验创建独立临时 checkout。Agent 命令仅在 Docker 中执行，只挂载当前任务，不挂载项目主目录、隐藏用例或参考修复。
- 关闭容器网络；只读根文件系统；限制 CPU、内存、进程，删除 capabilities；模型 API key 仅留在宿主模型调用进程，不传入容器。
- 文件工具拒绝修改 tests。容器将 tests、Git 和会话目录作为只读子挂载。保存拒绝行为和完整轨迹。
- 评分另建干净 checkout，仅复制允许包目录内的 Python 源码改动，然后加入固定隐藏测试。模型测试/配置改动不进入评分目录；越界改动直接判无效。
- resolved 要求公开与隐藏测试均通过、没有不允许的文件改动。参考修复必须使原本失败的公开用例和全部隐藏用例通过，否则停止模型试验。
- 这是针对正常修复行为的工程防护，尚未完成恶意代码沙箱攻防评测。

## 记录与统计

保存 suite SHA256、模型配置、每次通过情况、步骤、工具、tokens、diff、失败类型、逐步日志。端到端耗时统一从临时目录准备开始，到公开复现、模型修复、干净 checkout 隐藏评分结束。修复阶段耗时另列；不将基线模型耗时与 Agent 总耗时混用。

按任务报告 0/3 至 3/3，不挑选成功试验。总体率按 30 次报告，但不当成 30 个独立样本；成功率差的参考区间按 10 个任务做 cluster bootstrap。仅 10 个独立任务，区间不用于声称行业统计显著性。

运行前冻结此协议、任务及评分器；本轮结果出来前不针对任务调提示词。后续若基于失败轨迹修复，需标记开发集并再选择新任务留出评测。

## 运行

GitHub Actions → External historical bug evaluation → Run workflow。复用仓库的 DASHSCOPE_API_KEY。该工作流固定 60 次真实请求试验并产生付费 tokens。普通 push 不会调用模型；包含 `[external-eval]` 的提交会自动触发这一轮。

本机仅验证可信参考修复：

```bash
pip install -e '.[dev]' text-unidecode
python eval/run_external.py --mode reference --local-reference
```

真实模型命令必须安装 Docker：

```bash
docker build -t repopilot-external:fixed -f eval/Dockerfile.external .
export REPOPILOT_DOCKER_IMAGE=repopilot-external:fixed
python eval/run_external.py --mode agent --runs 3 --shard 0 --shards 5
```
