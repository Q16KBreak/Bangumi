#!/usr/bin/env bash
set -euo pipefail

entrypoint=/usr/local/bin/bangumi-entrypoint
adb=/opt/android-sdk/platform-tools/adb
apk=/repo/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk

case "${1:-help}" in
  init) exec node /usr/local/lib/bangumi/prepare-project.cjs ;;
  build|metro) exec "$entrypoint" "$1" ;;
  start)
    case "${2:-}" in
      --device) serial="$3" ;;
      '') serial="$("$adb" get-serialno)" ;;
      *) serial="$2"; "$adb" connect "$serial" ;;
    esac

    if [[ "$("$adb" -s "$serial" get-state 2>/dev/null)" != device ]]; then
      printf '[bangumi] 设备不在线或未授权：%s\n' "$serial" >&2
      exit 1
    fi

    "$entrypoint" build
    "$adb" -s "$serial" install -r "$apk"
    "$adb" -s "$serial" reverse tcp:8081 tcp:8081
    exec "$adb" -s "$serial" shell am start -W -n \
      com.czy0729.bangumi.dev/com.czy0729.bangumi.MainActivity
    ;;
  help|-h|--help)
    printf '%s\n' '用法：bangumi init | build | metro | start [IP:PORT|--device SERIAL]' \
      '先在另一终端运行 bangumi metro，再运行 bangumi start。'
    ;;
  *) printf '[bangumi] 未知命令：%s\n' "$1" >&2; exit 1 ;;
esac
