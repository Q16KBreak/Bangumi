# Docker 开发：智能体指南

本文件约束本目录及子目录的容器维护工作，不替代上层指令，也不授予安装、提权、设备操作或 Git 写操作权限。先读[使用说明](<README.md>)和[验收记录](<VERIFICATION.md>)，检查当前工作区和运行态，不把历史成功当作本轮验证。

## 修改边界

- 容器相关改动默认限于 `docker/`；标准 VS Code 入口 [devcontainer.json](<../.devcontainer/devcontainer.json>) 是唯一目录外例外。其他外部脚本、业务源码或文档需当次明确授权。
- 不修改、生成或删除锁文件，不在宿主执行项目依赖安装、原生同步或环境切换。镜像内或真实仓库依赖安装、真实设备/构建按当次授权执行。
- 仓库默认 iOS 清单、Expo/Babel 配置不切换；Android 配置只在镜像独立阶段准备。容器内 Android 依赖放仓库 `node_modules`，首次遇到非空无管理标记目录必须拒绝，不自动删除/覆盖。
- 默认不新增镜像源或代理、不关闭 TLS。不得因便于测试自动清缓存；本次用户对缓存清理的授权不是长期授权。
- 不改 Git 暂存区、提交、推送、stash 或改写历史；需要推送时由用户使用既有 SSH 443 和 rbw-agent。不得将凭据、配对码、本机标识或编译产物提交。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| [Dockerfile](<Dockerfile>) | 顶部 ARG 集中版本，系统/JDK base 与独立工具阶段，最终只复制产物到 dev；不复制安装脚本再执行 |
| [Dockerfile.dockerignore](<Dockerfile.dockerignore>) | 镜像构建上下文白名单与敏感文件保护 |
| [compose.yml](<compose.yml>) | 单一 `dev` 服务、仓库与运行视图挂载、host 网络、五个用户级卷 |
| [devcontainer.json](<../.devcontainer/devcontainer.json>) | VS Code 标准入口：宿主 initialize、单容器、postStart 等待初始化 |
| [devcontainer-host.sh](<devcontainer-host.sh>) | 宿主 UID/GID、镜像输入指纹、缺失时构建镜像及本机 Compose 覆盖 |
| [prepare-workspace.cjs](<prepare-workspace.cjs>) | 受标记约束的 Android 依赖安装/复用、补丁与共用入口同步 |
| [entrypoint.sh](<entrypoint.sh>) | workbench、运行环境检查、Metro 和 Rust/Gradle 构建 |
| [develop.sh](<develop.sh>) | 容器内 `bangumi`：初始化、设备选择、构建安装、受管 Metro、日志 |
| [adb.sh](<adb.sh>)、[adb-manager.sh](<adb-manager.sh>)、[adb-server.sh](<adb-server.sh>) | ADB 参数保护、容器/host server 归属与只读协议探测 |
| [android-debug.sh](<android-debug.sh>) | 可选宿主兼容转发，不要求宿主 ADB；正常开发使用容器终端 |
| [start-metro.cjs](<start-metro.cjs>) | 旧 Expo CLI 回环绑定与 watch 适配 |
| [build-rust.sh](<build-rust.sh>) | 容器 Linux OpenSSL/Rust/JNI 构建，使用预装工具 |
| [configure-debug-host.py](<configure-debug-host.py>) | 仅转换开发包私有调试地址 |
| [tests/](<tests/>) | Python 标准库、Node 内置 test/VM mock 回归 |

## 不要破坏的一体化架构

- 只支持 Linux amd64 宿主、Android 11+ ARM64 真机；不默认扩展 iOS、USB、模拟器或 Docker Desktop。`BANGUMI_ANDROID_ABI` 仅 `arm64-v8a`，x86_64 接口未实现，不能将设备可见误称 APK 可运行。
- 唯一 `dev` 容器完整读写挂载真实仓库 `/repo`；`/workspace` 保存镜像生成的 Android package/app/Babel/patches 与 ESLint 运行配置，不能用整仓挂载覆盖。源码、Android 工程、`node_modules`、Metro 缓存共用同一宿主文件；根入口/TS/Metro 配置在运行准备时复制，保存后重启 Metro 刷新。
- 真实仓库保留 `node_modules`、Android `.gradle`、Rust `target`/OpenSSL 和 Metro 缓存；仅 Gradle 用户缓存、Cargo registry/git、Yarn 缓存及容器 ADB 状态使用五个卷。`postStart` 每次启动运行 `bangumi init`，依赖输入未变时复用现有产物，失败后可重新启动重试；受管状态保存在 `node_modules/.bangumi-android-dependencies/state.json`。Android 清单、Expo/Babel、补丁及 ESLint 插件是镜像快照，改这些输入后须重建容器以更新指纹镜像，再由 `postStart` 初始化；旧镜像中的 `bangumi init` 不能获取新快照。
- 自动初始化按 Dockerfile 和实际镜像输入哈希+UID/GID 计算本地镜像标签；缺失时一次构建，再生成本机 Compose 覆盖。Compose 服务本身无 `build`，防止 VS Code 临时 Dockerfile 触发第二次完整构建。
- 语言服务使用 Android 依赖，根清单仍是 iOS 默认；不运行根 `yarn env` 或直接根项目启动脚本，不承诺全量类型零错误或未经验证的断点调试。完整仓库中未跟踪和忽略的敏感文件对容器/扩展可见；不承诺 VS Code 不会按个人配置共享凭据。
- RN 与 Rust/OpenSSL 分别使用 NDK 23.1 和 27.1；以 Dockerfile、构建入口和工程配置为准。保留 Rust 的 `no-shared`、线程检查和 Cargo `--locked`。

## ADB、手机与网络

- 默认容器内 ADB Server 使用不带 `-a` 的 `-L tcp:5037`，预期监听 `127.0.0.1:5037`，客户端使用 `tcp:127.0.0.1:5037`；使用自己的 `/home/dev/.android` 命名卷。若端口已被其他服务占用则失败，不自动替换。`BANGUMI_ADB_SERVER_MODE=host` 仅为可选宿主模拟器后端，只读探测已有 server，不启动/停止/替换；宿主负责兼容版本。
- 保留 `network_mode: host`、Metro `127.0.0.1:8081` 和所选设备 `adb reverse`。不启用 `adb -a`、发布 5037/8081、主动挂宿主私钥/USB/Docker socket 或使用 privileged。不要恢复 LAN 自动选路。
- 显式选择设备；mDNS 名称可能含空格，同一设备可能有 IP 和 mDNS 多条记录。配对码只在用户交互终端输入，不写参数、聊天、脚本或日志。
- 只操作开发包 `com.czy0729.bangumi.dev` 的私有调试偏好；不卸载、清数据、改正式包或手机全局网络。真机验收由用户保持解锁、亮屏、前台；不使用 root 或修改省电策略绕过。
- 模拟器目前未验收，x86_64 的 Gradle/Rust/OpenSSL 构建未实现；VMware 内 Ubuntu 如需模拟器还要确认嵌套虚拟化与 KVM。

## 开发、缓存与验收

在 VS Code 容器终端使用 `bangumi init/build/up/metro/devices/start/install/logs/down` 或交互 `adb pair`。`bangumi down` 仅停止自己管理的 Metro；关闭 VS Code 按 Dev Container 配置停止 Compose，保留仓库和卷，不影响 host 模式下的宿主 ADB。旧双容器迁移先保存代码、只停止旧 `editor`，不清旧镜像或卷。

先做与修改相关的静态/mock 检查，不安装宿主项目依赖；以下不触碰真实设备：

```bash
python3 -B -m unittest discover -s docker/tests -p 'test_*.py' -v
node --test docker/tests/test_*.cjs
(for script in docker/*.sh; do bash -n "$script" || exit; done)
docker compose -f docker/compose.yml config --quiet
```

- 配置测试应覆盖单服务、真实仓库与运行视图、五卷、无 Compose build、输入指纹/UID 和项目名、旧依赖拒绝/受管复用、ADB 归属及端口冲突；不启动真实 Docker 或设备的 mock 不能视为真机验收。
- 工具链 Dockerfile、运行脚本和指纹输入保持一致；变更会触发镜像更新，不能把源码或私密配置无故加进构建上下文。不要把构建安装塞回单独 COPY 的安装脚本。
- 真实镜像/原生构建按当次授权执行；日志中区分依赖安装、缓存命中和实际编译。真机区分 Metro `/status`、实际 JS 冷启动和不重装热更新；必要时核对原生 PID。
- `validation/` 为忽略的历史实验，不自动运行。临时探针必须撤回；[验收记录](<VERIFICATION.md>)只记录本轮实际结果，后续锁刷新、原生同步及业务/发布真机回归由用户自理。
