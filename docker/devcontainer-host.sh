#!/usr/bin/env bash
# VS Code 宿主初始化：只准备挂载目录、镜像和本机 Compose 覆盖，不安装宿主依赖。
set -Eeuo pipefail
# 指纹输入顺序不能随 VS Code 与终端的区域设置而变化。
export LC_ALL=C

fail() { printf '[devcontainer] 错误：%s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' \
    '用法: bash docker/devcontainer-host.sh [--build-image | --help]' \
    '默认复用与镜像输入匹配的本地镜像；缺失时自动构建。' \
    '--build-image 显式使用 Docker 缓存重建当前镜像，不清理现有缓存。'
}
mode=auto
case "${1:-}" in
  '') ;;
  --build-image) mode=build ;;
  --help|-h) [[ $# == 1 ]] || fail '参数数量不正确。'; usage; exit 0 ;;
  *) fail '未知选项，请使用 --help 查看用法。' ;;
esac
(( $# <= 1 )) || fail '参数数量不正确。'

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
adb_mode="${BANGUMI_ADB_SERVER_MODE:-container}"
abi="${BANGUMI_ANDROID_ABI:-arm64-v8a}"
jobs="${BANGUMI_BUILD_JOBS:-4}"
[[ "$adb_mode" == container || "$adb_mode" == host ]] || fail 'BANGUMI_ADB_SERVER_MODE 只能是 container 或 host。'
[[ "$abi" == arm64-v8a ]] || fail '当前仅支持 arm64-v8a；x86_64 模拟器 ABI 尚未实现。'
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || fail 'BANGUMI_BUILD_JOBS 必须为正整数。'

command -v docker >/dev/null 2>&1 || fail '找不到 Docker CLI，请先安装 Docker Engine 与 Compose。'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose 插件不可用。'
docker info >/dev/null 2>&1 || \
  fail '当前用户无法访问 Docker daemon；VS Code 需要同样的 Docker 访问权限，请勿修改 socket 权限或使用 sudo code。'

# 镜像仅接收固定输入；业务源码、宿主依赖、文档和 IDE 配置不影响指纹。
inputs=(
  docker/Dockerfile docker/Dockerfile.dockerignore
  docker/entrypoint.sh docker/develop.sh docker/adb.sh docker/adb-manager.sh
  docker/adb-server.sh docker/start-metro.cjs docker/configure-debug-host.py
  docker/build-rust.sh docker/prepare-workspace.cjs
  packages/env.js packages/android/package.json babel.config.js app.json
  eslint-rules/package.json eslint-rules/index.js eslint-rules/utils.js
)
patches=(
  react-native-android-widget+0.5.2.patch react-native-pager-view+6.2.0.patch
  react-native-realtimeblurview+1.1.3.patch react-native-render-html+4.1.1.patch
  react-native-smb+0.2.4.patch react-native-tab-view+3.5.2.patch
)
for patch in "${patches[@]}"; do
  inputs+=("packages/android/patches/$patch" "packages/patches/$patch")
done
shopt -s nullglob
rule_files=("$root"/eslint-rules/rules/*.js)
shopt -u nullglob
(( ${#rule_files[@]} > 0 )) || fail '镜像输入目录缺少 ESLint 规则文件。'
for file in "${rule_files[@]}"; do inputs+=("${file#"$root"/}"); done
for file in "${inputs[@]}"; do [[ -f "$root/$file" ]] || fail "镜像输入不存在或不是文件：$file"; done
fingerprint="$(
  cd -- "$root"
  for file in "${inputs[@]}"; do
    # 名称和内容都入摘要；项目中已存在相对软链接的补丁还包括链接目标。
    printf '%s\0' "$file"
    if [[ -L "$file" ]]; then printf 'symlink:%s\0' "$(readlink -- "$file")"; else printf 'file\0'; fi
    sha256sum < "$file"
  done | sha256sum
)"
fingerprint="${fingerprint%% *}"
[[ "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || fail '计算镜像指纹失败。'
tag="bangumi-android-dev:${fingerprint:0:16}-u${uid}-g${gid}"

# 不对已存在目录做递归处理；拒绝链接避免写出仓库或隐藏宿主文件。
for directory in "$root/node_modules" "$root/metro-cache" "$root/docker/.generated"; do
  if [[ -L "$directory" || ( -e "$directory" && ! -d "$directory" ) ]]; then
    fail "挂载或配置目录必须是真实目录：$directory"
  fi
  if [[ ! -e "$directory" ]]; then mkdir -- "$directory" || fail "无法创建目录：$directory"; fi
  [[ -w "$directory" && -x "$directory" ]] || fail "目录不可写或不可进入，请先由用户修复权限：$directory"
done

image_platform=''
image_platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$tag" 2>/dev/null)" || image_platform=''
if [[ "$mode" == build || -z "$image_platform" ]]; then
  printf '[devcontainer] 构建本地镜像 %s（复用现有 Docker 缓存）\n' "$tag"
  docker build --platform linux/amd64 --target dev \
    --build-arg "LOCAL_UID=$uid" --build-arg "LOCAL_GID=$gid" \
    --tag "$tag" --file "$root/docker/Dockerfile" "$root"
  image_platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$tag" 2>/dev/null)" || \
    fail '镜像构建完成后无法检查镜像。'
fi
[[ "$image_platform" == linux/amd64 ]] || fail '本地镜像平台不符合 linux/amd64，不会自动替换。'

# 仅生成可验证的枚举、整数和 SHA 标签；不将宿主环境或密钥写入文件。
generated="$root/docker/.generated"
[[ ! -L "$generated" && -d "$generated" ]] || fail '生成目录不是安全的真实目录。'
temporary="$(mktemp "$generated/.compose.XXXXXXXX")"
trap '[[ -z "${temporary:-}" ]] || rm -f -- "$temporary"' EXIT
printf '%s\n' \
  'name: bangumi-android-dev' \
  'services:' \
  '  dev:' \
  "    image: $tag" \
  "    user: \"$uid:$gid\"" \
  '    environment:' \
  "      BANGUMI_ADB_SERVER_MODE: $adb_mode" \
  "      BANGUMI_ANDROID_ABI: $abi" \
  "      BANGUMI_BUILD_JOBS: \"$jobs\"" > "$temporary"
mv -f -- "$temporary" "$generated/compose.yml"
temporary=''
printf '[devcontainer] 宿主初始化完成：复用 %s。\n' "$tag"
