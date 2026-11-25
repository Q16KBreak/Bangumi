# Bangumi Android：VS Code 单容器开发

**本版已在隔离源码副本通过镜像、工作台/ADB、原生 APK 构建和 Metro 实际打包；正式仓库依赖准备、VS Code 完整重连及新手机冷启动/Fast Refresh 仍待用户验收**。历史双容器或旧手机结果不代表本版真机已验证，见[验收记录](<VERIFICATION.md>)。

目标是宿主只准备 **VS Code + Dev Containers 扩展、Docker Engine + Buildx/Compose、Git**，在一个容器终端内完成无线 ADB、Metro 和 Android 编译；宿主不需要 Node、ADB、JDK、Rust、Android SDK 或项目依赖。

## 1. 准备 Ubuntu 宿主

- 支持 Linux **amd64**、普通 Git clone、Android **11+ ARM64 真机**。不支持 Rootless Docker、Docker Desktop、Windows/macOS 宿主、iOS 原生编译或正式签名包；无线调试需手机与电脑网络互通。
- 安装 [VS Code](<https://code.visualstudio.com/>) 和 Dev Containers 扩展（`ms-vscode-remote.remote-containers`）、Git，按 [Docker 官方 Ubuntu 安装文档](<https://docs.docker.com/engine/install/ubuntu/>)安装 Docker Engine、Buildx 和 Compose 插件。基础 `bash`、`coreutils` 等由 Ubuntu 提供。
- VS Code **当前用户必须能直接访问 Docker**。按自身安全要求配置已有权限；加入 `docker` 组相当于授予 **root 级权限**，可参考[官方说明](<https://docs.docker.com/engine/install/linux-postinstall/>)。权限变化后重新登录使 VS Code 进程继承；不要 `sudo code`、修改 Docker socket 权限或开放 Docker TCP API。
- 首次镜像、依赖和原生构建需要下载数 GB，建议预留 **30 GiB 以上**磁盘空间；这是建议而非保证。依赖无 Yarn lock，传递依赖不保证完全可复现。不要为重试默认删除卷、全局 prune 或使用 `--no-cache`。

在普通用户的**宿主终端**检查：

```bash
git --version
docker compose version
docker buildx version
docker ps
```

`docker ps` 空列表也可以；若权限不足，请先由用户自行配置 Docker 访问权并重新登录，不能靠给容器挂 Docker socket 解决。

## 2. 获取代码并打开容器

在宿主普通用户终端执行（替换完整占位符）：

```bash
git clone --branch '<包含本方案的分支>' '<仓库地址>' bangumi32
cd bangumi32
code .
```

在 VS Code 确认信任自己的仓库，按 **Ctrl+Shift+P** 选择 **Dev Containers: Reopen in Container**。首次需要等待，保持窗口打开：

1. [宿主初始化](<devcontainer-host.sh>)自动检测 UID/GID，准备缺失的空挂载目录，并根据 Dockerfile 及镜像输入指纹复用或构建一个本地镜像；生成本机 Compose 覆盖文件。
2. 启动唯一的 `dev` 工作容器和该容器的 ADB Server。
3. [Dev Container 配置](<../.devcontainer/devcontainer.json>)每次启动时通过 `postStartCommand` 运行 `bangumi init`，首次在**真实仓库**的 `node_modules` 中安装 Android 依赖并应用补丁；输入未变时复用已有依赖。等待初始化结束后再开发，VS Code Server/扩展也可能下载。

不要手动在宿主安装项目依赖，也不要反复点击 Rebuild。打开后的 VS Code 新终端在容器中：

```bash
pwd
node --version
bangumi help
```

`pwd` 应为 `/repo`。命令未准备好或初始化报错时先阅读 VS Code 的 **Dev Containers: Show Container Log**；不要把配对码或凭据贴进日志、脚本或聊天。新方案实际连接仍待验证。

### 已有依赖和旧版迁移

- 初始化只管理带本方案标记的 Android `node_modules`：空目录可初始化；**非空且没有标记会拒绝覆盖**。若仓库已有宿主/iOS 依赖，由用户自行备份或移走后重试，不要自动删除。管理状态保存在 `node_modules/.bangumi-android-dependencies/state.json`；带有效标记且输入未变时复用依赖和原生增量。安装或补丁失败后保留该受管目录与状态，排查后可重新打开容器自动重试，也可在容器终端运行 `bangumi init`；不要在宿主运行安装命令绕过。
- Android 清单、Expo/Babel 配置、补丁和 ESLint 插件是**镜像快照**。这些输入变化后，在 VS Code 中执行 **Dev Containers: Rebuild Container**，让宿主初始化使用新的镜像指纹并在新容器执行初始化。正在运行的旧镜像里单独执行 `bangumi init` 不能读取这些新快照；它用于恢复/复用当前镜像的依赖。
- 从旧双容器方案迁移时，先保存工作；在 VS Code 容器列表中只停止旧项目的 `editor`，然后重新执行 **Reopen in Container**，必要时按 VS Code 提示重建一次。当前单服务 Compose 配置不再定义旧 `editor`；不要用 `down --volumes`。旧镜像、缓存卷默认保留；不从旧临时依赖投影自动复制模块。新指纹镜像首次仍需要初始化原生工具/依赖，并非承诺命中旧缓存。

## 3. 连接新手机

以下命令都在 **VS Code 容器终端**执行。建议先运行 `bangumi build` 完成长时间原生编译，再操作手机。

1. 手机与 Ubuntu 网络互通；在手机的开发者选项中开启**无线调试**，选择“使用配对码配对设备”。
2. 屏幕显示配对 IP 和**配对端口**后，在容器终端执行：

   ```bash
   adb pair 192.168.1.10:配对端口
   ```

   替换为手机实际地址，在终端交互输入配对码。**不要把配对码写进命令参数、聊天或脚本。**
3. 返回无线调试主界面，查看另一个**连接端口**，执行：

   ```bash
   adb connect 192.168.1.10:连接端口
   bangumi devices
   ```

   端口变化时使用当前显示的连接端口重新连接。多个设备或同一手机出现多条 mDNS/IP 记录时，用完整序列号显式指定，不自动猜测。
4. 保持手机解锁、亮屏，执行：

   ```bash
   bangumi start 192.168.1.10:连接端口
   ```

   或选择已连接设备 `bangumi start --device '完整序列号'`。它依次选择设备、验证 ARM64、启动受管 Metro、编译 Rust/Gradle、`install -r`、只设置开发包私有调试地址、建立所选设备的 `adb reverse` 并启动应用；不卸载或清数据。必要时由用户在手机上判断 Play Protect 提示，应用前台保持亮屏以避免 Doze 断连。

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

普通 JS/TS 源码保存后观察 Fast Refresh；Java/Rust/Android 资源变化需重新 `bangumi start` 或 `bangumi build` 再安装。Metro 固定监听 `127.0.0.1:8081`，所选设备通过 `adb reverse` 访问；断线或 server 重启后重新执行 `bangumi start`。根入口、TS、Metro 配置启动时从真实仓库复制到 Android 运行视图；这些文件变更后停止已有受管 Metro 并重新运行 `bangumi up`，或退出前台 Metro 后重新 `bangumi metro`，不必为原子保存重建容器。

关闭 VS Code 时 `shutdownAction: stopCompose` 会停止单一开发容器与其容器 ADB Server；项目文件和命名卷保留。重开容器后可重新连接已配对手机。可选的[宿主兼容入口](<android-debug.sh>)仅转发到容器；正常开发不用切回宿主，也不要求宿主 ADB。

## 工作区、缓存与安全

- 整仓库读写挂载到 `/repo`，Git 面板和宿主看到同一工作区；容器与受信任扩展也能访问仓库中的 `.git`、未跟踪或忽略的敏感文件。项目不主动挂 HOME、宿主 SSH/ADB 密钥、USB 或 Docker socket；VS Code/扩展可能根据个人设置共享凭据，请自行检查。推送仍由用户在宿主使用既有 SSH 443 和 rbw-agent。
- `/workspace` 是镜像准备的 Android 运行配置，不是第二份源码；`src`、`android`、`node_modules`、`metro-cache` 指向同一宿主项目数据，真实根目录的 iOS 清单、Expo/Babel 配置不会被切换。不要在根目录执行 `yarn env` 或直接运行根项目 npm 脚本；Android 命令统一用 `bangumi`。宿主若复用项目依赖，必须自行确认 Linux、架构及工具版本兼容。
- `node_modules`、Android `.gradle`、Rust `target`、OpenSSL 和 Metro 缓存留在仓库目录；Gradle 用户缓存、Cargo registry/git、Yarn 缓存及容器 ADB 身份分别由五个卷保存。**不自动清理缓存、镜像或卷。**工具链、运行脚本或镜像输入变化时在 VS Code 重建容器，以生成/复用匹配新输入的指纹镜像并执行初始化；普通源码修改不需要重建镜像。
- [Dockerfile](<Dockerfile>)顶部用 `ARG` 集中维护版本：系统包/JDK 为 `base`，Node、Yarn、Android SDK 和 Rust 分别从 `base` 独立安装，最后只将工具产物复制进 `dev`；Android 清单及配置在独立阶段生成。标准流程使用文件内的 `ARG` 默认值，变更后 Rebuild 会生成新指纹镜像；版本以独立实测结果选定，不在启动流程做工具组合预检。下载直接使用 HTTPS，不额外执行自定义摘要校验或构建末尾版本检查，SDK 与 Rust/Cargo 保留各自工具的校验机制。项目依赖由容器的 `bangumi init` 安装，执行 Yarn `--no-lockfile` 和补丁，不修改锁文件。仓库的 Cargo 构建仍使用 `--locked`。锁刷新、原生工程同步（如 Gradle sync / pod install）及业务/发布真机回归由用户自理。

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

Build Tools 统一为 30.0.3：工程根属性与 AGP 默认值一致，不再分新版和 legacy，也不安装 37。正常的 Android 调试/本地构建配置由[工作区准备器](<prepare-workspace.cjs>)生成，选择容器 SDK、CMake 和根 Build Tools 属性；已存在的用户自管配置不会被覆盖。SDK 归开发用户所有，允许官方管理器写入正常状态与锁文件。OpenSSL 缓存记录 NDK 路径和 OpenSSL 版本，更换工具链时重编，不误用旧编译器产物。最终镜像及真机结果分别记录于[验收记录](<VERIFICATION.md>)。

## ADB 安全与宿主模拟器预留

默认 `BANGUMI_ADB_SERVER_MODE=container`，容器管理自己的 ADB Server，使用不带 `-a` 的 `-L tcp:5037`，预期只监听 `127.0.0.1:5037`；客户端继续使用 `tcp:127.0.0.1:5037`。容器专用 `/home/dev/.android` 卷持久化配对身份。网络模式为 host，但不使用端口发布、`privileged` 或 USB 映射。若 5037 已被其他服务占用，容器会报错而不自动替换或杀掉现有服务；由用户判断处理。实际监听及真机连接仍须验收。

宿主模拟器**仅预留后端接口，尚未验收或实现 x86_64 构建**。用户可在宿主预先自行管理兼容的 ADB Server、客户端与模拟器，然后在启动 VS Code 的宿主环境中设置 `BANGUMI_ADB_SERVER_MODE=host` 并重新创建容器；该模式只探测并使用已有回环 server，不自动启动、关闭或替换它。保持宿主和容器 ADB 版本兼容；关闭容器也不停止宿主 server。

当前 `BANGUMI_ANDROID_ABI` 只允许 `arm64-v8a`；Gradle、Rust、OpenSSL 尚不支持 x86_64，**ADB 能看到 x86_64 模拟器不意味着 ARM64 APK 能运行**。Ubuntu 本身运行在 VMware 中时，宿主模拟器还需自行确认嵌套虚拟化与 KVM 可用。

## 官方 Features 的复用边界

[官方 Features](<https://github.com/devcontainers/features>)可以复用通用工具安装，但不是自动消除安装成本：它们是在基础镜像之后执行安装脚本、增加镜像层。

- [Node](<https://github.com/devcontainers/features/tree/main/src/node>)和[Java](<https://github.com/devcontainers/features/tree/main/src/java>)支持固定版本，分别使用 nvm 和 SDKMAN。若迁移，应替代对应的运行时安装，不能直接与现有版本叠加；本项目在 Android 配置生成阶段已调用 Node，现有系统/JDK 基础层和 SDK 构建流程也先于 Features；迁移前应先安排好构建期与运行期的分工。
- [Rust Feature](<https://github.com/devcontainers/features/blob/main/src/rust/devcontainer-feature.json>)默认申请 `SYS_PTRACE` 与 `seccomp=unconfined`，还会改变 Cargo/Rustup 路径；不默认采用这些放宽设置。官方集合当前没有对应的 Android SDK、双 NDK 或 cargo-ndk Feature，这些项目特定工具仍自行管理。
- 本版先保留已实测的 ARG 多阶段安装，不为复用而重复安装工具或扩大权限。将来可独立验证 Features 管理运行时工具的方案，但不能承诺首次构建必然更快或镜像更小。

## 独立工具升级验收

[升级验收脚本](<tests/validate-toolchain.sh>)只供明确授权后的隔离实验，**不会由 Dockerfile、容器入口或普通回归自动执行**。它仅从 Git 已跟踪文件的当前内容新建忽略的工作副本；发现未跟踪的非容器文件时先拒绝，要求明确处理复制范围，不静默遗漏或自动暂存。在副本中安装依赖和编译，并在运行前后核对锁文件；正式仓库的依赖和源码不作为写入目标。

```bash
# 尝试候选工具，仅做 Gradle 配置阶段；首次会创建并打印 CASE_DIRECTORY。
CANDIDATE_NODE_VERSION=26.13.1 CANDIDATE_JDK_MAJOR=25 \
  bash docker/tests/validate-toolchain.sh gradle-help

# 使用同一隔离副本和镜像原有 JDK 做完整构建。
CANDIDATE_NODE_VERSION=26.13.1 CANDIDATE_JDK_MAJOR=image \
  bash docker/tests/validate-toolchain.sh build '<CASE_DIRECTORY>'
```

`CANDIDATE_NODE_VERSION=image`、`CANDIDATE_JDK_MAJOR=image` 表示不覆盖镜像中的对应工具，用于最终镜像复验。每次使用相同副本可复用该副本的依赖和下载缓存，但不会自动同步主工作树之后的源码改动；日志保存在该副本中。生产版本只在实测后提升，配置成功、依赖安装成功或出现 APK 均不能替代手机冷启动与热更新验收；不会为得到通过结果而往生产入口添加测试分支。

## 排障与维护检查

- **5037 被占用**：先确认已有服务归属；不自动 kill。需共用宿主服务时明确选择 host 模式。
- **设备 offline / unauthorized**：检查无线调试、手机网络、配对端口与连接端口；使用 `bangumi devices`。重新配对时配对码只在交互终端输入。
- **8081 被占用**：确认占用进程；脚本不会接管或杀死其他 Metro。可检查 `http://127.0.0.1:8081/status` 和所选设备 reverse。
- **已有 Gradle 配置**：入口不会覆盖手写配置；用户确认并自行处理后重试。
- **下载或磁盘失败**：保留错误，检查网络和空间；不要关闭 TLS 校验、刷新锁文件或默认清缓存。

维护者在宿主可选执行以下静态/mock 检查，需要 Python 3 和 Node 18+；它们不连接真实设备、不安装项目依赖：

```bash
python3 -B -m unittest discover -s docker/tests -p 'test_*.py' -v
node --test docker/tests/test_*.cjs
(for script in docker/*.sh; do bash -n "$script" || exit; done)
docker compose -f docker/compose.yml config --quiet
```

真实镜像构建、容器重开和手机测试必须单独报告结果；静态/mock 通过不等同实际环境验收。官方参考：[Dev Containers](<https://code.visualstudio.com/docs/devcontainers/containers>)、[ADB 无线调试](<https://developer.android.com/tools/adb>)、[Docker host 网络](<https://docs.docker.com/engine/network/drivers/host/>)。
