# Docker 开发：智能体指南

## 维护边界

- 容器改动默认限于 `docker/`，唯一目录外例外为 [devcontainer.json](<../.devcontainer/devcontainer.json>)；其他业务文件需当次授权。
- 不改 Git 索引、暂存、提交、推送、stash 或历史；不修改、生成或删除锁文件，不在宿主安装项目依赖或同步原生工程。
- 正常容器初始化已授权在真实仓库执行上游 `node packages/env.js android`，变更宿主可见；不得在宿主直接切换环境，不自动切回 iOS 或提交。
- 不自动删除已有 `node_modules`、缓存、卷或用户数据；切换中断后先核对根配置和依赖再继续。
- 不新增镜像源或代理、不关闭 TLS、不自动清缓存；不提交凭据、配对码、本机标识或编译产物。

## 关键不变量

- 仅支持 Linux amd64 和 Android 11+ ARM64 真机；单 `dev` 服务整仓读写绑定 `/repo`，保留五个用户级卷、非 root、独立 bridge 网络与安全限制。首次 postCreate 等待 `bangumi init`，普通重开不重复安装。
- 固定镜像标签由宿主初始化常规构建，Compose 不另设 build；[Dockerfile.dockerignore](<Dockerfile.dockerignore>) 保持构建上下文白名单和敏感文件保护。
- 官方 ADB 在容器内按需启动且仅监听回环 5037。Metro 在前台运行，手机通过在线设备的 adb reverse 访问容器内的 8081。不得启用 `adb -a`、发布端口、挂载宿主私钥/USB/Docker socket 或使用 privileged。
- 配对码只在用户交互终端输入；不卸载或清数据，不写手机调试偏好或全局网络设置。
- RN 与 Rust/OpenSSL 使用各自 NDK；OpenSSL 使用 `threads no-shared`，按 OpenSSL 和 NDK 版本复用构建目录。保留 Cargo `--locked`，不覆盖用户 Gradle 配置。
- 不把测试探针塞入生产入口。历史验收不能视为本轮验证，真实构建及设备操作须当次授权。

## 静态检查

```bash
(for script in docker/*.sh; do bash -n "$script" || exit; done)
node --check docker/prepare-project.cjs
docker compose -f docker/compose.yml config --quiet
```

语法及配置检查不能视为镜像、VS Code 生命周期或真机验收；后续锁刷新、原生同步及业务/发布真机回归由用户自理。
