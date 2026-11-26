#!/usr/bin/env bash
# Bangumi ECH Proxy - Linux 容器内交叉编译（OpenSSL ECH + Rust JNI）。
#
# 用法:
#   bash /usr/local/lib/bangumi/build-rust.sh [PROJECT_ROOT]   # 默认 /repo
#
# Rust、cargo-ndk、Rust NDK 和 OpenSSL 源码由镜像提供。
set -Eeuo pipefail

PROJECT_ROOT="${1:-/repo}"
RUST_DIR="$PROJECT_ROOT/android/rust"
JNILIBS_DIR="$PROJECT_ROOT/android/app/src/main/jniLibs/arm64-v8a"
OPENSSL_ROOT="$RUST_DIR/openssl/$BANGUMI_OPENSSL_VERSION/${ANDROID_NDK_HOME##*/}"
OPENSSL_SRC=/opt/openssl-src
OPENSSL_BUILD="$OPENSSL_ROOT/objects"
OPENSSL_PREFIX="$OPENSSL_ROOT/install"
mkdir -p "$OPENSSL_BUILD"
(
  cd "$OPENSSL_BUILD"
  export PATH="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
  if [ ! -f Makefile ]; then
    "$OPENSSL_SRC/Configure" android-arm64 -D__ANDROID_API__=21 \
      --prefix="$OPENSSL_PREFIX" \
      --openssldir="$OPENSSL_PREFIX" \
      --libdir=lib threads no-shared no-tests
  fi
  make -j"$BANGUMI_BUILD_JOBS"
  make install_sw
)

(
  cd "$RUST_DIR"
  OPENSSL_DIR="$OPENSSL_PREFIX" OPENSSL_STATIC=1 \
    cargo ndk -t arm64-v8a --platform 21 build --release --locked
)

SO_FILE="$RUST_DIR/target/aarch64-linux-android/release/libechproxy.so"
mkdir -p "$JNILIBS_DIR"
cp "$SO_FILE" "$JNILIBS_DIR/libechproxy.so"
