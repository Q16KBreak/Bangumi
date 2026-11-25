#!/usr/bin/env bash
# 容器内开发入口；编译、设备选择和 Metro 生命周期不依赖 Docker socket。
set -euo pipefail

BANGUMI_PROJECT_ROOT="${BANGUMI_PROJECT_ROOT:-/repo}"
BANGUMI_LIB=/usr/local/lib/bangumi
BANGUMI_ENTRYPOINT=/usr/local/bin/bangumi-entrypoint
ADB_BIN=/usr/local/bin/adb
APK="$BANGUMI_PROJECT_ROOT/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
DEBUG_PACKAGE=com.czy0729.bangumi.dev
DEBUG_PREFS=shared_prefs/com.czy0729.bangumi.dev_preferences.xml
COMPONENT=com.czy0729.bangumi.dev/com.czy0729.bangumi.MainActivity

fail() { printf '[bangumi] 错误：%s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' \
    '用法：bangumi <命令> [参数]' \
    '  init                       初始化 Android 配置和项目依赖' \
    '  start [IP:PORT|--device SERIAL]  选择设备、编译、安装并启动' \
    '  build                      编译 Rust/ECH 与 Android debug APK' \
    '  metro                      前台运行 Metro（127.0.0.1:8081）' \
    '  down                       停止 start 启动的后台 Metro' \
    '  help                       显示帮助' \
    '无线调试使用 adb pair、adb connect 和 adb devices -l。' \
    '多设备时必须指定 --device 或 ANDROID_SERIAL；目前仅支持 arm64-v8a。'
}
require_no_args() { (( $# == 0 )) || fail '此命令不接受参数，请查看 help。'; }
check_abi_config() {
  [[ "${BANGUMI_ANDROID_ABI:-arm64-v8a}" == arm64-v8a ]] || \
    fail '当前仅支持 BANGUMI_ANDROID_ABI=arm64-v8a；x86_64 模拟器构建尚未支持。'
}
check_endpoint() {
  local pattern='^([a-zA-Z0-9][a-zA-Z0-9._-]*|\[[0-9a-fA-F:.%]+\]):([0-9]{1,5})$'
  [[ "$1" =~ $pattern ]] || fail '地址格式应为 IP:PORT，IPv6 地址需使用 [地址]:PORT。'
  local port="${BASH_REMATCH[2]}"
  (( 10#$port >= 1 && 10#$port <= 65535 )) || fail '端口必须介于 1 和 65535。'
}

select_device() {
  local wanted="${1:-}" list line serial selected=''
  local pattern='^(.+)[[:space:]]+device([[:space:]]|$)'
  local -a devices=()
  list="$("$ADB_BIN" devices -l)" || fail '读取 ADB 设备列表失败，不会使用不完整结果。'
  while IFS= read -r line; do
    if [[ "$line" =~ $pattern ]]; then
      serial="${BASH_REMATCH[1]}"
      serial="${serial%"${serial##*[![:space:]]}"}"
      devices+=("$serial")
    fi
  done <<< "$list"
  if [[ -n "$wanted" ]]; then
    for serial in "${devices[@]}"; do [[ "$serial" == "$wanted" ]] && selected="$serial"; done
    [[ -n "$selected" ]] || fail '指定设备未在线，不会使用其他设备代替。'
  elif [[ -n "${ANDROID_SERIAL:-}" ]]; then
    for serial in "${devices[@]}"; do [[ "$serial" == "$ANDROID_SERIAL" ]] && selected="$serial"; done
    [[ -n "$selected" ]] || fail 'ANDROID_SERIAL 指定的设备未连接或未授权。'
  else
    (( ${#devices[@]} > 0 )) || fail '没有可用设备：请先配对或连接无线调试。'
    (( ${#devices[@]} == 1 )) || fail '检测到多台设备，请使用 --device 或 ANDROID_SERIAL，不会自动选择。'
    selected="${devices[0]}"
  fi
  printf '%s\n' "$selected"
}

# 设备 ABI 读取失败或未声明 arm64 时不得安装。
check_device_abi() {
  local serial="$1" abis
  abis="$("$ADB_BIN" -s "$serial" shell getprop ro.product.cpu.abilist)" || \
    fail '读取设备 ABI 失败，不会安装 APK。'
  abis="${abis//$'\r'/}"
  abis="${abis//[[:space:]]/}"
  [[ ",$abis," == *,arm64-v8a,* ]] || \
    fail '设备未声明 arm64-v8a；当前 APK 不支持该设备或 x86_64 模拟器。'
}
install_apk() {
  [[ -f "$APK" ]] || fail 'debug APK 不存在，请先执行 bangumi build。'
  check_device_abi "$1"
  "$ADB_BIN" -s "$1" install -r "$APK"
}
write_debug_prefs() {
  printf '%s' "$2" | base64 -d | "$ADB_BIN" -s "$1" shell -T run-as "$DEBUG_PACKAGE" dd "of=$DEBUG_PREFS"
}
configure_debug_prefs() {
  local serial="$1" snapshot old new had_prefs=0
  "$ADB_BIN" -s "$serial" shell am force-stop "$DEBUG_PACKAGE" || fail '停止开发包失败，不会修改偏好或启动应用。'
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
  new="$(printf '%s' "$old" | python3 "$BANGUMI_LIB/configure-debug-host.py")" \
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
      printf '警告：新建偏好可能留有不完整内容；不会自动删除文件，请手动修复。\n' >&2
    fi
    fail '写入 Metro 调试偏好失败，不会启动应用。'
  fi
}
metro_state_dir() {
  local state="/tmp/bangumi-dev-$(id -u)"
  [[ ! -L "$state" ]] || fail '状态目录不能是符号链接。'
  if [[ ! -d "$state" ]]; then (umask 077; mkdir -p -- "$state"); fi
  [[ -O "$state" && -w "$state" ]] || fail 'Metro 状态目录不可写或不属于当前用户。'
  chmod 700 "$state"
  printf '%s\n' "$state"
}
metro_owned_pid() {
  local file="$1" pid start stat rest cmd
  [[ -f "$file" && ! -L "$file" ]] || return 1
  read -r pid start < "$file" || return 1
  [[ "$pid" =~ ^[1-9][0-9]*$ && "$start" =~ ^[0-9]+$ && -r "/proc/$pid/stat" ]] || return 1
  IFS= read -r stat < "/proc/$pid/stat" || return 1
  rest="${stat##*) }"
  local -a fields
  read -ra fields <<< "$rest"
  [[ "${fields[19]:-}" == "$start" ]] || return 1
  cmd="$(tr '\0' '\n' < "/proc/$pid/cmdline")" || return 1
  [[ "$cmd" == *'/usr/local/lib/bangumi/start-metro.cjs'* ]] || return 1
  printf '%s\n' "$pid"
}
metro_owns_listener() {
  local pid="$1" slot local_address remote state queue timer retr uid timeout inode fd link
  [[ -r /proc/net/tcp && -d "/proc/$pid/fd" ]] || return 1
  while read -r slot local_address remote state queue timer retr uid timeout inode _; do
    [[ "$local_address" == 0100007F:1F91 && "$state" == 0A && "$inode" =~ ^[0-9]+$ ]] || continue
    for fd in "/proc/$pid/fd/"*; do
      link="$(readlink "$fd" 2>/dev/null)" || continue
      [[ "$link" == "socket:[$inode]" ]] && return 0
    done
  done < /proc/net/tcp
  return 1
}
metro_ready() {
  [[ "$(curl --silent --show-error --max-time 2 http://127.0.0.1:8081/status 2>/dev/null)" == 'packager-status:running' ]]
}
metro_port_free() {
  local file slot address remote status remaining
  for file in /proc/net/tcp /proc/net/tcp6; do
    [[ -r "$file" ]] || { [[ "$file" == /proc/net/tcp6 && ! -e "$file" ]] && continue; return 1; }
    while read -r slot address remote status remaining; do
      [[ "$status" == 0A && "${address##*:}" == 1F91 ]] && return 1
    done < "$file"
  done
  return 0
}
metro_up() {
  local state pid start stat rest i
  local -a fields
  state="$(metro_state_dir)"
  (
    flock -x 9
    pid="$(metro_owned_pid "$state/metro.pid" 2>/dev/null)" || pid=''
    if [[ -n "$pid" ]]; then
      for ((i=0; i<120; i++)); do
        if metro_owns_listener "$pid" && metro_ready; then exit 0; fi
        metro_owned_pid "$state/metro.pid" >/dev/null 2>&1 || break
        sleep 1
      done
      fail '本项目 Metro 进程仍在但尚未就绪或未拥有端口；请检查日志。'
    fi
    metro_port_free || fail '8081 已被其他进程占用；不会接管或结束它。'
    "$BANGUMI_ENTRYPOINT" metro 9>&- >"$state/metro.log" 2>&1 </dev/null &
    pid=$!
    # 先保存确切进程身份，避免 readiness 超时留下不可管理的进程。
    IFS= read -r stat < "/proc/$pid/stat" || fail '无法确认 Metro 进程身份。'
    rest="${stat##*) }"
    read -ra fields <<< "$rest"
    start="${fields[19]:-}"
    [[ "$start" =~ ^[0-9]+$ ]] || fail '无法读取 Metro 进程启动时间。'
    printf '%s %s\n' "$pid" "$start" > "$state/metro.pid"
    for ((i=0; i<120; i++)); do
      if ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid" 2>/dev/null || true
        fail "Metro 启动失败，请检查 $state/metro.log。"
      fi
      if metro_owned_pid "$state/metro.pid" >/dev/null 2>&1 && metro_owns_listener "$pid" && metro_ready; then exit 0; fi
      sleep 1
    done
    fail "Metro 未就绪，请检查 $state/metro.log；可用 bangumi down 停止已识别的 Metro。"
  ) 9>"$state/metro.lock"
}
metro_down() {
  local state pid
  state="$(metro_state_dir)"
  (
    flock -x 9
    pid="$(metro_owned_pid "$state/metro.pid" 2>/dev/null)" || pid=''
    if [[ -z "$pid" ]]; then printf '本项目 Metro 未运行。\n'; exit 0; fi
    metro_owns_listener "$pid" || fail '该 Metro 进程未拥有回环 8081，拒绝停止以避免误伤其他进程。'
    # 读取并验证启动时间、命令和监听 socket 后再次核对，再发送 TERM。
    [[ "$(metro_owned_pid "$state/metro.pid" 2>/dev/null)" == "$pid" ]] || fail 'Metro 进程已变化，拒绝停止。'
    kill -TERM "$pid" || fail '停止本项目 Metro 失败。'
    printf '已请求停止本项目 Metro。\n'
  ) 9>"$state/metro.lock"
}

main() {
  local command="${1:-help}" serial wanted='' endpoint=''
  (( $# == 0 )) || shift
  [[ "${BANGUMI_CONTAINER:-}" == 1 ]] || fail '请在 Bangumi 开发容器终端运行。'
  case "$command" in
    help|-h|--help) require_no_args "$@"; usage ;;
    init)
      require_no_args "$@"
      local state
      state="$(metro_state_dir)"
      exec flock "$state/deps.lock" node "$BANGUMI_LIB/prepare-project.cjs" init
      ;;
    build|metro) require_no_args "$@"; exec "$BANGUMI_ENTRYPOINT" "$command" ;;
    down) require_no_args "$@"; metro_down ;;
    start)
      if (( $# == 1 )); then
        check_endpoint "$1"; endpoint="$1"; wanted="$1"
      elif (( $# )); then
        [[ $# == 2 && "$1" == --device && -n "$2" ]] || fail '请使用 --device SERIAL 指定设备。'
        wanted="$2"
      fi
      [[ -z "$wanted" || -z "${ANDROID_SERIAL:-}" || "$ANDROID_SERIAL" == "$wanted" ]] || \
        fail 'ANDROID_SERIAL 与显式选择的设备不同，请统一目标。'
      check_abi_config
      if [[ -n "$endpoint" ]]; then "$ADB_BIN" connect "$endpoint"; fi
      serial="$(select_device "$wanted")"
      check_device_abi "$serial"
      metro_up
      "$BANGUMI_ENTRYPOINT" build
      install_apk "$serial"
      configure_debug_prefs "$serial"
      "$ADB_BIN" -s "$serial" reverse tcp:8081 tcp:8081 || fail '建立 Metro 反向端口失败，不会启动应用。'
      "$ADB_BIN" -s "$serial" shell am start -W -n "$COMPONENT"
      printf '已启动开发包：%s；Metro 通过 adb reverse 访问 127.0.0.1:8081。\n' "$serial"
      ;;
    *) fail "未知命令：$command，请查看 help。" ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
