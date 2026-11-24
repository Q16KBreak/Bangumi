#!/usr/bin/env bash
# 保留 adb 原生参数界面，但禁止切换、杀死或替换共享 server。
set -euo pipefail

source /usr/local/lib/bangumi/adb-server.sh
source /usr/local/lib/bangumi/adb-manager.sh
[[ "${BANGUMI_CONTAINER:-}" == 1 ]] || { bangumi_adb_fail '只能在 Bangumi 开发容器中使用。'; exit 1; }
# 禁止继承外部 vendor key 路径和调试 trace，以免配对码或授权密钥进入日志。
unset ADB_TRACE ADB_VENDOR_KEYS

# 只解析 global options，远端 shell 的参数不应误当作 adb server 选项。
args=("$@")
while (( $# )); do
  case "$1" in
    -a|-H|-P|-L|-H?*|-P?*|-L?*|--one-device|--one-device=*)
      bangumi_adb_fail '禁止更改 ADB server 地址或限制其设备。'; exit 1 ;;
    -s|-t) (( $# >= 2 )) || { bangumi_adb_fail '设备选项缺少参数。'; exit 1; }; shift 2 ;;
    -s?*|-t?*|-d|-e|--exit-on-write-error) shift ;;
    *) break ;;
  esac
done
case "${1:-help}" in
  version|help|--help|-h)
    exec "$BANGUMI_ADB_REAL" "${args[@]}"
    ;;
  kill-server|server|nodaemon|fork-server)
    bangumi_adb_fail '禁止直接启动或停止 ADB server。'; exit 1 ;;
  start-server)
    (( $# == 1 )) || { bangumi_adb_fail 'start-server 不接受额外参数。'; exit 1; }
    bangumi_ensure_adb
    exit 0
    ;;
  pair)
    (( $# == 2 )) || { bangumi_adb_fail '配对码只能在交互终端输入，禁止通过参数传入。'; exit 1; }
    [[ -t 0 ]] || { bangumi_adb_fail '配对需要交互终端。'; exit 1; }
    ;;
esac
bangumi_ensure_adb
exec "$BANGUMI_ADB_REAL" "${args[@]}"
