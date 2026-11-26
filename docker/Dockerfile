# syntax=docker/dockerfile:1.7
# 一体化 Android 开发环境；源码、项目依赖与产物在运行时挂载。
# 固定工具版本集中于下方 ARG。
ARG BASE_IMAGE=debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
ARG JDK_VERSION=17
ARG NODE_VERSION=26.13.1
ARG YARN_VERSION=1.22.22
ARG ANDROID_TOOLS_BUILD=16111833
ARG ANDROID_API=34
ARG ANDROID_BUILD_TOOLS=33.0.0
ARG ANDROID_CMAKE=3.31.6
ARG RN_NDK_VERSION=23.1.7779620
ARG RUST_NDK_VERSION=30.0.16248370
ARG PLATFORM_TOOLS_VERSION=37.0.3
ARG RUSTUP_VERSION=1.29.3
ARG RUST_VERSION=1.100.0
ARG CARGO_NDK_VERSION=4.1.2
ARG OPENSSL_VERSION=4.0.1

# 系统工具 / JDK：其余下载阶段仅继承这层，而不互相依赖。
FROM --platform=linux/amd64 ${BASE_IMAGE} AS base
ARG JDK_VERSION
SHELL ["/bin/bash", "-Eeuo", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/java-${JDK_VERSION}-openjdk-amd64
RUN --mount=type=cache,id=bangumi-android-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=bangumi-android-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       bash build-essential ca-certificates curl git "openjdk-${JDK_VERSION}-jdk-headless" \
       perl pkg-config python3 unzip util-linux xz-utils zip

# Node
FROM base AS node
ARG NODE_VERSION
RUN --mount=type=tmpfs,target=/tmp/bangumi \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" -o /tmp/bangumi/node.tar.xz \
    && tar -xJf /tmp/bangumi/node.tar.xz -C /usr/local --strip-components=1

# Yarn：独立下载到 /opt，不让 Node 版本变化失效此阶段。
FROM base AS yarn
ARG YARN_VERSION
RUN --mount=type=tmpfs,target=/tmp/bangumi \
    curl -fsSL "https://registry.npmjs.org/yarn/-/yarn-${YARN_VERSION}.tgz" -o /tmp/bangumi/yarn.tgz \
    && mkdir -p /opt/yarn \
    && tar -xzf /tmp/bangumi/yarn.tgz -C /opt/yarn --strip-components=1

# Android SDK / NDK：_latest 是带固定构建编号的官方文件名。
FROM base AS android-sdk
ARG ANDROID_TOOLS_BUILD
ARG ANDROID_API
ARG ANDROID_BUILD_TOOLS
ARG ANDROID_CMAKE
ARG RN_NDK_VERSION
ARG RUST_NDK_VERSION
ARG PLATFORM_TOOLS_VERSION
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:${JAVA_HOME}/bin:${PATH}
RUN --mount=type=tmpfs,target=/tmp/bangumi \
    curl -fsSL "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_TOOLS_BUILD}_latest.zip" -o /tmp/bangumi/sdk.zip \
    && unzip -q /tmp/bangumi/sdk.zip -d /tmp/bangumi \
    && mkdir -p "$ANDROID_HOME/cmdline-tools" \
    && mv /tmp/bangumi/cmdline-tools "$ANDROID_HOME/cmdline-tools/latest"

# yes 的 SIGPIPE 不应掩盖 sdkmanager 自身的退出状态。
RUN (set +o pipefail; yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null) \
    && sdkmanager --sdk_root="$ANDROID_HOME" --install \
       "platforms;android-${ANDROID_API}" "build-tools;${ANDROID_BUILD_TOOLS}" \
       "cmake;${ANDROID_CMAKE}" \
       "ndk;${RN_NDK_VERSION}" "ndk;${RUST_NDK_VERSION}"

# 固定 platform-tools；sdkmanager 可能已隐式安装浮动版本。
RUN --mount=type=tmpfs,target=/tmp/bangumi \
    curl -fsSL "https://dl.google.com/android/repository/platform-tools_r${PLATFORM_TOOLS_VERSION}-linux.zip" -o /tmp/bangumi/adb.zip \
    && rm -rf /opt/android-sdk/platform-tools \
    && unzip -q /tmp/bangumi/adb.zip -d "$ANDROID_HOME"

# Rust：只启用当前支持的 ARM64 Android 构建目标。
FROM base AS rust
ARG RUSTUP_VERSION
ARG RUST_VERSION
ENV RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    RUSTUP_TOOLCHAIN=${RUST_VERSION}
ENV PATH=/opt/cargo/bin:${PATH}
RUN --mount=type=tmpfs,target=/tmp/bangumi \
    curl -fsSL "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" -o /tmp/bangumi/rustup-init \
    && chmod +x /tmp/bangumi/rustup-init \
    && /tmp/bangumi/rustup-init -y --no-modify-path --profile minimal \
       --default-toolchain "$RUST_VERSION" --target aarch64-linux-android

# cargo-ndk：使用官方预编译包，不依赖 Rust 阶段编译安装。
FROM base AS cargo-ndk
ARG CARGO_NDK_VERSION
RUN --mount=type=tmpfs,target=/tmp/bangumi \
    curl -fsSL "https://github.com/bbqsrc/cargo-ndk/releases/download/v${CARGO_NDK_VERSION}/cargo-ndk-x86_64-unknown-linux-musl-v${CARGO_NDK_VERSION}.tgz" -o /tmp/bangumi/cargo-ndk.tgz \
    && mkdir -p /opt/cargo-ndk \
    && tar -xzf /tmp/bangumi/cargo-ndk.tgz -C /opt/cargo-ndk --strip-components=1

FROM base AS openssl-source
ARG OPENSSL_VERSION
RUN mkdir -p /opt/openssl-src \
    && curl -fsSL "https://github.com/openssl/openssl/releases/download/openssl-${OPENSSL_VERSION}/openssl-${OPENSSL_VERSION}.tar.gz" \
    | tar -xz -C /opt/openssl-src --strip-components=1

# 开发用户与运行入口。项目 node_modules 由容器初始化写入真实仓库。
FROM base AS dev
ARG LOCAL_UID=1000
ARG LOCAL_GID=1000
ARG ANDROID_CMAKE
ARG RUST_NDK_VERSION
ARG RUST_VERSION
ENV HOME=/home/dev \
    CARGO_HOME=/home/dev/.cargo \
    RUSTUP_HOME=/opt/rustup \
    RUSTUP_TOOLCHAIN=${RUST_VERSION} \
    ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_NDK_HOME=/opt/android-sdk/ndk/${RUST_NDK_VERSION} \
    ANDROID_NDK_ROOT=/opt/android-sdk/ndk/${RUST_NDK_VERSION} \
    GRADLE_USER_HOME=/home/dev/.gradle \
    XDG_CACHE_HOME=/home/dev/.cache \
    YARN_CACHE_FOLDER=/home/dev/.cache/yarn \
    EXPO_NO_TELEMETRY=1 \
    BANGUMI_BUILD_JOBS=4
ENV PATH=/usr/local/bin:/opt/cargo/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/opt/android-sdk/cmake/${ANDROID_CMAKE}/bin:${JAVA_HOME}/bin:${PATH}

COPY --from=node /usr/local/ /usr/local/
COPY --from=yarn /opt/yarn/ /opt/yarn/
COPY --from=android-sdk --chown=${LOCAL_UID}:${LOCAL_GID} /opt/android-sdk/ /opt/android-sdk/
COPY --from=rust /opt/cargo/bin/ /opt/cargo/bin/
COPY --from=rust /opt/rustup/ /opt/rustup/
COPY --from=cargo-ndk /opt/cargo-ndk/ /opt/cargo/bin/
RUN ln -s /opt/yarn/bin/yarn /usr/local/bin/yarn \
    && ln -s /opt/yarn/bin/yarnpkg /usr/local/bin/yarnpkg \
    && groupadd --force --gid "$LOCAL_GID" dev \
    && useradd --uid "$LOCAL_UID" --gid "$LOCAL_GID" --create-home --shell /bin/bash dev \
    && install -d -m 0755 /usr/local/lib/bangumi \
    && install -d -o "$LOCAL_UID" -g "$LOCAL_GID" \
       /home/dev/.gradle /home/dev/.cargo /home/dev/.cargo/registry /home/dev/.cargo/git \
       /home/dev/.cache /home/dev/.cache/yarn /home/dev/.android /repo

COPY --from=openssl-source /opt/openssl-src/ /opt/openssl-src/
ARG OPENSSL_VERSION
ENV BANGUMI_OPENSSL_VERSION=${OPENSSL_VERSION}

COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/bangumi-entrypoint
COPY --chmod=0755 docker/develop.sh /usr/local/bin/bangumi
COPY --chmod=0644 docker/build-rust.sh /usr/local/lib/bangumi/build-rust.sh
COPY --chmod=0644 docker/prepare-project.cjs /usr/local/lib/bangumi/prepare-project.cjs

WORKDIR /repo
USER dev
ENTRYPOINT ["/usr/local/bin/bangumi-entrypoint"]
CMD ["workbench"]
