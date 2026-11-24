#!/usr/bin/env bash
# ADB 服务仅绑定回环；容器模式只管理自己启动的前台 server。

BANGUMI_ADB_REAL=/opt/android-sdk/platform-tools/adb
export ADB_SERVER_SOCKET=tcp:127.0.0.1:5037

bangumi_adb_fail() { printf '[bangumi-adb] %s\n' "$*" >&2; return 1; }

bangumi_adb_state_dir() {
  local state="/tmp/bangumi-dev-$(id -u)"
  [[ ! -L "$state" ]] || { bangumi_adb_fail '状态目录不能是符号链接。'; return 1; }
  if [[ ! -d "$state" ]]; then
    (umask 077; mkdir -p -- "$state") || return 1
  fi
  [[ -O "$state" && -w "$state" ]] || { bangumi_adb_fail '状态目录不可写或不属于当前用户。'; return 1; }
  chmod 700 "$state" || return 1
  printf '%s\n' "$state"
}

bangumi_adb_owned_pid() {
  local file="$1" pid exe expected start
  [[ -f "$file" && ! -L "$file" ]] || return 1
  read -r pid start < "$file" || return 1
  [[ "$pid" =~ ^[1-9][0-9]*$ && "$start" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/$pid/stat" ]] || return 1
  exe="$(readlink -f "/proc/$pid/exe" 2>/dev/null)" || return 1
  expected="$(readlink -f "$BANGUMI_ADB_REAL" 2>/dev/null)" || return 1
  [[ "$exe" == "$expected" ]] || return 1
  local -a command
  mapfile -d '' -t command < "/proc/$pid/cmdline" || return 1
  [[ "${command[1]:-}" == '-L' && "${command[2]:-}" == 'tcp:5037' && \
     "${command[3]:-}" == 'nodaemon' && "${command[4]:-}" == 'server' ]] || return 1
  # /proc stat 字段 22 是进程启动时间；comm 可能包含空格和括号。
  local stat rest
  IFS= read -r stat < "/proc/$pid/stat" || return 1
  rest="${stat##*) }"
  local -a fields
  read -ra fields <<< "$rest"
  [[ "${fields[19]:-}" == "$start" ]] || return 1
  printf '%s\n' "$pid"
}

# 只信任该进程实际持有的 127.0.0.1:5037 LISTEN socket。
bangumi_adb_owns_listener() {
  local pid="$1" slot local_address remote state queue timer retr uid timeout inode fd link
  [[ -r /proc/net/tcp && -d "/proc/$pid/fd" ]] || return 1
  while read -r slot local_address remote state queue timer retr uid timeout inode _; do
    [[ "$local_address" == 0100007F:13AD && "$state" == 0A && "$inode" =~ ^[0-9]+$ ]] || continue
    for fd in "/proc/$pid/fd/"*; do
      link="$(readlink "$fd" 2>/dev/null)" || continue
      [[ "$link" == "socket:[$inode]" ]] && return 0
    done
  done < /proc/net/tcp
  return 1
}

bangumi_adb_port_available() {
  local file slot address remote state remaining
  for file in /proc/net/tcp /proc/net/tcp6; do
    [[ -r "$file" ]] || { [[ "$file" == /proc/net/tcp6 && ! -e "$file" ]] && continue; return 1; }
    while read -r slot address remote state remaining; do
      [[ "$state" == 0A && "${address##*:}" == 13AD ]] && return 1
    done < "$file"
  done
  return 0
}

bangumi_adb_process_start() {
  local pid="$1" stat rest
  IFS= read -r stat < "/proc/$pid/stat" || return 1
  rest="${stat##*) }"
  local -a fields
  read -ra fields <<< "$rest"
  [[ "${fields[19]:-}" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "${fields[19]}"
}

bangumi_ensure_adb() {
  local mode="${BANGUMI_ADB_SERVER_MODE:-container}" state protocol rc pid start i
  [[ "${BANGUMI_CONTAINER:-}" == 1 ]] || { bangumi_adb_fail '只能在 Bangumi 开发容器中使用。'; return 1; }
  case "$mode" in
    host)
      protocol="$(bangumi_adb_server_version 127.0.0.1 5037)" || {
        bangumi_adb_fail '宿主 ADB server 不可用；host 模式不会启动或替换它。'; return 1;
      }
      [[ "$protocol" == 41 ]] || { bangumi_adb_fail '宿主 ADB 协议不兼容（需要 41）；不会替换服务。'; return 1; }
      return 0
      ;;
    container) ;;
    *) bangumi_adb_fail 'BANGUMI_ADB_SERVER_MODE 只能为 container 或 host。'; return 1 ;;
  esac

  state="$(bangumi_adb_state_dir)" || return 1
  (
    flock -x 9 || exit 1
    pid="$(bangumi_adb_owned_pid "$state/adb.pid" 2>/dev/null)" || pid=''
    if [[ -n "$pid" ]]; then
      for ((i=0; i<50; i++)); do
        if protocol="$(bangumi_adb_server_version 127.0.0.1 5037)"; then
          [[ "$protocol" == 41 ]] || { bangumi_adb_fail '本容器 ADB 协议异常。'; exit 1; }
          bangumi_adb_owns_listener "$pid" || {
            bangumi_adb_fail '5037 不属于本容器 ADB 进程，不会误用外部服务。'; exit 1;
          }
          exit 0
        fi
        bangumi_adb_owned_pid "$state/adb.pid" >/dev/null || break
        sleep 0.1
      done
      bangumi_adb_fail '本容器 ADB 进程仍在但服务不可用；不会启动替代进程。'
      exit 1
    fi

    if protocol="$(bangumi_adb_server_version 127.0.0.1 5037)"; then
      bangumi_adb_fail '5037 已被非本容器 ADB 服务占用；如需共用宿主设备，请选择 host 模式重建容器。'
      exit 1
    else
      rc=$?
      [[ "$rc" == 2 ]] || { bangumi_adb_fail '5037 已被未知服务占用或无效；不会替换。'; exit 1; }
    fi
    bangumi_adb_port_available || {
      bangumi_adb_fail '5037 已存在监听服务，可能仅监听 IPv6；不会启动或替换它。'; exit 1;
    }

    # socket 竞争由 adb server 自行处理；不使用 start-server 或 kill-server。
    # The listen socket syntax accepts only tcp:PORT; without -a adb binds loopback.
    # A host name is valid for client sockets but aborts real platform-tools 37.
    "$BANGUMI_ADB_REAL" -L tcp:5037 nodaemon server 9>&- >"$state/adb.log" 2>&1 </dev/null &
    pid=$!
    start="$(bangumi_adb_process_start "$pid")" || {
      bangumi_adb_fail '无法读取新 ADB 进程身份。'; exit 1;
    }
    printf '%s %s\n' "$pid" "$start" > "$state/adb.pid"
    for ((i=0; i<50; i++)); do
      if ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid" 2>/dev/null || true
        bangumi_adb_fail '容器 ADB server 启动失败或端口发生竞争；不会替换外部服务。'
        exit 1
      fi
      if protocol="$(bangumi_adb_server_version 127.0.0.1 5037)"; then
        [[ "$protocol" == 41 ]] || { bangumi_adb_fail 'ADB server 协议不兼容。'; exit 1; }
        # 前台进程存活不足以证明它占有端口：核对自己的监听 socket inode。
        bangumi_adb_owned_pid "$state/adb.pid" >/dev/null && bangumi_adb_owns_listener "$pid" || {
          bangumi_adb_fail 'ADB 监听端口不属于本容器进程，可能发生端口竞争。'; exit 1;
        }
        exit 0
      fi
      sleep 0.1
    done
    bangumi_adb_fail "容器 ADB server 未就绪；请检查 $state/adb.log。"
    exit 1
  ) 9>"$state/adb.lock"
}
