# Bangumi Android：VS Code 容器开发

## 宿主准备

- 支持 Linux amd64 普通 Git clone 和 Android 11+ ARM64 真机；手机与电脑须网络互通。不支持 Rootless Docker、Docker Desktop 或 iOS 原生构建。
- 安装 [VS Code](<https://code.visualstudio.com/>)、Dev Containers 扩展（`ms-vscode-remote.remote-containers`）、Git，以及 [Docker Engine、Buildx 和 Compose](<https://docs.docker.com/engine/install/ubuntu/>)。
- 启动 VS Code 的普通用户必须能访问 Docker。加入 docker 组相当于授予 root 级权限，参见 [Docker 安全说明](<https://docs.docker.com/engine/install/linux-postinstall/>)；权限变化后重新登录。不要使用 `sudo code`、修改 socket 权限或开放 Docker TCP API。
- 首次下载及原生构建建议预留 30 GiB 以上空间。不要为重试默认清理缓存或卷；依赖无 Yarn lock，传递依赖不保证完全可复现。

> [!NOTE]
> 如果 `docker build` 拉取基础镜像或下载工具链时超时，建议在 Ubuntu 宿主使用可信的 TUN 等透明代理，并确认 Docker 守护进程与 BuildKit 构建步骤的流量都能经过代理。只在浏览器或 VS Code 中设置代理，不一定覆盖镜像构建。

## 打开项目

在普通用户终端克隆仓库并运行 VS Code，或打开已有普通 clone：

```bash
git clone --branch '<分支>' '<仓库地址>' bangumi
cd bangumi
code .
```

在 VS Code 信任自己的仓库，选择 **Dev Containers: Reopen in Container**。宿主初始化使用 Docker 层缓存构建本地镜像，并将宿主 UID/GID 写入镜像的开发用户；Compose 直接使用镜像配置。容器把真实仓库读写挂载到 `/repo`。首次创建时 VS Code 自动运行并等待 `bangumi init`；普通重开不会重复安装。

如果手动在宿主启动，先运行 `bash docker/devcontainer-host.sh`，再运行 `docker compose -f docker/compose.yml run --rm --entrypoint bash dev`。

**初始化会修改宿主真实仓库。** 容器在 `/repo` 必要时运行 `node packages/env.js android`：切换根 [package.json](<../package.json>)、[app.json](<../app.json>)、[babel.config.js](<../babel.config.js>) 和 `patches/` 等配置，iOS 清单备份到 [packages/ios/package.json](<../packages/ios/package.json>)，`node_modules` 可能移动。随后执行 `yarn install --no-lockfile --non-interactive` 并应用补丁，再从 [gradle_yours.properties](<../android/gradle_yours.properties>) 补齐缺失的 Gradle 配置，只调整 JDK 17 不兼容的参数并注释发布签名。已有 Gradle 配置不会重写。

首次初始化失败时，修复错误后在容器终端执行 `bangumi init`；普通重开不会重试。环境切换中断后，先核对根配置和平台依赖再重试。

提交需要默认 iOS 配置的业务变更前，先停止 Metro、构建等占用依赖的任务，再由用户按仓库流程切回 iOS 并检查差异。修改根清单、补丁或 ESLint 插件后，容器内重跑 `bangumi init`；修改 [Dockerfile](<Dockerfile>) 或镜像内运行脚本后，在 VS Code 重建容器。

## 连接手机

以下命令均在 VS Code 容器终端执行。bridge 网络不依赖 mDNS 自动发现，请使用手机显示的地址配对、连接。可先执行 `bangumi build`，避免配对后等待首次编译。

1. 在手机开发者选项启用无线调试，选择“使用配对码配对设备”。
2. 执行 `adb pair 手机IP:配对端口`，在终端交互输入配对码；不要将配对码写入参数、日志或聊天。
3. 返回无线调试主界面，使用其**连接端口**执行 `adb connect 手机IP:连接端口`。
4. 在一个容器终端执行 `bangumi metro`，保持 Metro 在前台运行。另一个容器终端执行 `bangumi start`，构建、安装、设置 adb reverse 并启动开发包。多设备时用 `bangumi start --device '完整序列号'`；序列号可能包含空格。
5. 如果 App 保留了其他调试地址，在手机开发菜单 **Change Bundle Location** 里改成 `127.0.0.1:8081`，然后 **Reload**。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `bangumi init` | 切换 Android 环境、安装依赖、补齐 Gradle 配置 |
| `bangumi start [IP:PORT\|--device SERIAL]` | 构建、安装并启动所选设备 |
| `bangumi build` | 编译 Rust/ECH 和 Android debug APK |
| `bangumi metro` | 前台运行 Metro，不生成原生构建配置 |

OpenSSL 源码在构建镜像时下载解压。`bangumi build` 按 OpenSSL 和 Rust NDK 版本分开存放构建目录，由 `make` 增量编译，然后构建 Rust/ECH；`bangumi init` 不编译原生库。

`bangumi start` 在设备唯一时可省略 `--device`；多设备必须显式选择或设置 `ANDROID_SERIAL`。只改 JS/TS 时保留 Metro 即可热更新；停止 Metro 时在前台按 Ctrl+C。关闭 VS Code 时容器停止，仓库和命名卷保留。

容器直接使用 Android SDK 的 `adb`，Server 按需启动；不要用 `adb -a`。排查设备用 `adb devices -l`，查看日志用 `adb -s '序列号' logcat`。仅安装已有 APK 可用 `adb -s '序列号' install -r android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk`。

## 排障与安全

- 设备连不上：检查容器能否访问手机显示的地址及端口。容器重开或手机更换连接端口后，用 `adb connect` 重连；配对身份保留在命名卷中。
- 8081 被占用：停止占用端口的进程，再前台启动 Metro。
- 构建使用容器环境中的 SDK 和 CMake 路径。若提示缺少 Gradle 配置，先运行 `bangumi init`。
- 下载或磁盘失败：检查网络和空间，保留错误现场；不要关闭 TLS、刷新锁文件或默认清缓存。
- Compose 使用独立 bridge 网络，不发布端口。ADB 仅监听回环 5037；Metro 用 `yarn expo start --localhost --port 8081` 启动，实际监听地址由 Expo 决定。手机仍通过所选设备的 adb reverse 访问 Metro。不启用 privileged、USB 或宿主 Docker socket 挂载。
- 完整仓库及其未跟踪或忽略的敏感文件对容器和可信扩展可见；不要假设编辑器不会按个人设置共享凭据。
- Gradle、Cargo、Yarn 缓存及容器 ADB 身份使用命名卷；项目依赖与原生/Metro 缓存位于真实仓库。不要自动删除已有数据。

历史验证与待验收范围见 [VERIFICATION.md](<VERIFICATION.md>)。
