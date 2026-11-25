#!/usr/bin/env bash
# @Author: Q16KBreak
#
# 单容器入口：保持工作台运行，或在仓库中启动 Metro / 编译。
set -Eeuo pipefail

fail() { printf '[bangumi] %s\n' "$*" >&2; exit 1; }

[[ "${BANGUMI_CONTAINER:-}" == 1 && "$(id -u)" != 0 ]] || \
  fail 'Run as the non-root Dev Container user, not on the host.'
cd /repo
export ADB_SERVER_SOCKET=tcp:127.0.0.1:5037
export BANGUMI_BUILD_JOBS="${BANGUMI_BUILD_JOBS:-4}"
export BANGUMI_ANDROID_ABI="${BANGUMI_ANDROID_ABI:-arm64-v8a}"
[[ "$BANGUMI_BUILD_JOBS" =~ ^[1-9][0-9]*$ ]] || fail 'BANGUMI_BUILD_JOBS must be a positive integer.'
[[ "$BANGUMI_ANDROID_ABI" == arm64-v8a ]] || \
  fail 'Only arm64-v8a Android devices are supported.'

require_writable_caches() {
  local directory
  for directory in "$@"; do
    mkdir -p "$directory"
    [[ -w "$directory" ]] || fail "Cache is not writable: $directory (check image UID/GID and existing volume ownership)."
  done
}

command="${1:-workbench}"
if (( $# )); then shift; fi
case "$command" in
  workbench)
    (( $# == 0 )) || fail 'workbench takes no arguments; open the real repository at /repo.'
    [[ -d /repo/.git ]] || fail 'The complete repository bind is missing; use docker/compose.yml.'
    # postCreate initializes dependencies; the ADB wrapper starts its server on demand.
    exec sleep infinity
    ;;
  metro)
    (( $# == 0 )) || fail 'metro takes no arguments; it serves the loopback development server on 127.0.0.1:8081.'
    node /usr/local/lib/bangumi/prepare-project.cjs check
    require_writable_caches metro-cache
    exec node /usr/local/lib/bangumi/start-metro.cjs
    ;;
  build)
    (( $# == 0 )) || fail 'build takes no arguments; it only runs Rust then assembleDebug.'
    node /usr/local/lib/bangumi/prepare-project.cjs check
    [[ -f android/gradlew && -f android/rust/Cargo.toml ]] || \
      fail 'The Android runtime bind is missing; use docker/compose.yml.'
    require_writable_caches "$GRADLE_USER_HOME" "$CARGO_HOME/registry" "$CARGO_HOME/git" \
      android/.gradle android/rust/target android/rust/openssl
    # Serialize Rust and Gradle over the real project directory, without ADB.
    exec 9>android/.gradle/bangumi-build.lock
    flock -n 9 || fail 'Another native build is already using this project.'
    node /usr/local/lib/bangumi/prepare-project.cjs configure
    bash /usr/local/lib/bangumi/build-rust.sh /repo
    cd android
    exec bash ./gradlew --no-daemon --console=plain assembleDebug
    ;;
  shell)
    cd /repo
    if (( $# )); then exec "$@"; fi
    exec /bin/bash
    ;;
  *)
    fail 'Usage: bangumi-entrypoint [workbench | metro | build | shell [command ...]]'
    ;;
esac
