# syntax=docker/dockerfile:1.7
# @Author: Q16KBreak
#
# Android 无线真机开发镜像：工具、配置切换、依赖相互隔离缓存；源码仅在运行时挂载。
FROM --platform=linux/amd64 debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS toolchain
SHELL ["/bin/bash", "-Eeuo", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_NDK_HOME=/opt/android-sdk/ndk/27.1.12297006 \
    ANDROID_NDK_ROOT=/opt/android-sdk/ndk/27.1.12297006 \
    RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    RUSTUP_TOOLCHAIN=1.100.0 \
    ADB_SERVER_SOCKET=tcp:127.0.0.1:5037
ENV PATH=/opt/cargo/bin:/opt/android-sdk/cmdline-tools/19.0/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/cmake/3.22.1/bin:${JAVA_HOME}/bin:${PATH}

# Debian apt verifies signed repository metadata and package digests. Keep apt's
# download cache; neither business files nor LOCAL_UID/GID invalidate this layer.
RUN --mount=type=cache,id=bangumi-android-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=bangumi-android-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
      bash build-essential ca-certificates curl git openjdk-17-jdk-headless \
      perl pkg-config python3 unzip xz-utils zip
COPY docker/install-toolchain.sh /usr/local/lib/bangumi/install-toolchain.sh
RUN bash /usr/local/lib/bangumi/install-toolchain.sh

# Lightweight stage: run the project's real Android switch WITHOUT node_modules.
# No root package.json is needed: this isolated stage has no current environment
# to back up. Include both the Android patch symlinks and their canonical targets.
FROM toolchain AS android-config
WORKDIR /configuration
COPY packages/env.js ./packages/env.js
COPY packages/android/package.json ./packages/android/package.json
COPY packages/android/patches/ ./packages/android/patches/
COPY packages/patches/react-native-android-widget+0.5.2.patch \
     packages/patches/react-native-pager-view+6.2.0.patch \
     packages/patches/react-native-realtimeblurview+1.1.3.patch \
     packages/patches/react-native-render-html+4.1.1.patch \
     packages/patches/react-native-smb+0.2.4.patch \
     packages/patches/react-native-tab-view+3.5.2.patch ./packages/patches/
COPY babel.config.js app.json ./
RUN node packages/env.js android && \
    test ! -e node_modules && \
    test "$(node -p 'require("./package.json").name')" = android && \
    test "$(find patches -maxdepth 1 -name '*.patch' | wc -l)" = 6

FROM toolchain AS dependencies
WORKDIR /workspace
ENV CI=1
# COPY uses output contents, not config-stage lineage: Babel/Expo/app changes do
# not invalidate Yarn if the Android manifest and six patches remain unchanged.
COPY --from=android-config /configuration/package.json ./package.json
COPY --from=android-config /configuration/patches/ ./patches/
COPY --from=android-config /configuration/packages/patches/ ./packages/patches/
COPY eslint-rules/ ./eslint-rules/
RUN --mount=type=cache,id=bangumi-android-yarn-v1,target=/var/cache/yarn,sharing=locked \
    YARN_CACHE_FOLDER=/var/cache/yarn yarn install --no-lockfile --non-interactive && \
    ./node_modules/.bin/patch-package --error-on-fail && \
    test ! -e yarn.lock && test ! -e package-lock.json

# Some legacy native modules still use AGP 4.2.x and require its minimum Build Tools.
# Keep this small compatibility download independent from the expensive tool/dependency layers.
FROM toolchain AS legacy-build-tools
RUN sdkmanager --sdk_root="$ANDROID_HOME" --install 'build-tools;30.0.3'

FROM toolchain AS dev
ARG LOCAL_UID=1000
ARG LOCAL_GID=1000
WORKDIR /workspace
ENV HOME=/home/dev \
    CARGO_HOME=/home/dev/.cargo \
    GRADLE_USER_HOME=/home/dev/.gradle \
    XDG_CACHE_HOME=/home/dev/.cache \
    CI=1 \
    EXPO_NO_TELEMETRY=1

# Delay identity to after expensive installs. Never recursively chown /workspace.
# Empty, owned mount targets seed named volumes, even under the Android bind.
RUN [[ "$LOCAL_UID" =~ ^[1-9][0-9]*$ && "$LOCAL_GID" =~ ^[1-9][0-9]*$ ]] && \
    if ! getent group "$LOCAL_GID" >/dev/null; then groupadd --gid "$LOCAL_GID" dev; fi && \
    useradd --uid "$LOCAL_UID" --gid "$LOCAL_GID" --create-home --shell /bin/bash dev && \
    chown "$LOCAL_UID:$LOCAL_GID" /workspace && \
    install -d -o "$LOCAL_UID" -g "$LOCAL_GID" \
      /home/dev/.gradle /home/dev/.cargo /home/dev/.cargo/registry /home/dev/.cargo/git /home/dev/.cache \
      /workspace/metro-cache /workspace/android/.gradle \
      /workspace/android/rust/target /workspace/android/rust/openssl

# Gradle native dependencies write generated files inside node_modules. COPY's
# ownership is limited to dependencies, rather than a project-wide chown pass.
COPY --from=dependencies --chown=${LOCAL_UID}:${LOCAL_GID} /workspace/node_modules/ ./node_modules/
COPY --from=dependencies /workspace/package.json ./package.json
COPY --from=legacy-build-tools /opt/android-sdk/build-tools/30.0.3/ /opt/android-sdk/build-tools/30.0.3/
# Final layers only: app/Babel edits and entrypoint edits keep dependency caches.
COPY --from=android-config /configuration/babel.config.js /configuration/app.json ./
COPY --chmod=0644 docker/adb-server.sh /usr/local/lib/bangumi/adb-server.sh
COPY --chmod=0644 docker/start-metro.cjs /usr/local/lib/bangumi/start-metro.cjs
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/bangumi-entrypoint
COPY --chmod=0644 docker/configure-debug-host.py /usr/local/lib/bangumi/configure-debug-host.py
COPY --chmod=0644 docker/build-rust.sh /usr/local/lib/bangumi/build-rust.sh

USER dev
ENTRYPOINT ["/usr/local/bin/bangumi-entrypoint"]
CMD ["metro"]
