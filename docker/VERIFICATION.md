# 容器开发验收概要

## 历史证据

此前单项目根目录方案在隔离副本中完成 Android 环境切换、Yarn 初始化及含 Rust/OpenSSL 的 APK 构建；受管 Metro 曾实际返回 Android JS bundle。这些构建使用了缓存，并非当前改动后的冷构建。

此前独立容器中 ADB Server 启动、空设备列表和重复复用通过；更早的另一方案曾在 ARM64 真机验证无线安装、adb reverse、冷启动及 Fast Refresh。这些结果不能代替当前启动链和目标设备验收。

工具链选择有实际兼容性依据：现有 Gradle 在 JDK 21、25 配置失败，JDK 17 完成构建；旧 Expo 的 CMake 最低版本声明被 CMake 4 拒绝，CMake 3 完成配置。RN 和 Rust 使用不同 NDK，Build Tools 统一为 30.0.3。

## 当前改动验证

Shell、Node、Python 语法检查、Compose 配置解析、Dev Container 自动初始化契约和镜像 COPY 源文件检查通过。保留单服务、唯一整仓挂载、五个卷及容器安全选项。

本轮未重建镜像、安装项目依赖、构建 APK 或操作手机；静态检查不代表 VS Code 生命周期或真机验收。

## 待用户验收

完整 VS Code 首次创建和重开、真实仓库初始化、按需 ADB 启动与端口冲突、无线配对连接、APK 安装、JS 冷启动及 Fast Refresh 均须在目标环境验证。锁刷新、原生同步及业务/发布真机回归由用户自行执行。
