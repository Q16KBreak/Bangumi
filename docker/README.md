# Bangumi Android：VS Code 单容器开发

```text
VS Code → devcontainer-host.sh → 镜像 + Compose 配置
        → entrypoint.sh workbench → 容器 ADB Server
        → postStart: bangumi init → develop.sh → prepare-workspace.cjs

bangumi build → entrypoint.sh → build-rust.sh → Gradle
bangumi up/metro → entrypoint.sh → start-metro.cjs
bangumi start → 构建/安装 + 调试偏好 + adb reverse + 启动开发包
```

## 1. 准备 Ubuntu 宿主

- 支持 Linux **amd64**、普通 Git clone、Android **11+ ARM64 真机**。不支持 Rootless Docker、Docker Desktop、Windows/macOS 宿主、iOS 原生编译或正式签名包；无线调试需手机与电脑网络互通。
- 安装 [VS Code](<https://code.visualstudio.com/>) 和 Dev Containers 扩展（`ms-vscode-remote.remote-containers`）、Git，按 [Docker 官方 Ubuntu 安装文档](<https://docs.docker.com/engine/install/ubuntu/>)安装 Docker Engine、Buildx 和 Compose 插件。基础 `bash`、`coreutils` 等由 Ubuntu 提供。
- VS Code **当前用户必须能直接访问 Docker**。按自身安全要求配置已有权限；加入 `docker` 组相当于授予 **root 级权限**，可参考[官方说明](<https://docs.docker.com/engine/install/linux-postinstall/>)。权限变化后重新登录使 VS Code 进程继承；不要 `sudo code`、修改 Docker socket 权限或开放 Docker TCP API。
- 首次镜像、依赖和原生构建需要下载数 GB，建议预留 **30 GiB 以上**磁盘空间；这是建议而非保证。依赖无 Yarn lock，传递依赖不保证完全可复现。不要为重试默认删除卷、全局 prune 或使用 `--no-cache`。

## 2. 获取代码并打开容器

在宿主普通用户终端执行（替换完整占位符）：

```bash
git clone --branch '<包含本方案的分支>' '<仓库地址>' bangumi
cd bangumi
code .
```

在 VS Code 确认信任自己的仓库，按 **Ctrl+Shift+P** 选择 **Dev Containers: Reopen in Container**。首次需要等待，保持窗口打开：


## 3. 连接新手机

以下命令都在 **VS Code 容器终端**执行。建议先运行 `bangumi build` 完成长时间原生编译，再操作手机。

1. 手机与 Ubuntu 网络互通；在手机的开发者选项中开启**无线调试**，选择“使用配对码配对设备”。
2. 屏幕显示配对 IP 和**配对端口**后，在容器终端执行：

   ```bash
   bangumi pair <ip>:<port>
   ```

   在终端交互输入配对码。
3. 返回无线调试主界面，查看另一个**连接端口**，执行：

   ```bash
   bangumi connect <ip>:<port>
   ```

4. 保持手机解锁、亮屏，执行：

   ```bash
   bangumi start [--device <ip>:<port>]
   ```

## 4. 日常开发

| 容器终端命令 | 作用 |
| --- | --- |
| `bangumi init` | 初始化/复用 Android 依赖和运行配置 |
| `bangumi build` | 编译 Rust/ECH 和 debug APK，不要求手机 |
| `bangumi up` | 在后台启动并等待本项目 Metro |
| `bangumi metro` | 前台运行 Metro，退出该前台进程可停止它 |
| `bangumi devices` | 列出设备和 mDNS 发现 |
| `bangumi start [IP:PORT\|--device SERIAL]` | 编译、安装、reverse、启动所选设备 |
| `bangumi install --device SERIAL` | 安装已有 APK，不清数据 |
| `bangumi logs --device SERIAL` | 查看所选设备日志 |
| `bangumi down` | 仅停止本命令管理的 Metro，不停止容器 |

设备唯一时可以省略 `--device`；多设备必须用 `--device` 或 `ANDROID_SERIAL`。序列号可能带空格，应加引号。`bangumi start` 的显式地址与 `ANDROID_SERIAL` 不得冲突。


关闭 VS Code 时 `shutdownAction: stopCompose` 会停止单一开发容器与其容器 ADB Server；项目文件和命名卷保留。重开容器后可重新连接已配对手机。可选的[宿主兼容入口](<android-debug.sh>)仅转发到容器；正常开发不用切回宿主，也不要求宿主 ADB。



当前工具版本集中在 [Dockerfile](<Dockerfile>)，本轮以隔离项目的实际构建结果选定：

| 工具 | 当前配置与边界 |
| --- | --- |
| Node / Yarn Classic | 26.13.1 / 1.22.22 |
| JDK | 17；JDK 25、21 均在现有 Gradle 8.0.1 配置阶段实际失败 |
| SDK Command-line Tools / ADB | 23.0（16111833）/ 37.0.3 |
| CMake | 3.31.6；4.1.2 实际被旧 Expo 的最低版本声明拒绝，未添加策略绕过 |
| Rust / rustup / cargo-ndk | 1.100.0 / 1.29.3 / 4.1.2 |
| Rust NDK / RN NDK | 30.0.16248370 / 工程固定的 23.1.7779620，二者独立 |
| Build Tools / 编译平台 | 统一使用 30.0.3，只安装这一版；编译平台保持工程 API 34 |


## ADB 安全与宿主模拟器预留

默认 `BANGUMI_ADB_SERVER_MODE=container`，容器管理自己的 ADB Server，使用不带 `-a` 的 `-L tcp:5037`，预期只监听 `127.0.0.1:5037`；客户端继续使用 `tcp:127.0.0.1:5037`。容器专用 `/home/dev/.android` 卷持久化配对身份。网络模式为 host，但不使用端口发布、`privileged` 或 USB 映射。若 5037 已被其他服务占用，容器会报错而不自动替换或杀掉现有服务；由用户判断处理。实际监听及真机连接仍须验收。

宿主模拟器**仅预留后端接口，尚未验收或实现 x86_64 构建**。用户可在宿主预先自行管理兼容的 ADB Server、客户端与模拟器，然后在启动 VS Code 的宿主环境中设置 `BANGUMI_ADB_SERVER_MODE=host` 并重新创建容器；该模式只探测并使用已有回环 server，不自动启动、关闭或替换它。保持宿主和容器 ADB 版本兼容；关闭容器也不停止宿主 server。

当前 `BANGUMI_ANDROID_ABI` 只允许 `arm64-v8a`；Gradle、Rust、OpenSSL 尚不支持 x86_64，**ADB 能看到 x86_64 模拟器不意味着 ARM64 APK 能运行**。Ubuntu 本身运行在 VMware 中时，宿主模拟器还需自行确认嵌套虚拟化与 KVM 可用。


## 排障与维护检查

- **5037 被占用**：先确认已有服务归属；不自动 kill。需共用宿主服务时明确选择 host 模式。
- **设备 offline / unauthorized**：检查无线调试、手机网络、配对端口与连接端口；使用 `bangumi devices`。重新配对时配对码只在交互终端输入。
- **8081 被占用**：确认占用进程；脚本不会接管或杀死其他 Metro。可检查 `http://127.0.0.1:8081/status` 和所选设备 reverse。
- **已有 Gradle 配置**：入口不会覆盖手写配置；用户确认并自行处理后重试。
- **下载或磁盘失败**：保留错误，检查网络和空间；不要关闭 TLS 校验、刷新锁文件或默认清缓存。
