#!/usr/bin/env bash
# bridge 网络下由官方 adb 按需启动 Server；这里只保护端口和配对码。
set -euo pipefail

fail() { printf '[bangumi-adb] %s\n' "$*" >&2; exit 1; }
[[ "${BANGUMI_CONTAINER:-}" == 1 ]] || fail '只能在 Bangumi 开发容器中使用。'
# tcp:PORT 无主机名，官方 adb 不带 -a 启动时只监听回环。
export ADB_SERVER_SOCKET=tcp:5037
# 禁止继承外部 vendor key 路径和调试 trace，以免配对码或授权密钥进入日志。
unset ADB_TRACE ADB_VENDOR_KEYS

# 只解析 global options，远端 shell 的参数不应误当作 adb server 选项。
args=("$@")
while (( $# )); do
  case "$1" in
    -a|-H|-P|-L|-H?*|-P?*|-L?*|--one-device|--one-device=*)
      fail '禁止更改 ADB Server 地址或限制其设备。' ;;
    -s|-t) (( $# >= 2 )) || fail '设备选项缺少参数。'; shift 2 ;;
    -s?*|-t?*|-d|-e|--exit-on-write-error) shift ;;
    *) break ;;
  esac
done
case "${1:-}" in
  kill-server|server|nodaemon|fork-server)
    fail '禁止直接运行 ADB Server 进程或关闭它。' ;;
  pair)
    (( $# == 2 )) || fail '配对码只能在交互终端输入，禁止通过参数传入。'
    [[ -t 0 ]] || fail '配对需要交互终端。'
    ;;
esac
exec /opt/android-sdk/platform-tools/adb "${args[@]}"
