# 06｜Docker Sandbox：给命令画一道边界

为什么命令危险？`run_command` 接受模型选出的 shell 字符串；如果模型误选 `rm -rf ...`，本地执行器会按当前用户身份运行。即使没有恶意，测试也可能写坏数据库、启动服务或无限占用资源。默认让命令走 Docker，先把它关进一个只看得到挂载仓库的临时房间。

```text
Host（RepoPilot、模型 Key、Docker daemon）
  │ docker run（不传 Key，禁网，限 CPU/内存/进程）
  v
Container（只读根文件系统 + 临时 /tmp）
  │ 可写挂载 /workspace
  v
Target Repo（pytest / python / shell）
```

`repopilot/sandbox/docker.py:DockerExecutor.run` 采用 `--network none`、`--cap-drop ALL`、`no-new-privileges`、内存/CPU/进程数限制，命令限时，超时时尝试强制删除容器。镜像 `Dockerfile.sandbox` 预装 pytest；进入容器运行代码而非进入主程序。宿主机必须先 `docker build -f Dockerfile.sandbox -t repopilot-sandbox:dev .`。容器内没安装的项目依赖需在自定义沙箱镜像中预装，因为命令执行时容器没有网络。

它降低了什么风险？执行环境里默认看不到主程序的环境变量和其他目录，容器网络关闭，耗时与资源有限。但**不是绝对安全**：目标仓库被可写挂载，文件照样可能被删除；宿主 Docker daemon 和内核仍是受信任底座；宿主 UID 为 root 时容器也使用对应 UID；危险镜像和内核漏洞不在本项目防护范围。批准 `auto` 只应针对可信副本。

CLI `--executor local` 是调试选项：它更容易跑已经配置好的虚拟环境，但命令能使用宿主权限。`--approval ask` 每次写/执行先征询用户，和 Docker 解决不同问题：审批决定「是否允许运行」，沙箱限制「允许运行后能接触什么」。Compose 里的 API 自身运行在容器内，示例用 `executor=local` 表示在 API 容器中运行；它不等同于 `DockerExecutor` 的每命令隔离。没有挂载 Docker socket，这是有意避免把宿主 daemon 交给 HTTP 服务。

### 这一章你面试时应该能说什么

「Shell 是风险最高的工具。默认每个命令起一个限资源、禁网、只挂载仓库的 Docker 容器；审批控制是否执行。Docker 不能保护可写的目标仓库，也不能防所有内核或 daemon 风险，所以要在可信副本上运行并审查 diff。」

### 可能的追问

1. `--network none` 会导致什么依赖问题？
2. 为什么容器还要限时、限内存？
3. 为什么不把 Docker socket 挂到 API 容器？
4. Docker 能保证目标仓库不被删吗？
5. 本地执行器适合什么情况？

