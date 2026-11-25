#!/usr/bin/env bash
# @Author: Q16KBreak
#
# 从宿主编排 Android 开发容器与共享 ADB，不在宿主安装项目依赖。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
source "$DIR/adb-server.sh"
ADB_BIN="${BANGUMI_ADB_BIN:-adb}"
APK="$ROOT/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
DEBUG_PACKAGE='com.czy0729.bangumi.dev'
DEBUG_PREFS='shared_prefs/com.czy0729.bangumi.dev_preferences.xml'
COMPONENT='com.czy0729.bangumi.dev/com.czy0729.bangumi.MainActivity'

fail() { printf '错误：%s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' \
    '用法：bash docker/android-debug.sh <命令> [参数]' \
    '  build-image       构建工具链和依赖镜像（配置或依赖变化后执行）' \
    '  up                启动 Metro 和共享 ADB server；镜像不存在时自动构建，不需要连接手机' \
    '  pair IP:PORT      在宿主交互配对手机（输入配对端口）' \
    '  start [IP:PORT]   连接手机、启动 Metro、编译安装、建立 reverse 并启动应用' \
    '  build             编译 Rust/ECH 和 debug APK，无需连接手机' \
    '  install           将已编译 APK 安装到所选手机，不删除应用数据' \
    '  devices           列出宿主 ADB 设备与 mDNS 服务' \
    '  logs              查看所选手机 React Native / Android 错误日志' \
    '  down              停止开发容器，保留缓存和宿主 ADB server' \
    '  help              显示帮助' \
    '' \
    '可选环境变量：ANDROID_SERIAL、BANGUMI_ADB_BIN、LOCAL_UID、LOCAL_GID、BANGUMI_BUILD_JOBS。' \
    'Metro 只监听 127.0.0.1:8081，手机通过 adb reverse tcp:8081 访问该端口，不需要宿主 IPv4。' \
    '无 Docker socket 权限时设置 DOCKER_USE_SUDO=1，不必修改 socket 或用户组。' \
    '无线调试端口和配对端口不同；多台设备必须设置 ANDROID_SERIAL 或使用 start IP:PORT。' \
    'start 只重建所选手机的 tcp:8081 映射，不删除设备上的其他 reverse 映射。'
}

check_args() {
  local count="$1" min="$2" max="$3"
  (( count >= min && count <= max )) || fail '参数数量不正确，请查看 help。'
}

check_endpoint() {
  local pattern='^([a-zA-Z0-9][a-zA-Z0-9._-]*|\[[0-9a-fA-F:.%]+\]):([0-9]{1,5})$'
  [[ "$1" =~ $pattern ]] || fail '地址格式应为 IP:PORT，IPv6 地址需使用 [地址]:PORT。'
  local port="${BASH_REMATCH[2]}"
  (( 10#$port >= 1 && 10#$port <= 65535 )) || fail '端口必须介于 1 和 65535。'
}

check_adb() {
  command -v "$ADB_BIN" >/dev/null 2>&1 || fail '未找到宿主 adb，请安装 platform-tools 37.0.1 或设置 BANGUMI_ADB_BIN。'
  local version
  version="$("$ADB_BIN" version)"
  [[ "$version" == *'Android Debug Bridge version 1.0.41'* ]] || fail '宿主 adb 协议不是 1.0.41，请统一 platform-tools 版本。'
  [[ "$version" == *'Version 37.0.1-'* ]] || fail '请使用与镜像一致的 platform-tools 37.0.1，避免不同客户端争用服务。'
  export ADB_SERVER_SOCKET=tcp:127.0.0.1:5037
}

ensure_server() {
  check_adb
  local protocol result
  if protocol="$(bangumi_adb_server_version)"; then
    [[ "$protocol" == 41 ]] || fail "现有 ADB server 协议为 $protocol，不会自动重启，请自行统一版本。"
    return
  else
    result="$?"
  fi
  [[ "$result" == 2 ]] || fail '5037 端口不是可用的 ADB server，或响应超时；不会自动替换服务。'
  "$ADB_BIN" start-server
  protocol="$(bangumi_adb_server_version)" || fail '宿主 ADB server 启动后未通过只读协议检查。'
  [[ "$protocol" == 41 ]] || fail '宿主 ADB server 协议不兼容。'
}

check_docker() {
  command -v docker >/dev/null 2>&1 || fail '未安装 Docker Engine / Compose 插件。'
  DOCKER=(docker)
  case "${DOCKER_USE_SUDO:-0}" in
    0) ;;
    1) command -v sudo >/dev/null 2>&1 || fail '未找到 sudo。' ;;
    *) fail 'DOCKER_USE_SUDO 只能是 0 或 1。' ;;
  esac
  export LOCAL_UID="${LOCAL_UID:-${SUDO_UID:-$(id -u)}}"
  export LOCAL_GID="${LOCAL_GID:-${SUDO_GID:-$(id -g)}}"
  [[ "$LOCAL_UID" =~ ^[0-9]+$ && "$LOCAL_GID" =~ ^[0-9]+$ ]] || fail 'LOCAL_UID / LOCAL_GID 必须为数字。'
  (( LOCAL_UID > 0 && LOCAL_GID > 0 )) || fail '容器开发用户不能是 root，请指定非零 LOCAL_UID / LOCAL_GID。'
  export BANGUMI_BUILD_JOBS="${BANGUMI_BUILD_JOBS:-4}"
  [[ "$BANGUMI_BUILD_JOBS" =~ ^[1-9][0-9]*$ ]] || fail 'BANGUMI_BUILD_JOBS 必须为正整数。'
  if [[ "${DOCKER_USE_SUDO:-0}" == 1 ]]; then
    DOCKER=(sudo env "LOCAL_UID=$LOCAL_UID" "LOCAL_GID=$LOCAL_GID" "BANGUMI_BUILD_JOBS=$BANGUMI_BUILD_JOBS")
    # sudo 默认清理环境，只传递 Compose 所需的用户与构建并发白名单。
    DOCKER+=(docker)
  fi
  "${DOCKER[@]}" compose version >/dev/null || fail 'Docker Compose 插件不可用。'
}

compose() {
  "${DOCKER[@]}" compose --project-name bangumi-android-dev --file "$DIR/compose.yml" "$@"
}

up() {
  compose up --detach --wait --wait-timeout 120 dev || {
    compose logs --tail 60 dev >&2 || true
    fail '开发容器启动失败，请检查 Docker 权限、宿主 8081 端口和容器日志。'
  }
}

build() {
  local running
  running="$(compose ps --status running --quiet dev)" || fail '读取开发容器状态失败。'
  if [[ -n "$running" ]]; then
    # 原生依赖会写 node_modules 下的 build/.cxx，复用服务容器可保留这些增量产物。
    compose exec -T dev /usr/local/bin/bangumi-entrypoint build
  else
    compose run --rm --no-deps -T dev build
  fi
}

select_device() {
  local wanted="${1:-}" list line serial selected=''
  local pattern='^(.+)[[:space:]]+device([[:space:]]|$)'
  local -a devices=()
  list="$("$ADB_BIN" devices -l)" || fail '读取 ADB 设备列表失败，不会使用不完整结果。'
  while IFS= read -r line; do
    # mDNS 实例名可能包含空格，不能按空白把序列号拆成多个字段。
    if [[ "$line" =~ $pattern ]]; then
      serial="${BASH_REMATCH[1]}"
      serial="${serial%"${serial##*[![:space:]]}"}"
      devices+=("$serial")
    fi
  done <<< "$list"
  if [[ -n "$wanted" ]]; then
    # start 的显式地址既是连接目标也是选择目标；同一手机的 IP 与 mDNS 两条记录不影响选择。
    for serial in "${devices[@]}"; do
      [[ "$serial" == "$wanted" ]] && selected="$serial"
    done
    [[ -n "$selected" ]] || fail '指定无线调试地址未在线，不会使用其他设备代替。'
  elif [[ -n "${ANDROID_SERIAL:-}" ]]; then
    for serial in "${devices[@]}"; do
      [[ "$serial" == "$ANDROID_SERIAL" ]] && selected="$serial"
    done
    [[ -n "$selected" ]] || fail 'ANDROID_SERIAL 指定的手机未连接或未授权，请查看 devices。'
  else
    (( ${#devices[@]} > 0 )) || fail '没有可用手机：请开启无线调试并完成 pair / connect，或指定 start IP:PORT。'
    (( ${#devices[@]} == 1 )) || fail '检测到多台手机，请设置 ANDROID_SERIAL，不会自动选择。'
    selected="${devices[0]}"
  fi
  printf '%s\n' "$selected"
}

install_apk() {
  [[ -f "$APK" ]] || fail 'debug APK 不存在，请先执行 build。'
  "$ADB_BIN" -s "$1" install -r "$APK"
}

write_debug_prefs() {
  printf '%s' "$2" | base64 -d | "$ADB_BIN" -s "$1" shell -T run-as "$DEBUG_PACKAGE" dd "of=$DEBUG_PREFS"
}

configure_debug_prefs() {
  local serial="$1" snapshot old new had_prefs=0
  command -v base64 >/dev/null 2>&1 || fail '未找到宿主 coreutils base64，不能安全配置开发包。'
  # 安装 -r 不清数据；先停开发包，防止内存中的 SharedPreferences 覆盖新文件。
  "$ADB_BIN" -s "$serial" shell am force-stop "$DEBUG_PACKAGE" || fail '停止开发包失败，不会修改偏好或启动应用。'
  # sh -c 的引号必须传给设备端 shell；包名和私有相对路径均为固定值。
  snapshot="$("$ADB_BIN" -s "$serial" shell -T run-as "$DEBUG_PACKAGE" sh -c \
    "'if [ -f $DEBUG_PREFS ]; then printf present:; base64 $DEBUG_PREFS; elif [ -e $DEBUG_PREFS ]; then exit 1; else printf missing:; fi'")" \
    || fail '读取开发包已有偏好失败，不会覆盖文件或启动应用。'
  case "$snapshot" in
    present:*) had_prefs=1; old="${snapshot#present:}" ;;
    missing:) old='' ;;
    *) fail '读取开发包偏好返回格式异常，不会覆盖文件或启动应用。' ;;
  esac
  old="${old//$'\r'/}"; old="${old//$'\n'/}"
  printf '%s' "$old" | base64 -d >/dev/null || fail '已有偏好不是有效 base64，不会覆盖文件或启动应用。'
  # helper 固定写入 127.0.0.1:8081（配合 adb reverse），宿主不再传地址参数。
  new="$(printf '%s' "$old" | compose exec -T dev python3 /usr/local/lib/bangumi/configure-debug-host.py)" \
    || fail '生成 Metro 调试偏好失败，保留原文件且不会启动应用。'
  [[ -n "$new" ]] || fail '生成的 Metro 调试偏好为空，保留原文件且不会启动应用。'
  printf '%s' "$new" | base64 -d >/dev/null || fail '生成的 Metro 调试偏好不是有效 base64，保留原文件且不会启动应用。'
  "$ADB_BIN" -s "$serial" shell -T run-as "$DEBUG_PACKAGE" mkdir -p shared_prefs \
    || fail '创建开发包私有 shared_prefs 失败，不会启动应用。'
  if ! write_debug_prefs "$serial" "$new"; then
    if (( had_prefs )); then
      if write_debug_prefs "$serial" "$old"; then
        printf '已恢复开发包原有偏好。\n' >&2
      else
        printf '警告：恢复开发包原有偏好也失败，请检查 run-as 权限及设备存储。\n' >&2
      fi
    else
      printf '警告：新建偏好可能留有不完整内容；不会自动删除文件，请检查 run-as 权限及设备存储，手动修复该文件后再执行 start。\n' >&2
    fi
    fail '写入 Metro 调试偏好失败，不会启动应用；修复后请重新执行 start。'
  fi
}

check_screen_ready() {
  local serial="$1" power='' policy=''
  # 只读查询：power 取休眠/Doze，window policy 只取锁屏策略；失败只提醒，不唤醒、解锁或修改省电/网络策略。
  power="$("$ADB_BIN" -s "$serial" shell dumpsys power 2>/dev/null)" || power=''
  policy="$("$ADB_BIN" -s "$serial" shell dumpsys window policy 2>/dev/null)" || policy=''
  if [[ -z "$power" && -z "$policy" ]]; then
    printf '提示：无法读取手机屏幕/锁屏状态；请确认手机已亮屏解锁，应用启动后可能不在前台。\n' >&2
  elif [[ "$power" == *mWakefulness=Asleep* || "$power" == *mWakefulness=Dreaming* ||
          "$power" == *mWakefulness=Dozing* ||
          "$policy" == *showing=true* ||
          "$policy" == *mShowingLockscreen=true* || "$policy" == *mDreamingLockscreen=true* ]]; then
    printf '警告：手机可能处于休眠、锁屏或 Doze 状态，应用启动后可能不可见；请亮屏解锁后查看。\n' >&2
  fi
  printf '提示：请让手机保持前台亮屏，便于观察 Metro 加载与热更新。\n' >&2
}

main() {
  local command="${1:-help}" serial
  (( $# == 0 )) || shift
  case "$command" in
    help|-h|--help) check_args "$#" 0 0; usage ;;
    pair)
      check_args "$#" 1 1; check_endpoint "$1"; ensure_server
      [[ -t 0 ]] || fail '配对需要交互终端，请在宿主终端运行 pair；不要把配对码放入命令参数。'
      "$ADB_BIN" pair "$1"
      ;;
    devices)
      check_args "$#" 0 0; ensure_server
      "$ADB_BIN" devices -l
      "$ADB_BIN" mdns services
      ;;
    build-image) check_args "$#" 0 0; check_docker; compose --progress plain build dev ;;
    up) check_args "$#" 0 0; ensure_server; check_docker; up ;;
    build) check_args "$#" 0 0; check_docker; build ;;
    install)
      check_args "$#" 0 0; ensure_server; serial="$(select_device)"; install_apk "$serial"
      ;;
    start)
      check_args "$#" 0 1
      if (( $# )); then
        check_endpoint "$1"
        [[ -z "${ANDROID_SERIAL:-}" || "$ANDROID_SERIAL" == "$1" ]] || fail 'ANDROID_SERIAL 与 start 地址不同，请统一目标。'
      fi
      ensure_server
      if (( $# )); then "$ADB_BIN" connect "$1"; fi
      # adb connect 可能打印连接失败却返回 0；显式地址同时是选择目标，绝不退回其他设备。
      serial="$(select_device "${1:-}")"
      check_docker; up; build; install_apk "$serial"
      configure_debug_prefs "$serial"
      # 仅重建所选手机本项目的 tcp:8081；不使用 --remove-all，避免删除未知 reverse 映射。
      "$ADB_BIN" -s "$serial" reverse tcp:8081 tcp:8081 \
        || fail '建立 Metro 反向端口（adb reverse tcp:8081）失败，不会启动应用。'
      check_screen_ready "$serial"
      "$ADB_BIN" -s "$serial" shell am start -W -n "$COMPONENT"
      printf '已启动开发包：%s；Metro 通过 adb reverse 访问 127.0.0.1:8081。使用 logs 查看设备日志。\n' "$serial"
      ;;
    logs)
      check_args "$#" 0 0; ensure_server; serial="$(select_device)"
      exec "$ADB_BIN" -s "$serial" logcat ReactNative:V ReactNativeJS:V AndroidRuntime:E '*:S'
      ;;
    down) check_args "$#" 0 0; check_docker; compose down ;;
    *) fail "未知命令：$command，请查看 help。" ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
