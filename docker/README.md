# Bangumi Android：VS Code 容器开发

## 宿主准备

- 支持 Linux amd64 普通 Git clone 和 Android 11+ ARM64 真机；手机与电脑须网络互通。不支持 Rootless Docker、Docker Desktop 或 iOS 原生构建。
- 安装 [VS Code](<https://code.visualstudio.com/>)、Dev Containers 扩展（`ms-vscode-remote.remote-containers`）、Git，以及 [Docker Engine、Buildx 和 Compose](<https://docs.docker.com/engine/install/ubuntu/>)。
- 启动 VS Code 的普通用户必须能访问 Docker。加入 docker 组相当于授予 root 级权限，参见 [Docker 安全说明](<https://docs.docker.com/engine/install/linux-postinstall/>)；权限变化后重新登录。不要使用 `sudo code`、修改 socket 权限或开放 Docker TCP API。
- 首次下载及原生构建建议预留 30 GiB 以上空间。不要为重试默认清理缓存或卷；依赖无 Yarn lock，传递依赖不保证完全可复现。

## 打开项目

在普通用户终端克隆仓库并运行 VS Code，或打开已有普通 clone：

```bash
git clone --branch '<分支>' '<仓库地址>' bangumi
cd bangumi
code .
```

在 VS Code 信任自己的仓库，选择 **Dev Containers: Reopen in Container**。宿主初始化使用 Docker 层缓存构建本地镜像，单个容器把真实仓库读写挂载到 `/repo`。首次创建时 VS Code 自动运行并等待 `bangumi init`；普通重开不会重复安装。

**初始化会修改宿主真实仓库。** 容器在 `/repo` 运行现有 `node packages/env.js android`：切换根 [package.json](<../package.json>)、[app.json](<../app.json>)、[babel.config.js](<../babel.config.js>) 和 `patches/` 等配置，iOS 清单备份到 [packages/ios/package.json](<../packages/ios/package.json>)，`node_modules` 可能移动。随后执行 `yarn install --no-lockfile --non-interactive` 并应用补丁；这些变化不是临时副本，也不会自动切回或提交。

首次初始化失败时，修复错误后在容器终端执行 `bangumi init`；普通重开不会重试。旧 Android 依赖标记会被识别，避免误备份到 `packages/ios`；未知状态或缓存冲突会保留现场并报错。环境切换中断时先检查根配置和平台缓存，再处理 `docker/.generated/android-switch.pending`，不要盲目重放。

提交需要默认 iOS 配置的业务变更前，先停止 Metro、构建等占用依赖的任务，再由用户按仓库流程切回 iOS 并检查差异。修改根清单、补丁或 ESLint 插件后，容器内重跑 `bangumi init`；修改 [Dockerfile](<Dockerfile>) 或镜像内运行脚本后，在 VS Code 重建容器。

## 连接手机

以下命令均在 VS Code 容器终端执行。bridge 网络不依赖 mDNS 自动发现，请使用手机显示的地址配对、连接。可先执行 `bangumi build`，避免配对后等待首次编译。

1. 在手机开发者选项启用无线调试，选择“使用配对码配对设备”。
2. 执行 `adb pair 手机IP:配对端口`，在终端交互输入配对码；不要将配对码写入参数、日志或聊天。
3. 返回无线调试主界面，使用其**连接端口**执行 `adb connect 手机IP:连接端口`。
4. 保持手机解锁、亮屏，执行 `bangumi start`。它会构建、安装、配置调试地址和 adb reverse 并启动开发包；启动后保持应用前台以观察热更新。多设备时使用 `bangumi start --device '完整序列号'`；序列号可能包含空格。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `bangumi init` | 初始化 Android 环境与依赖 |
| `bangumi start [IP:PORT\|--device SERIAL]` | 构建、安装并启动所选设备 |
| `bangumi build` | 编译 Rust/ECH 和 Android debug APK，生成原生构建配置 |
| `bangumi metro` | 前台运行 Metro，不生成原生构建配置 |
| `bangumi down` | 仅停止 `start` 启动的后台 Metro |

`bangumi start` 在设备唯一时可省略 `--device`；多设备必须显式选择或设置 `ANDROID_SERIAL`。只改 JS/TS 时保留 Metro 即可热更新。关闭 VS Code 时容器停止，仓库和命名卷保留。

容器里的 `adb` 由[包装器](<adb.sh>)固定在本地端口，ADB Server 由官方工具按需启动。排查设备用 `adb devices -l`，查看日志用 `adb -s '序列号' logcat`。仅安装已有 APK 可用 `adb -s '序列号' install -r android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk`。

## 排障与安全

- 设备连不上：检查容器能否访问手机显示的地址及端口。容器重开或手机更换连接端口后，用 `adb connect` 重连；配对身份保留在命名卷中。
- 8081 被占用：检查容器内的占用进程和所选设备 reverse；脚本不会接管或杀死其他 Metro。
- 下载或磁盘失败：检查网络和空间，保留错误现场；不要关闭 TLS、刷新锁文件或默认清缓存。已有手写 Gradle 配置由用户确认处理。
- Compose 使用独立 bridge 网络，ADB 和 Metro 分别使用容器内的回环 5037 与 8081，不和宿主端口冲突。手机通过所选设备的 adb reverse 访问 Metro，无需发布端口。不启用 privileged、USB 或宿主 Docker socket 挂载。
- 仅操作开发包的私有调试偏好，不卸载、清数据或修改手机全局设置。完整仓库及其未跟踪或忽略的敏感文件对容器和可信扩展可见；不要假设编辑器不会按个人设置共享凭据。
- Gradle、Cargo、Yarn 缓存及容器 ADB 身份使用命名卷；项目依赖与原生/Metro 缓存位于真实仓库。不要自动删除已有数据。

历史验证与待验收范围见 [VERIFICATION.md](<VERIFICATION.md>)。
