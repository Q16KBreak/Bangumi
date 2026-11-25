# Android 容器开发与 adb reverse 无线调试

工具链和项目依赖全部在容器中。宿主只需 Linux amd64 的 Docker Engine（含 Buildx、Compose 插件）以及与镜像**同版的 platform-tools 37.0.1**（本项目固定）；宿主不需要 Node、Python、JDK、Rust、Android Studio 或任何项目依赖。支持 Android 11+、ARM64 真机；不构建 iOS、模拟器或发布签名包。

**连接方式：`adb reverse`。** 手机只访问自己的 `127.0.0.1:8081`，由已授权的 ADB 连接转发到开发机的 `127.0.0.1:8081`；Metro 只监听回环地址，不读取也不猜测电脑的局域网 IP。Compose 保持 `network_mode: host`，用于共享宿主回环上的 ADB server（`tcp:127.0.0.1:5037`）。该链路已在真机验证，环境与结果见[验收记录](<VERIFICATION.md>)。

## 环境要求与支持边界

- Linux **amd64**；镜像只提供这一架构。
- Docker Engine（官方 apt 仓库）与 Buildx、Compose 插件。
- 宿主 **platform-tools 37.0.1**，与镜像内版本一致（本项目固定此版本，协议 1.0.41）。
- 基础命令：`bash`、`git`、`curl`、`unzip`、`ca-certificates`、`coreutils`（`base64`、`sha256sum`）。
- Android 11+ 真机，开启开发者选项与无线调试。无线 ADB 本身要求手机与电脑在同一局域网且网络可达；本教程不覆盖 USB 连接。手机不需要能主动访问电脑的端口。
- **不在当前支持范围**：Rootless Docker、Docker Desktop、Windows/macOS 宿主、模拟器、iOS、正式签名包。

## 准备全新 Ubuntu amd64 宿主

以 Docker 官方当前支持的 Ubuntu amd64 版本为例（是否受支持以 Docker 官方页面为准）。以下命令用普通用户执行，只有安装系统包需要 `sudo`。

### 基础工具

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates coreutils curl git unzip
```

`sudo` 只用于安装 Docker 等系统包；platform-tools 装在用户目录，不需要 sudo。账号没有 sudo 时，请让有权限的管理员完成 Docker 部分。

### 安装 Docker Engine

按 Docker 官方文档 **Install using the apt repository** 一节配置签名密钥、apt 源并安装。不要照抄第三方教程里长期不更新的仓库/密钥片段，也不要用发行版自带的 `docker.io`：官方页面会随 Ubuntu 代号与签名方式更新。

- [官方安装文档](<https://docs.docker.com/engine/install/ubuntu/>)
- 安装包：`docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`（以官方页面当前命令为准）

安装后验证：

```bash
sudo docker run --rm hello-world
sudo docker compose version
sudo docker buildx version
```

若提示 Docker daemon 未运行，在使用 systemd 的 Ubuntu 上执行 `sudo systemctl start docker` 后重试；是否开机自动启动按需选择。

`hello-world` 能拉取并运行，说明 Docker Engine、镜像下载与网络正常；两个插件命令能输出版本，说明 Buildx、Compose 可用，无需再单独安装旧式 `docker-compose` 二进制。

### 权限：sudo 或 docker 组

- **推荐**保持默认权限，单独的 Docker 命令用 `sudo`；调试脚本仍由普通用户运行，设置 `export DOCKER_USE_SUDO=1` 仅让其中的 Docker 调用走 sudo。不要用 `sudo bash` 运行整个调试脚本，以免 ADB 使用另一套用户环境或密钥。交互 shell 可能提示输入 sudo 密码。
- 也可以把用户加入 `docker` 组免 sudo，但这**等价于给予该用户 root 级权限**（可直接挂载宿主文件、启动可提权容器）。只在单用户开发机按需选择，不要把该组授予共享账号。参考[官方后续配置说明](<https://docs.docker.com/engine/install/linux-postinstall/>)。
- 本项目不修改 Docker socket 权限、不开放 Docker TCP API、不挂载 Docker socket、不使用 `privileged`。

### 安装固定版本 platform-tools 37.0.1

本项目把宿主 adb 固定为 37.0.1，与镜像内版本一致，避免多版本客户端混用同一个 server；这不代表 Google 要求所有客户端的发行版必须相同。**不要**使用 `apt install adb`、`sdkmanager platform-tools`（会跟随最新版）或网上"最新 platform-tools"压缩包。

官方固定下载（与镜像工具链同一地址、同一摘要）。首次安装推荐装到用户目录 `$HOME/.local/share/android-platform-tools/37.0.1`，无需 sudo：下面的命令先建临时下载目录，**只在目标目录不存在时**解压。如果这台机器上已经装过 37.0.1，不要执行本段，直接把 `BANGUMI_ADB_BIN`（见下）指向原路径。

```bash
(
  set -euo pipefail
  url=https://dl.google.com/android/repository/platform-tools_r37.0.1-linux.zip
  sha=d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1
  target="${HOME:?}/.local/share/android-platform-tools/37.0.1"

  if [[ -e "$target" || -L "$target" ]]; then
    echo "目标已存在，跳过安装并核对版本：$target"
  else
    tmp="$(mktemp -d)"
    curl -fL --retry 4 --proto '=https' --tlsv1.2 -o "$tmp/platform-tools.zip" "$url"
    printf '%s  %s\n' "$sha" "$tmp/platform-tools.zip" | sha256sum --check --strict -
    # 下载或校验失败会退出本段，不解压；不移动或覆盖已有安装。
    [[ ! -e "$target" && ! -L "$target" ]]
    mkdir -p -- "$target"
    unzip -q "$tmp/platform-tools.zip" -d "$target"
  fi
  "$target/platform-tools/adb" version
)
```

临时目录不会自动删除，可按需自行清理。版本检查应看到这两行关键信息：

```
Android Debug Bridge version 1.0.41
Version 37.0.1-15733141
```

让项目使用该版本：推荐只设 `BANGUMI_ADB_BIN`，用包含 `$HOME` 的完整路径（脚本会直接使用该路径，不依赖某个终端里残留的临时变量）：

```bash
export BANGUMI_ADB_BIN="$HOME/.local/share/android-platform-tools/37.0.1/platform-tools/adb"
```

如果也想在终端直接输入 `adb` 使用同一版本，再单独加 PATH（放在系统旧 adb 之前）：

```bash
export PATH="$HOME/.local/share/android-platform-tools/37.0.1/platform-tools:$PATH"
```

`export` 只对当前终端有效；需要跨终端复用时，把相应设置写入 shell 启动配置（例如 `~/.bashrc`），或在每次运行脚本前重新设置。不要覆盖或重命名系统已有的 adb。

要点：

- **不覆盖已有安装**：已装过 37.0.1 时保留原目录，把 `BANGUMI_ADB_BIN` 指向原路径即可；已装过其它版本时也不要删除。不要改动或删除 `~/.android/adbkey`、`adbkey.pub`，工具链只读使用现有密钥。
- 脚本检查本机 adb 客户端为 `37.0.1`，并以只读探测确认现有 server 协议为 `41`；它无法识别 server 的完整发行版。发现不兼容时脚本拒绝自动重启或替换 server，请自行统一版本。
- 宿主不需要 Android SDK、`sdkmanager`、Android Studio、JDK、Node 或 Python。
- 官方参考：[platform-tools 发布说明](<https://developer.android.com/tools/releases/platform-tools>)、[adb 手册与无线调试](<https://developer.android.com/tools/adb>)（Android 11+ 使用配对码配对，连接端口与配对端口不同）。

## 获取代码

```bash
git clone --branch '<包含 docker 目录的分支>' '<包含 docker 目录的仓库地址>' bangumi32
cd bangumi32
test -f docker/android-debug.sh
```

尖括号为占位符，与引号一起整体替换为实际仓库地址与包含 `docker/` 目录的分支或标签。命令在仓库根目录执行；脚本也支持从其它目录调用。

## 首次构建

```bash
export DOCKER_USE_SUDO=1   # 仅在需要 sudo 时
bash docker/android-debug.sh build-image

# 先完成首次原生编译，不需要连接手机。
# 保持开发容器运行，可复用 node_modules 内原生依赖的增量产物。
bash docker/android-debug.sh up
bash docker/android-debug.sh build
```

首次镜像及原生构建会下载容器工具链（Node、JDK、Android SDK/NDK/CMake、Rust、cargo-ndk、platform-tools）、Android/Gradle/Cargo 依赖及 OpenSSL 源码，体积为**数 GB**。先完成上述构建再操作手机，避免让手机在漫长的首次编译中休眠；后续 `start` 只需进行正常增量检查。建议预留 **30 GiB 以上**可用磁盘空间（镜像、依赖、原生构建与临时下载合计），这是推荐值而非硬性保证，空间越少越可能中途失败。耗时取决于网络、CPU 与磁盘，本文不给出时间保证。重复执行可见 BuildKit 的 `CACHED`。**不要**加 `--no-cache`，也不要为"干净重建"删除缓存或运行卷。

## 连接手机并首次启动

```bash
# 手机：开发者选项 → 无线调试 → 使用配对码配对设备。
# 在宿主交互终端按提示输入配对码，不要写进命令参数、脚本或提交。
bash docker/android-debug.sh pair 192.168.1.10:配对端口

# 使用无线调试主页面显示的"IP 地址和端口"连接；它与配对端口不同。
bash docker/android-debug.sh start 192.168.1.10:连接端口
```

`start` 的顺序：确认并**显式选择设备** → 启动 Metro（仅 `127.0.0.1:8081`）→ 增量构建 Rust/ECH 与 debug APK → `install -r` 保留数据安装 → 只把 `com.czy0729.bangumi.dev` 的私有 `debug_http_host` 固定写为 `127.0.0.1:8081` → `adb -s <序列号> reverse tcp:8081 tcp:8081` → 启动应用。它不清空应用数据、不写正式包、不改手机全局代理或系统 `metro.host`、不卸载旧包。

- 已配对过的手机不必重复配对；mDNS 自动重连时可省略 `start` 地址，连接端口变化后按手机页面重新传入。
- 多台设备时，用 `start IP:PORT` 或 `ANDROID_SERIAL` 明确指定目标；两者不能指向不同设备，脚本不会自动挑一台：

  ```bash
  ANDROID_SERIAL=192.168.1.10:连接端口 bash docker/android-debug.sh start
  ```

- 首次构建和启动时保持手机**解锁、亮屏且应用在前台**。Doze/后台策略可能切断调试连接，表现为启动几秒后黑屏或连接中断；不要因此关闭安全校验、省电策略或改代理。

## 日常命令

```bash
bash docker/android-debug.sh start       # 完整流程：选择设备、启动、构建、安装、reverse、启动
bash docker/android-debug.sh up          # 启动 Metro 与宿主 ADB server（按需），无需手机在线
bash docker/android-debug.sh devices     # 宿主 ADB 设备列表与 mDNS 发现
bash docker/android-debug.sh build       # 只编译 Rust/ECH 与 debug APK，无需手机或 ADB server
bash docker/android-debug.sh install     # 只安装已有 APK，不删除数据
bash docker/android-debug.sh logs        # React Native / Android 错误日志
bash docker/android-debug.sh down        # 停止容器，保留缓存与宿主 ADB server
sudo docker compose -f docker/compose.yml exec dev /usr/local/bin/bangumi-entrypoint shell
```

| 变量 | 默认 | 用途 |
| --- | --- | --- |
| `DOCKER_USE_SUDO` | `0` | `1` 表示 Docker 命令走 sudo |
| `BANGUMI_ADB_BIN` | `adb` | 宿主 adb 可执行文件，支持含空格的路径 |
| `ANDROID_SERIAL` | 唯一在线设备 | 多设备时必须指定 |
| `LOCAL_UID` / `LOCAL_GID` | 当前宿主用户 ID | 非 root 构建/运行身份，改变后需重建镜像 |
| `BANGUMI_BUILD_JOBS` | `4` | 原生构建并行数，内存不足时调小 |

## reverse、网络与安全边界

- Metro 只监听 `127.0.0.1:8081`，容器健康检查同样访问回环；电脑的 8081 不对局域网或公网开放，手机也不需要能主动访问电脑端口。
- `adb reverse tcp:8081 tcp:8081` 把所选设备的回环端口映射到开发机回环端口，JS 与热更新共用这条通道；旧 SDK 中依赖手机回环的 inspector 如需连接，也可使用同一条映射。反向连接的目标由**宿主 ADB server** 解析，所以目标就是宿主的 `127.0.0.1:8081`；这也是容器需要 host 网络、而 Metro 只绑回环仍可工作的原因。映射属于该设备与该 server：断开重连、端口变化或 server 重启后需重新执行 `start`；可用 `adb -s <序列号> reverse --list` 查看当前映射。`start` 只重建所选手机的 `tcp:8081` 映射，不使用 `reverse --remove-all`，不会删除设备上的其它映射。
- ADB server 只监听 `127.0.0.1:5037`；脚本不执行 `adb -a`、不 `kill-server`、不做端口映射或发布、不使用 `privileged`、不挂载 USB 或私钥。
- 配对、mDNS、设备连接与密钥都由宿主负责；容器不挂载 HOME、SSH/ADB 私钥或 Docker socket，Android Studio 可使用同一设备列表。
- 不要为 5037 或 8081 配置公网/局域网端口转发；reverse 只在已授权的调试连接内生效。

## 源码、配置与缓存

[Dockerfile](<Dockerfile>)把容易变化的输入放在后面：

1. 工具链（[install-toolchain.sh](<install-toolchain.sh>)）：Node 22.20.0、Yarn 1.22.22、JDK 17、SDK 34、Build Tools 33.0.0 / 30.0.3、CMake 3.22.1、RN NDK 23.1.7779620、Rust NDK 27.1.12297006、Rust 1.100.0、cargo-ndk 4.1.2、platform-tools 37.0.1。各下载的校验方式与摘要以该脚本为准：Node、Rust、cargo-ndk、platform-tools 等校验固定 SHA-256，Yarn 校验 SHA-512，SDK 组件由 sdkmanager 按 Google 仓库元数据校验；apt 包与无锁 Yarn 依赖并非逐项冻结。`adb` 只在构建内做本机版本检查，不连接设备。
2. 配置准备阶段复用[环境切换脚本](<../packages/env.js>)，依赖层只接收 Android 清单、六个补丁和本地 ESLint 插件。
3. 最后复制 Expo/Babel 配置、运行入口（[entrypoint.sh](<entrypoint.sh>)、[start-metro.cjs](<start-metro.cjs>)）、调试偏好 helper（[configure-debug-host.py](<configure-debug-host.py>)）和 [Linux Rust 构建脚本](<build-rust.sh>)；用户身份在昂贵的工具链与依赖安装之后设置。

Rust 构建入口仅用于 Linux 容器，直接使用镜像预装的 Rust/cargo-ndk/NDK 27.1，不调用或改写仓库原有的跨平台脚本。首次构建自动从官方 Release 下载、解压 OpenSSL 4.0.1，无需交互，不额外校验源码 SHA256。沿用原有 `no-shared` 配置和线程检查，使用现有 OpenSSL/Cargo 缓存；Cargo 仍使用 `--locked`。容器适配和测试均位于本目录，仓库其它脚本与文档保持主分支版本。

| 修改内容 | 后续操作 | 缓存预期 |
| --- | --- | --- |
| [源码](<../src/>)中的 JS / TS / 样式 | 保存并观察热更新 | 不重建镜像 |
| Java / Rust / Android 资源 | `start`，或 `build` 后再 `install` | 不重建镜像，复用原生缓存 |
| 单文件挂载的根入口 / TS / Metro 配置 | 重启开发容器，必要时重启应用 | 不重装依赖 |
| 镜像内 Expo/Babel 配置、入口/helper、Rust 构建脚本 | `build-image` 再 `up` | 工具链与依赖层命中 |
| Android 清单 / 补丁 / ESLint 插件 | `build-image` 再 `up` | 工具链命中，复用下载缓存 |
| 工具链版本 | `build-image` 再 `up` | 从对应工具层重新构建 |

[Compose 配置](<compose.yml>)只共享宿主网络，不共享 ADB 密钥、USB 或 Docker socket；[构建上下文白名单](<Dockerfile.dockerignore>)不传业务/原生源码、宿主依赖、缓存、私密配置或 Git，文档和测试不影响镜像。[源码](<../src/>)、[原生工程](<../android/>)、根入口与 Metro 配置选择性挂载；`android/` 可写以保留 `build/.cxx`、JNI 与 APK，`src/` 只读。

`build` 优先复用运行中的开发容器，从而保留 `node_modules` 内原生依赖的 `build/.cxx` 等增量产物；这部分在容器可写层，重建或删除开发容器会丢失，需要重新生成。Gradle、Cargo、OpenSSL 与 Metro 缓存在独立卷中，`down` 或重建容器不会删除。这是容器可写层与命名卷的差别，不属于镜像依赖层重装，也不会改变镜像构建的 `CACHED` 命中。确需清空**本项目**运行卷时，确认不在构建中后自行执行 `docker compose -f docker/compose.yml down --volumes`（必要时加 sudo）；它不影响 BuildKit 缓存，也不要全局 prune 其它项目。

仓库未提交 Yarn lock，镜像用 `--no-lockfile`，不生成或修改锁文件；无锁传递依赖仍可能随时间变化，并非完全可复现。Rust 使用 [Cargo.lock](<../android/rust/Cargo.lock>) 与 `--locked`。宿主默认依赖清单、Expo/Babel/Metro 配置与现有 `node_modules` 保持不变；后续依赖升级、锁刷新、原生工程同步（如 pod install / gradle sync）与发布回归由用户自理。

## 检查与排障

- **Docker 权限不足**：设置 `DOCKER_USE_SUDO=1`，不要 chmod Docker socket。
- **无设备 / offline / unauthorized**：核对无线调试、配对/连接端口与局域网可达性，查看 `devices`；必要时交互 `pair`。
- **手机连不上开发服务器**：确认 `adb -s <序列号> reverse --list` 含 `tcp:8081 tcp:8081`，否则重新 `start`；确认 Metro 在 `127.0.0.1:8081/status` 返回 `packager-status:running`。先核对 reverse 与手机前台状态，不要先动业务代理或旁路由规则。
- **锁屏后黑屏或连接被中止**：调试时保持解锁、亮屏、应用在前台；先解锁再重新 `start`。
- **8081 被占用或 Metro 未就绪**：先确认占用 8081 的进程，再自行停止不需要的 Metro；脚本不杀宿主进程。
- **adb 版本不匹配**：宿主客户端必须是本项目固定的 37.0.1；脚本只校验本机客户端版本并只读探测 server 协议 41，不识别 server 的完整发行版，也不会自动重启或替换 server。请自行统一版本后再试。
- **Play Protect 拦截**：由用户在手机上判断是否允许本 debug 包；脚本不关闭安全校验，也不自动卸载或清空旧包。
- **run-as / 调试地址写入失败**：确认安装的是否为本仓库 debug 包；失败即停止，不会改全局设置或用 root 绕过。
- **已有 Gradle 本地配置**：[入口](<entrypoint.sh>)不覆盖手写配置，以免破坏签名；确认后自行迁移或备份。
- **OpenSSL、NDK、补丁或下载失败**：保留原始错误，确认网络/磁盘后重试，不刷新锁文件或关闭 TLS 校验来绕过。

### 维护者测试（可选）

只有修改 `docker/` 内脚本时才需要，普通开发无需执行；这些测试依赖宿主 Python 3 与 Node 18+（可选），不安装项目依赖：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s docker/tests -p 'test_*.py' -v
node --test docker/tests/test_metro.cjs        # 需要宿主 Node 18+
bash -n docker/*.sh
sudo docker compose -f docker/compose.yml config
```

参考：[Docker 安装](<https://docs.docker.com/engine/install/ubuntu/>)、[Linux 后续配置](<https://docs.docker.com/engine/install/linux-postinstall/>)、[host 网络驱动](<https://docs.docker.com/engine/network/drivers/host/>)、[构建缓存](<https://docs.docker.com/build/cache/optimize/>)、[platform-tools](<https://developer.android.com/tools/releases/platform-tools>)、[adb 与无线调试](<https://developer.android.com/tools/adb>)。
