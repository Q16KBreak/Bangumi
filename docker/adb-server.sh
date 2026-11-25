#!/usr/bin/env bash
# @Author: Q16KBreak
#
# 只读探测 ADB smart socket，避免客户端自动启动或替换现有服务。

bangumi_adb_server_version() (
  local host="${1:-127.0.0.1}" port="${2:-5037}"
  local fd status length version
  if ! { exec {fd}<>"/dev/tcp/$host/$port"; } 2>/dev/null; then
    return 2
  fi
  printf '000chost:version' >&"$fd" || return 1
  IFS= read -r -N 4 -t 3 status <&"$fd" || return 1
  [[ "$status" == OKAY ]] || return 1
  IFS= read -r -N 4 -t 3 length <&"$fd" || return 1
  [[ "$length" =~ ^[0-9a-fA-F]{4}$ ]] || return 1
  (( 16#$length > 0 && 16#$length <= 8 )) || return 1
  IFS= read -r -N "$((16#$length))" -t 3 version <&"$fd" || return 1
  [[ "$version" =~ ^[0-9a-fA-F]{1,8}$ ]] || return 1
  printf '%d\n' "$((16#$version))"
)
