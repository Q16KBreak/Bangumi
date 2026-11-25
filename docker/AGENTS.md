# Docker 开发：智能体指南

本文件约束本目录及子目录的容器维护工作，不替代上层指令，也不授予安装、提权、设备操作或 Git 写操作权限。

## 先读什么

- [README.md](<README.md>)：从全新系统开始的安装、配对、构建、缓存与排障流程。
- [VERIFICATION.md](<VERIFICATION.md>)：历史验收及支持边界；历史成功不等于本轮修改已经通过。
- 只读取当前任务涉及的脚本，先检查工作区和实际运行态，不根据旧聊天或日志恢复环境。

## 修改边界

- 容器相关改动默认限于 `docker/`；确需修改外部脚本、业务源码或文档时，先取得当次明确授权。
- 容器说明和验收更新写在本目录，不顺手修改外部架构/测试文档。
- 不修改、生成或删除锁文件，不在宿主执行项目依赖安装、原生同步或环境切换。
- 不把仓库默认 iOS 配置切成 Android；Android 配置准备只在镜像独立阶段进行。
- 默认不新增国内镜像源或代理配置，不关闭 TLS 校验；网络适配须由当次任务明确提出。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| [Dockerfile](<Dockerfile>) | 工具链、Android 配置、依赖、开发运行层及缓存边界 |
| [Dockerfile.dockerignore](<Dockerfile.dockerignore>) | 构建上下文白名单；新增镜像输入须同步检查 |
| [install-toolchain.sh](<install-toolchain.sh>) | 固定工具版本、下载及现有摘要校验 |
| [compose.yml](<compose.yml>) | host 网络、选择性绑定、非 root 身份及持久缓存 |
| [android-debug.sh](<android-debug.sh>) | 宿主入口：配对、选设备、构建安装、配置偏好和 reverse |
| [adb-server.sh](<adb-server.sh>) | 只读探测共享 ADB server 协议，供宿主和容器使用 |
| [entrypoint.sh](<entrypoint.sh>) | 容器内生成 Debug 配置，运行 Metro、构建或 shell |
| [start-metro.cjs](<start-metro.cjs>) | 旧 Expo CLI 的 JS 入口、回环绑定和 watch 适配 |
| [build-rust.sh](<build-rust.sh>) | Linux 容器专用 OpenSSL/Rust/JNI 构建，不安装工具链 |
| [configure-debug-host.py](<configure-debug-host.py>) | 仅转换开发包的私有调试地址，保留其他偏好 |
| [tests/](<tests/>) | Python 标准库和 Node 内置 test/VM 回归 |

## 不要破坏的架构

- 支持 Linux amd64 宿主、Android 11+ ARM64 真机；不默认扩展到 iOS、模拟器或 Docker Desktop。
- `/workspace` 是镜像内的 Android 工作目录，不是宿主仓库的完整副本。
- 不直接用整仓库绑定覆盖 `/workspace`：这会遮住镜像内的 Android 配置和 `node_modules`。
- 源码和原生工程选择性挂载；当前 JS 源码对容器只读，Android 工程可写，Git 在宿主操作。
- 当前是构建容器，不是完整 IDE Dev Container；不能声称宿主 IDE 自动拥有容器依赖或完整类型检查。
- RN 与 Rust/OpenSSL 的 NDK 分别为 23.1 和 27.1；版本细节以安装脚本、构建入口和工程配置为准，不混用或擅自升级为 latest。
- Rust 入口保持精简 Linux 流程，保留原有 `no-shared`、线程检查和 Cargo `--locked`，不要重新扩成跨平台安装/通用加固框架。

## ADB、网络与手机

- 保留 `network_mode: host`，共享宿主 `ADB_SERVER_SOCKET=tcp:127.0.0.1:5037`。
- Metro 仅监听 `127.0.0.1:8081`，手机通过所选设备的 `adb reverse tcp:8081 tcp:8081` 访问；不恢复 LAN 自动选路或双模式。
- 宿主客户端固定 platform-tools 37.0.1；server 探测只确认协议 41，不能据此识别完整发行版。
- 不自动 `kill-server`、启用 `adb -a`、发布 5037/8081、挂载私钥/USB/Docker socket，或使用 privileged。
- 显式选择设备；mDNS 名称可能含空格，同一手机可能同时出现 IP 和 mDNS 两条记录，不能随意换目标。
- 配对码只在用户的交互终端输入，不写进参数、聊天、脚本或日志。
- 只修改开发包 `com.czy0729.bangumi.dev` 的调试偏好；不卸载、清数据、改正式包或手机全局网络设置。
- 真机验收需用户保持解锁、亮屏、应用前台；ADB 在线不代表应用未被 Doze/后台策略断网，不用 root、唤醒或关闭省电策略绕过。
- 容器运行时的 host 网络不等于镜像构建阶段也用 host；下载故障先区分宿主、daemon、构建 RUN 和运行容器。

## 操作与缓存

以下示例在仓库根目录执行，仅供已获授权的任务使用；设备地址需替换。

```bash
# 无 Docker socket 权限时设置；不要 sudo 运行整个宿主脚本或 chmod socket。
export DOCKER_USE_SUDO=1
bash docker/android-debug.sh build-image
bash docker/android-debug.sh up
bash docker/android-debug.sh build                 # 无需手机或 ADB server
bash docker/android-debug.sh start 手机IP:连接端口  # 包含构建、安装、偏好、reverse 和启动
```

- 首次长时间编译尽量先 `up`、`build`，准备好后再请用户保持手机亮屏进行 `start`。
- JS 保存走热更新；Java/Rust 修改重新构建安装；依赖、补丁、镜像配置或镜像内脚本变化才重建镜像。
- 工具链脚本变化可能影响后续依赖阶段；运行脚本留在后部 COPY，不能为方便把易变输入提前到昂贵安装层。
- `build` 优先复用运行容器；`node_modules` 内原生增量产物在容器可写层，重建会丢失，但不等于重新安装依赖。
- Gradle/Cargo/OpenSSL/Metro 卷与 BuildKit 下载/层缓存不同；不要默认清卷、全局 prune 或使用 `--no-cache`。
- 使用 `LOCAL_UID/LOCAL_GID` 和既有缓存目录；不靠 root 运行、递归 chown 整仓库或放宽容器隔离解决权限问题。

## 验证与交付

先做与修改相关的静态/mock 检查，不安装宿主项目依赖；以下命令不触碰真实设备。

```bash
python3 -B -m unittest discover -s docker/tests -p 'test_*.py' -v
node --test docker/tests/test_metro.cjs
bash -n docker/*.sh
docker compose -f docker/compose.yml config --quiet
```

- 真实镜像/原生构建按当次授权执行；日志中区分依赖安装、依赖复制、缓存命中和实际编译。
- 真机验收区分 Metro `/status`、实际 JS 冷启动和不重装的热更新；日志窗口使用毫秒精度，必要时核对原生 PID。
- 临时源码标记、探针和容器内覆盖必须撤回；不能靠临时补丁通过后交付另一份源码。
- `validation/` 是被忽略的本机历史实验，不是默认执行入口；不要自动运行其中可能恢复旧配置的脚本。
- 验收记录写本轮实际结果，不抄旧计数，不把 mock、语法检查或历史日志称为新系统/真机实测。
- 未获当次明确授权，不暂存、提交、推送、stash 或改写历史；获得提交授权后，概述使用中文。
- 推送使用既有 SSH 443 配置及 rbw-agent；锁定时请用户解锁，不改用只读 GitHub token、不导出私钥。
- 提交前检查新增文件及待推送历史，不纳入密钥、配对信息、本机标识、日志、截图或编译产物。
