#!/usr/bin/env bash
# VS Code 宿主初始化：构建镜像和生成本机 Compose 覆盖，不安装宿主依赖。
set -Eeuo pipefail
fail() { printf '[devcontainer] 错误：%s\n' "$*" >&2; exit 1; }
(( $# == 0 )) || fail '此脚本由 VS Code 初始化调用，不接受参数。'

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail '仅支持 Linux x86_64 宿主。'
uid="$(id -u)"
gid="$(id -g)"
[[ "$uid" =~ ^[1-9][0-9]*$ && "$gid" =~ ^[1-9][0-9]*$ ]] || fail '必须以非 root 用户和非 root 主用户组运行。'
[[ -z "${LOCAL_UID+x}" || "$LOCAL_UID" == "$uid" ]] || fail 'LOCAL_UID 与当前用户不一致，请取消设置。'
[[ -z "${LOCAL_GID+x}" || "$LOCAL_GID" == "$gid" ]] || fail 'LOCAL_GID 与当前用户组不一致，请取消设置。'
[[ -d "$root/.git" && ! -L "$root/.git" ]] || fail '仅支持 .git 为真实目录的普通 clone；外置 Git 目录或 worktree 不受支持。'

expected_project=bangumi-android-dev
[[ -z "${COMPOSE_PROJECT_NAME:-}" || "$COMPOSE_PROJECT_NAME" == "$expected_project" ]] || \
  fail 'COMPOSE_PROJECT_NAME 与项目要求不一致，请取消设置或设为 bangumi-android-dev。'
# VS Code CLI 会单独读取仓库根 .env；不执行该文件，也不输出其内容。
if [[ "${COMPOSE_PROJECT_NAME:-}" != "$expected_project" && -f "$root/.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ ! "$line" =~ ^COMPOSE_PROJECT_NAME=. ]] || \
      fail '仓库根 .env 设置了 COMPOSE_PROJECT_NAME；请在 VS Code 环境明确设置为 bangumi-android-dev。'
  done < "$root/.env"
fi
abi="${BANGUMI_ANDROID_ABI:-arm64-v8a}"
jobs="${BANGUMI_BUILD_JOBS:-4}"
[[ "$abi" == arm64-v8a ]] || fail '当前仅支持 arm64-v8a；x86_64 模拟器 ABI 尚未实现。'
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || fail 'BANGUMI_BUILD_JOBS 必须为正整数。'

command -v docker >/dev/null 2>&1 || fail '找不到 Docker CLI，请先安装 Docker Engine 与 Compose。'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose 插件不可用。'
docker info >/dev/null 2>&1 || \
  fail '当前用户无法访问 Docker daemon；VS Code 需要同样的 Docker 访问权限，请勿修改 socket 权限或使用 sudo code。'

# 只生成本机 Compose 覆盖；项目依赖和缓存由容器内正常流程创建。
for directory in "$root/docker/.generated"; do
  if [[ -L "$directory" || ( -e "$directory" && ! -d "$directory" ) ]]; then
    fail "挂载或配置目录必须是真实目录：$directory"
  fi
  if [[ ! -e "$directory" ]]; then mkdir -- "$directory" || fail "无法创建目录：$directory"; fi
  [[ -w "$directory" && -x "$directory" ]] || fail "目录不可写或不可进入，请先由用户修复权限：$directory"
done

printf '[devcontainer] 构建本地镜像 bangumi-android-dev:local（复用 Docker 层缓存）\n'
docker build --platform linux/amd64 --target dev \
  --build-arg "LOCAL_UID=$uid" --build-arg "LOCAL_GID=$gid" \
  --tag bangumi-android-dev:local --file "$root/docker/Dockerfile" "$root"

# 仅生成可验证的枚举和整数；不将宿主环境或密钥写入文件。
generated="$root/docker/.generated"
[[ ! -L "$generated" && -d "$generated" ]] || fail '生成目录不是安全的真实目录。'
temporary="$(mktemp "$generated/.compose.XXXXXXXX")"
trap '[[ -z "${temporary:-}" ]] || rm -f -- "$temporary"' EXIT
printf '%s\n' \
  'name: bangumi-android-dev' \
  'services:' \
  '  dev:' \
  "    user: \"$uid:$gid\"" \
  '    environment:' \
  "      BANGUMI_ANDROID_ABI: $abi" \
  "      BANGUMI_BUILD_JOBS: \"$jobs\"" > "$temporary"
mv -f -- "$temporary" "$generated/compose.yml"
temporary=''
printf '[devcontainer] 宿主初始化完成：bangumi-android-dev:local。\n'
