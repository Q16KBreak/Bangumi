#!/usr/bin/env bash
# @Author: Q16KBreak
#
# 单容器入口：保持工作台运行，或在仓库中启动 Metro / 编译。
set -Eeuo pipefail

cd /repo

case "${1:-workbench}" in
  workbench)
    exec sleep infinity
    ;;
  metro)
    exec yarn expo start --localhost --port 8081
    ;;
  build)
    bash /usr/local/lib/bangumi/build-rust.sh /repo
    cd android
    exec bash ./gradlew --no-daemon --console=plain assembleDebug
    ;;
  shell)
    shift
    exec "${@:-/bin/bash}"
    ;;
  *)
    printf 'Usage: bangumi-entrypoint [workbench | metro | build | shell [command ...]]\n' >&2
    exit 1
    ;;
esac
