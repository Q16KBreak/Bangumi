#!/usr/bin/env bash
# Bangumi ECH Proxy - Linux 容器内交叉编译（OpenSSL ECH + Rust JNI）。
#
# 用法:
#   bash /usr/local/lib/bangumi/build-rust.sh [PROJECT_ROOT]   # 默认 /workspace
#
# 镜像已预装 Rust 1.100 / cargo-ndk / NDK 27.1, 这里只做编译, 不再安装工具链。
set -Eeuo pipefail

OPENSSL_VERSION=4.0.1
PROJECT_ROOT="${1:-/workspace}"
RUST_DIR="$PROJECT_ROOT/android/rust"
JNILIBS_DIR="$PROJECT_ROOT/android/app/src/main/jniLibs/arm64-v8a"
OPENSSL_ROOT="$RUST_DIR/openssl"
OPENSSL_SRC="$OPENSSL_ROOT/build/openssl-$OPENSSL_VERSION"
OPENSSL_PREFIX="$OPENSSL_ROOT/install"
# 使用镜像指定的 Rust NDK，独立于 Gradle 的 RN NDK。
NDK="${ANDROID_NDK_HOME:-${ANDROID_HOME:-/opt/android-sdk}/ndk/27.1.12297006}"
TOOLCHAIN_BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"

log() { printf '[build-rust] %s\n' "$*"; }
die() { printf '[build-rust] error: %s\n' "$*" >&2; exit 1; }

export ANDROID_NDK_HOME="$NDK"
export ANDROID_NDK_ROOT="$NDK"
export PATH="$TOOLCHAIN_BIN:$PATH"

JOBS="${BANGUMI_BUILD_JOBS:-$(nproc)}"

# no-threads 的 libcrypto 会让多线程代理崩溃: 检查 threads_pthread.o 里是否有锁符号。
openssl_threads_ok() {
  "$TOOLCHAIN_BIN/llvm-ar" p "$OPENSSL_PREFIX/lib/libcrypto.a" \
    libcrypto-lib-threads_pthread.o 2>/dev/null \
    | "$TOOLCHAIN_BIN/llvm-nm" --defined-only - 2>/dev/null \
    | grep -F 'CRYPTO_THREAD_write_lock' >/dev/null
}

export OPENSSL_DIR="$OPENSSL_PREFIX"
export OPENSSL_INCLUDE_DIR="$OPENSSL_PREFIX/include"
export OPENSSL_LIB_DIR="$OPENSSL_PREFIX/lib"
export OPENSSL_STATIC=1

if [ -f "$OPENSSL_PREFIX/lib/libssl.a" ] && [ -f "$OPENSSL_PREFIX/.threads-ok" ]; then
  log "OpenSSL 已编译且 threads 已校验, 复用缓存"
else
  if [ ! -f "$OPENSSL_SRC/Configure" ]; then
    log "下载 OpenSSL $OPENSSL_VERSION ..."
    mkdir -p "$OPENSSL_ROOT/build"
    if ! curl --fail --location \
      "https://github.com/openssl/openssl/releases/download/openssl-$OPENSSL_VERSION/openssl-$OPENSSL_VERSION.tar.gz" \
      | tar xz -C "$OPENSSL_ROOT/build"; then
      die "OpenSSL 下载或解压失败"
    fi
  fi

  log "编译 OpenSSL $OPENSSL_VERSION (android-arm64, API 21, threads) ..."
  mkdir -p "$OPENSSL_PREFIX"
  # 独立子 shell: 不加 || 判断, 让 set -e 在 Configure/make 失败时直接传播。
  (
    cd "$OPENSSL_SRC"
    # 不能传 -static: OpenSSL 4.0 会因此隐式 disable threads, 并发代理必崩;
    # 静态库能力由 no-shared + OPENSSL_STATIC=1 保证。
    ./Configure android-arm64 -D__ANDROID_API__=21 \
      --prefix="$OPENSSL_PREFIX" \
      --openssldir="$OPENSSL_PREFIX" \
      no-shared \
      no-tests
    make clean >/dev/null 2>&1 || true
    make -j"$JOBS"
    make install_sw
  )
  openssl_threads_ok || die "OpenSSL 缺少多线程支持 (no-threads), 请检查 Configure 参数"
  touch "$OPENSSL_PREFIX/.threads-ok"
  log "OpenSSL 多线程校验通过"
fi

log "编译 ech-proxy (cargo ndk, arm64-v8a, API 21, --locked) ..."
(cd "$RUST_DIR" && cargo ndk -t arm64-v8a --platform 21 build --release --locked) \
  || die "cargo ndk 编译失败"

SO_FILE="$RUST_DIR/target/aarch64-linux-android/release/libechproxy.so"
[ -f "$SO_FILE" ] || die "编译产物未找到: $SO_FILE"

mkdir -p "$JNILIBS_DIR"
cp "$SO_FILE" "$JNILIBS_DIR/libechproxy.so"
log "已复制到 $JNILIBS_DIR/libechproxy.so"
