#!/usr/bin/env bash
# @Author: Q16KBreak
#
# 仅在镜像工具层安装固定版本工具；下载摘要独立于业务源码和宿主依赖。
set -Eeuo pipefail

[[ "$(dpkg --print-architecture)" == amd64 ]] || {
  echo 'This development image supports Linux amd64 only.' >&2
  exit 1
}

fail() { printf '[toolchain] %s\n' "$*" >&2; exit 1; }

scratch="$(mktemp -d /tmp/bangumi-toolchain.XXXXXXXX)"
[[ "$scratch" == /tmp/bangumi-toolchain.* && -d "$scratch" && ! -L "$scratch" && \
   "$(realpath -e -- "$scratch")" == "$scratch" ]] || fail 'Unsafe temporary directory.'
readonly scratch
cleanup() {
  [[ "$scratch" == /tmp/bangumi-toolchain.* && -d "$scratch" && ! -L "$scratch" && \
     "$(realpath -e -- "$scratch")" == "$scratch" ]] || {
    printf '[toolchain] Refusing to clean changed temporary path: %s\n' "$scratch" >&2
    return 1
  }
  rm -rf -- "${scratch:?}"
}
trap cleanup EXIT

assert_android_home() {
  [[ "${ANDROID_HOME:-}" == /opt/android-sdk && ! -L /opt/android-sdk && \
     "$(realpath -m -- /opt/android-sdk)" == /opt/android-sdk ]] || \
    fail 'ANDROID_HOME must be the non-symlink /opt/android-sdk.'
}

fetch() {
  local url="$1" digest="$2" destination="$3" algorithm="${4:-256}"
  curl --fail --show-error --location --retry 4 --proto '=https' --tlsv1.2 \
    "$url" --output "$destination"
  printf '%s  %s\n' "$digest" "$destination" | "sha${algorithm}sum" --check --strict -
}

# Node: https://nodejs.org/dist/v22.20.0/SHASUMS256.txt
fetch https://nodejs.org/dist/v22.20.0/node-v22.20.0-linux-x64.tar.xz \
  00bbd05e306ea68b6e13e17360d0e2f680b493ef95f2fea1c4296ff7437530bc "$scratch/node.tar.xz"
tar --extract --xz --file "$scratch/node.tar.xz" --directory /usr/local --strip-components=1

# Yarn: npm yarn/1.22.22 dist.integrity (SHA-512), not Corepack's floating download.
fetch https://registry.npmjs.org/yarn/-/yarn-1.22.22.tgz \
  a6b2f7906b721bba3d67d4aff083df04dad64c399707841b7acf00f6b133b7ac24255f2652fa22ae3534329dc6180534e98d17432037ff6fd140556e2bb3137e \
  "$scratch/yarn.tgz" 512
mkdir -p /opt/yarn
tar --extract --gzip --file "$scratch/yarn.tgz" --directory /opt/yarn --strip-components=1
ln -s /opt/yarn/bin/yarn /usr/local/bin/yarn
ln -s /opt/yarn/bin/yarnpkg /usr/local/bin/yarnpkg

# The numeric archive build is immutable; Google's literal _latest suffix is its filename.
# cmdline-tools 19.0 / build 13114758; SHA-256 checked before extraction.
fetch https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip \
  7ec965280a073311c339e571cd5de778b9975026cfcbe79f2b1cdcb1e15317ee "$scratch/cmdline-tools.zip"
unzip -q "$scratch/cmdline-tools.zip" -d "$scratch/cmdline"
assert_android_home
mkdir -p "$ANDROID_HOME/cmdline-tools"
cmdline_source="$scratch/cmdline/cmdline-tools"
cmdline_destination=/opt/android-sdk/cmdline-tools/19.0
[[ -d "$cmdline_source" && ! -L "$cmdline_source" && \
   "$(realpath -e -- "$cmdline_source")" == "$scratch/cmdline/cmdline-tools" ]] || \
  fail 'Command-line tools source escaped the verified temporary directory.'
[[ ! -e "$cmdline_destination" && ! -L "$cmdline_destination" && \
   "$(realpath -m -- "$cmdline_destination")" == /opt/android-sdk/cmdline-tools/19.0 ]] || \
  fail 'Command-line tools destination already exists or resolves unexpectedly.'
mv -- "$cmdline_source" "$cmdline_destination"

# sdkmanager verifies each SDK archive against Google's repository metadata.
# Capture sdkmanager's status rather than masking failures with `yes | ... || true`.
set +o pipefail
yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null
license_status="${PIPESTATUS[1]}"
set -o pipefail
[[ "$license_status" == 0 ]]
sdkmanager --sdk_root="$ANDROID_HOME" --install \
  'platforms;android-34' 'build-tools;33.0.0' 'cmake;3.22.1' \
  'ndk;23.1.7779620' 'ndk;27.1.12297006'

# Do not request platform-tools from sdkmanager: that package follows the newest release.
# Fixed 37.0.1 matches the host client (37.0.1-15733141), protocol 1.0.41.
fetch https://dl.google.com/android/repository/platform-tools_r37.0.1-linux.zip \
  d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1 "$scratch/platform-tools.zip"
# sdkmanager may install platform-tools as an implicit dependency; replace it deterministically.
assert_android_home
platform_tools=/opt/android-sdk/platform-tools
[[ ! -L "$platform_tools" && "$(realpath -m -- "$platform_tools")" == /opt/android-sdk/platform-tools ]] || \
  fail 'Refusing to remove an unexpected platform-tools path.'
rm -rf -- "${platform_tools:?}"
unzip -q "$scratch/platform-tools.zip" -d "$ANDROID_HOME"

# Pin the bootstrap executable AND release manifest. rustup additionally verifies all
# component archives using this release's manifest, including the Android std target.
fetch https://static.rust-lang.org/rustup/archive/1.28.2/x86_64-unknown-linux-gnu/rustup-init \
  20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c "$scratch/rustup-init"
fetch https://static.rust-lang.org/dist/channel-rust-1.100.0.toml \
  3051e859570f64a8c5acb9d09e87425db52c7d97287c67e8f6d57d7d34ef9258 "$scratch/rust-manifest.toml"
chmod 0755 "$scratch/rustup-init"
"$scratch/rustup-init" -y --no-modify-path --profile minimal \
  --default-toolchain 1.100.0 --target aarch64-linux-android

# Verify the top-level crate too; Cargo's packaged lock and registry checksums pin
# its transitive dependencies. This never accesses a repository Cargo.lock.
fetch https://static.crates.io/crates/cargo-ndk/cargo-ndk-4.1.2.crate \
  903cc87cda6ab7a2ff82a74065e1c2ae5baa869546b32eb4aacabcc6ed5a670f "$scratch/cargo-ndk.crate"
tar --extract --gzip --file "$scratch/cargo-ndk.crate" --directory "$scratch"
cargo install --path "$scratch/cargo-ndk-4.1.2" --locked --root /opt/cargo

node --version | grep -Fx 'v22.20.0'
yarn --version | grep -Fx '1.22.22'
rustc --version | grep -E '^rustc 1\.100\.0 '
cargo ndk --version | grep -E '(^| )4\.1\.2$'
# `adb version` is local-only; no device command or daemon is started in the build.
adb version | grep -F 'Version 37.0.1-15733141'
grep -Fx 'Pkg.Revision=37.0.1' "$ANDROID_HOME/platform-tools/source.properties"
java -version
