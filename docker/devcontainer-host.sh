#!/usr/bin/env bash
# VS Code 宿主初始化：构建与当前用户 UID/GID 匹配的镜像。
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

exec docker build --platform linux/amd64 --target dev \
  --build-arg "LOCAL_UID=$(id -u)" --build-arg "LOCAL_GID=$(id -g)" \
  --tag bangumi-android-dev:local --file "$root/docker/Dockerfile" "$root"
