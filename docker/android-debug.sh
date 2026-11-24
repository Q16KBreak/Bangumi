#!/usr/bin/env bash
# 可选宿主兼容入口。正常开发直接在 VS Code 容器终端使用 bangumi。
# 宿主不需要 ADB、Node、JDK 或项目依赖，也不挂载 Docker socket 到容器。
set -euo pipefail

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
GENERATED="$DIR/.generated/compose.yml"

usage() {
  printf '%s\n' \
    '推荐：VS Code Reopen in Container，随后在容器终端使用 bangumi。' \
    '可选宿主入口：bash docker/android-debug.sh <命令> [参数]' \
    '  build-image    手动构建当前输入对应的镜像（仍使用缓存）' \
    '  up             启动工作台、准备依赖和 Metro' \
    '  down           停止本项目开发容器，保留仓库文件与卷' \
    '  shell          打开容器终端' \
    '  其他命令       转发到容器内 bangumi，如 build/start/pair/devices/logs'
}

compose() {
  local -a args=(--project-name bangumi-android-dev --file "$DIR/compose.yml")
  if [[ -f "$GENERATED" ]]; then args+=(--file "$GENERATED"); fi
  docker compose "${args[@]}" "$@"
}

command="${1:-help}"
(( $# == 0 )) || shift
case "$command" in
  help|-h|--help) usage ;;
  build-image)
    (( $# == 0 )) || { usage >&2; exit 1; }
    exec bash "$DIR/devcontainer-host.sh" --build-image
    ;;
  down)
    (( $# == 0 )) || { usage >&2; exit 1; }
    compose stop dev
    ;;
  up|shell|init|build|metro|pair|connect|devices|start|install|logs)
    bash "$DIR/devcontainer-host.sh"
    compose up --detach --wait --wait-timeout 120 dev
    # Code normally runs this through postStartCommand; the optional host path
    # must initialize as well. A matching managed dependency tree is only reused.
    compose exec -T dev /usr/local/bin/bangumi init
    case "$command" in
      shell) compose exec dev /bin/bash "$@" ;;
      pair)
        [[ -t 0 ]] || { printf '配对请使用交互终端；不要将配对码写入参数或聊天。\n' >&2; exit 1; }
        compose exec dev /usr/local/bin/bangumi pair "$@"
        ;;
      *) compose exec -T dev /usr/local/bin/bangumi "$command" "$@" ;;
    esac
    ;;
  *) usage >&2; exit 1 ;;
esac
