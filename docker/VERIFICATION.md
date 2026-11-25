# 容器开发验收概要

## 历史证据

此前单项目根目录方案在隔离副本中完成 Android 环境切换、Yarn 初始化及含 Rust/OpenSSL 的 APK 构建；受管 Metro 曾实际返回 Android JS bundle。这些构建使用了缓存，并非当前改动后的冷构建。

此前独立容器中 ADB Server 启动、空设备列表和重复复用通过；更早的另一方案曾在 ARM64 真机验证无线安装、adb reverse、冷启动及 Fast Refresh。这些结果不能代替当前启动链和目标设备验收。

工具链选择有实际兼容性依据：现有 Gradle 在 JDK 21、25 配置失败，JDK 17 完成构建；旧 Expo 的 CMake 最低版本声明被 CMake 4 拒绝，CMake 3 完成配置。RN 和 Rust 使用不同 NDK，Build Tools 统一为 30.0.3。

## 当前改动验证

语法、Compose bridge 配置、挂载、镜像输入和自动初始化配置检查通过。用现有镜像启动临时 bridge 容器，挂载新版 ADB 包装器验证了官方 Server 按需启动及复用、5037 仅监听回环，以及配对需要交互终端。用测试监听器确认同容器内回环 8081 可访问、bridge 网卡上的 8081 不可访问。

用户已确认在 VS Code 打开 Dev Container 并连上手机。已核对运行中的容器使用 bridge、不发布端口，且 ADB 包装器与当前源码一致。

## 待用户验收

全新环境下的首次初始化和无线配对，以及 APK 安装、adb reverse、JS 冷启动及 Fast Refresh 尚未确认。锁刷新、原生同步及业务/发布真机回归由用户自行执行。
