#!/usr/bin/env bash
# 独立、显式运行的升级验收流程；不由镜像构建或容器入口调用。
# 仅在 docker/validation/latest-tools.* 中准备依赖和编译，不改正式工作区。
set -Eeuo pipefail

if [[ "${1:-}" == --inside ]]; then
  [[ "${BANGUMI_CONTAINER:-}" == 1 && -f /validation-driver.sh ]] || { printf 'Use the isolated container driver.\n' >&2; exit 1; }
  phase="${2:?missing validation phase}"
  if [[ "${CANDIDATE_NODE_VERSION:?}" != image ]]; then
    node_home="/candidate-tools/node-${CANDIDATE_NODE_VERSION}"
    if [[ ! -x "$node_home/bin/node" ]]; then
      curl -fsSL "https://nodejs.org/dist/v${CANDIDATE_NODE_VERSION}/node-v${CANDIDATE_NODE_VERSION}-linux-x64.tar.xz" -o /tmp/candidate-node.tar.xz
      mkdir -p "$node_home"
      tar -xJf /tmp/candidate-node.tar.xz -C "$node_home" --strip-components=1
    fi
    export PATH="$node_home/bin:$PATH"
  fi
  if [[ "${CANDIDATE_JDK_MAJOR:-image}" != image ]]; then
    jdk_home="/candidate-tools/jdk-${CANDIDATE_JDK_MAJOR}"
    if [[ ! -x "$jdk_home/bin/java" ]]; then
      curl -fsSL "https://api.adoptium.net/v3/binary/latest/${CANDIDATE_JDK_MAJOR}/ga/linux/x64/jdk/hotspot/normal/eclipse" -o /tmp/candidate-jdk.tar.gz
      mkdir -p "$jdk_home"
      tar -xzf /tmp/candidate-jdk.tar.gz -C "$jdk_home" --strip-components=1
    fi
    export JAVA_HOME="$jdk_home"
    export PATH="$JAVA_HOME/bin:$PATH"
  fi
  if [[ "${CANDIDATE_RUST_NDK:-image}" != image ]]; then
    ndk_home="/candidate-tools/android-ndk-${CANDIDATE_RUST_NDK}"
    if [[ ! -x "$ndk_home/toolchains/llvm/prebuilt/linux-x86_64/bin/clang" ]]; then
      curl -fsSL "https://dl.google.com/android/repository/android-ndk-${CANDIDATE_RUST_NDK}-linux.zip" -o /tmp/candidate-ndk.zip
      unzip -q /tmp/candidate-ndk.zip -d /candidate-tools
    fi
    export ANDROID_NDK_HOME="$ndk_home"
    export ANDROID_NDK_ROOT="$ndk_home"
  fi
  printf '\nCandidate tools used by this isolated run:\n'
  command -v node
  node --version
  printf 'JAVA_HOME=%s\n' "$JAVA_HOME"
  java -version
  printf 'ANDROID_NDK_HOME=%s\n' "$ANDROID_NDK_HOME"
  case "$phase" in
    init) bangumi init ;;
    gradle-report)
      bangumi init
      cd /workspace/android
      exec bash ./gradlew --no-daemon --console=plain --no-configure-on-demand --init-script /validation-report.gradle help
      ;;
    gradle-help)
      bangumi init
      cd /workspace/android
      exec bash ./gradlew --no-daemon --console=plain --info help
      ;;
    build)
      bangumi init
      exec bangumi build
      ;;
    cmake-build)
      [[ "${CANDIDATE_CMAKE:-image}" != image ]] || { printf 'Select a prepared candidate CMake.\n' >&2; exit 1; }
      local_properties=/workspace/android/local.properties
      [[ ! -e "$local_properties" && ! -L "$local_properties" ]] || { printf 'Refusing to replace snapshot local.properties.\n' >&2; exit 1; }
      printf 'sdk.dir=/opt/android-sdk\ncmake.dir=/opt/android-sdk/cmake/%s\n' "$CANDIDATE_CMAKE" > "$local_properties"
      trap 'status=$?; rm -f -- /workspace/android/local.properties; exit "$status"' EXIT
      for module in expo-modules-core react-native-mmkv react-native-reanimated; do
        for output in "/workspace/node_modules/$module/android/.cxx" "/workspace/node_modules/$module/android/build/intermediates/cxx"; do
          [[ ! -L "$output" && "$(realpath -m -- "$output")" == "$output" ]] || { printf 'Unexpected CMake output path: %s\n' "$output" >&2; exit 1; }
          printf 'Regenerating isolated CMake output: %s\n' "$output"
          rm -rf -- "$output"
        done
      done
      bangumi init
      bangumi build
      ;;
    rust-build)
      bangumi init
      # Only this isolated snapshot's native output is removed, never source or shared caches.
      for output in /workspace/android/rust/openssl /workspace/android/rust/target /workspace/android/app/src/main/jniLibs/arm64-v8a/libechproxy.so; do
        [[ ! -L "$output" && "$(realpath -m -- "$output")" == "$output" ]] || { printf 'Unexpected native output path: %s\n' "$output" >&2; exit 1; }
        printf 'Rebuilding isolated native output: %s\n' "$output"
      done
      rm -rf -- /workspace/android/rust/openssl /workspace/android/rust/target
      rm -f -- /workspace/android/app/src/main/jniLibs/arm64-v8a/libechproxy.so
      exec bash /usr/local/lib/bangumi/build-rust.sh /workspace
      ;;
    metro-bundle)
      bangumi init
      trap 'status=$?; cp "/tmp/bangumi-dev-$(id -u)/metro.log" /repo/metro-cache/validation-metro.log 2>/dev/null || true; bangumi down || true; exit "$status"' EXIT
      bangumi up
      curl --fail-with-body --silent --show-error --max-time 300 \
        'http://127.0.0.1:8081/index.bundle?platform=android&dev=true&minify=false' \
        --output /repo/metro-cache/validation.android.bundle
      sha256sum /repo/metro-cache/validation.android.bundle
      wc -c /repo/metro-cache/validation.android.bundle
      ;;
    *) printf 'Unknown validation phase: %s\n' "$phase" >&2; exit 1 ;;
  esac
  exit
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
phase="${1:-help}"
if [[ "$phase" == help || "$phase" == --help ]]; then
  printf '%s\n' \
    'Usage: bash docker/tests/validate-toolchain.sh <init|gradle-help|gradle-report|build|cmake-build|rust-build|metro-bundle> [CASE_DIRECTORY]' \
    'CANDIDATE_NODE_VERSION defaults to 26.13.1 (or image); CANDIDATE_JDK_MAJOR defaults to 25 (or image).' \
    'CANDIDATE_RUST_NDK defaults to image; use an official revision such as r30 for native experiments.' \
    'rust-build explicitly rebuilds only the snapshot native output; the previous APK is retained.' \
    'Prepared SDK candidates can be selected with CANDIDATE_CMAKE or CANDIDATE_BUILD_TOOLS (default image).' \
    'VALIDATION_IMAGE defaults to the currently generated dev image.' \
    'Creates a tracked-working-tree snapshot once; only that copy receives dependencies and build output.' \
    'No device commands, original dependencies, production scripts, Git index or lock contents are changed.'
  exit
fi
[[ "$phase" == init || "$phase" == gradle-help || "$phase" == gradle-report || "$phase" == build || "$phase" == cmake-build || "$phase" == rust-build || "$phase" == metro-bundle ]] || { printf 'Unknown validation phase.\n' >&2; exit 1; }
[[ "$(id -u)" != 0 ]] || { printf 'Run as the ordinary workspace user.\n' >&2; exit 1; }
export CANDIDATE_NODE_VERSION="${CANDIDATE_NODE_VERSION:-26.13.1}"
export CANDIDATE_JDK_MAJOR="${CANDIDATE_JDK_MAJOR:-25}"
export CANDIDATE_RUST_NDK="${CANDIDATE_RUST_NDK:-image}"
export CANDIDATE_CMAKE="${CANDIDATE_CMAKE:-image}"
export CANDIDATE_BUILD_TOOLS="${CANDIDATE_BUILD_TOOLS:-image}"
for version in "$CANDIDATE_CMAKE" "$CANDIDATE_BUILD_TOOLS"; do
  [[ "$version" == image || "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
done
[[ "$CANDIDATE_RUST_NDK" == image || "$CANDIDATE_RUST_NDK" =~ ^r[0-9]+[a-z]?$ ]] || exit 1
[[ "$CANDIDATE_NODE_VERSION" == image || "$CANDIDATE_NODE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
[[ "$CANDIDATE_JDK_MAJOR" == image || "$CANDIDATE_JDK_MAJOR" =~ ^[0-9]+$ ]] || exit 1
[[ ! -L "$ROOT/docker/validation" ]] || { printf 'Validation parent must not be a symbolic link.\n' >&2; exit 1; }
mkdir -p "$ROOT/docker/validation"
if [[ -n "${2:-}" ]]; then
  CASE="$(realpath -e -- "$2")"
  [[ "$CASE" == "$ROOT/docker/validation/latest-tools."* && -f "$CASE/snapshot-ready" ]] || { printf 'Not a validation snapshot created by this tool.\n' >&2; exit 1; }
else
  untracked="$(git -C "$ROOT" ls-files --others --exclude-standard -- . ':(exclude)docker' ':(exclude).devcontainer')"
  [[ -z "$untracked" ]] || { printf 'Snapshot contains tracked files only; resolve untracked non-container source explicitly before validation. No files were staged or copied.\n' >&2; exit 1; }
  CASE="$(mktemp -d "$ROOT/docker/validation/latest-tools.XXXXXXXX")"
  mkdir -p "$CASE/repo"
  (
    cd -- "$ROOT"
    git ls-files -z --cached | tar --no-recursion --null --files-from=- -cf - | tar -xf - -C "$CASE/repo"
    git ls-files -z -- '*.lock' '*-lock.json' | while IFS= read -r -d '' file; do sha256sum -- "$file"; done
  ) > "$CASE/locks.sha256"
  mkdir -p "$CASE/repo/node_modules" "$CASE/repo/metro-cache"
  printf 'tracked working-tree snapshot\n' > "$CASE/snapshot-ready"
fi
mkdir -p "$CASE/tools" "$CASE/logs" "$CASE/cache/gradle" "$CASE/cache/yarn" "$CASE/cache/cargo-registry" "$CASE/cache/cargo-git"
image="${VALIDATION_IMAGE:-}"
if [[ -z "$image" ]]; then
  image="$(docker compose -f "$ROOT/docker/compose.yml" -f "$ROOT/docker/.generated/compose.yml" config --images)"
fi
extra_mounts=()
extra_environment=()
if [[ "$CANDIDATE_CMAKE" != image ]]; then
  source="$CASE/tools/sdk-upgrades/cmake/$CANDIDATE_CMAKE"
  [[ -x "$source/bin/cmake" ]] || { printf 'Prepare SDK candidate first: %s\n' "$source" >&2; exit 1; }
  extra_mounts+=(--mount "type=bind,source=$source,target=/opt/android-sdk/cmake/$CANDIDATE_CMAKE,readonly")
fi
if [[ "$CANDIDATE_BUILD_TOOLS" != image ]]; then
  source="$CASE/tools/sdk-upgrades/build-tools/$CANDIDATE_BUILD_TOOLS"
  [[ -x "$source/aapt2" ]] || { printf 'Prepare SDK candidate first: %s\n' "$source" >&2; exit 1; }
  extra_mounts+=(--mount "type=bind,source=$source,target=/opt/android-sdk/build-tools/$CANDIDATE_BUILD_TOOLS,readonly")
  extra_environment+=(--env "ORG_GRADLE_PROJECT_android.buildToolsVersion=$CANDIDATE_BUILD_TOOLS")
fi
printf 'Validation snapshot: %s\nImage: %s\nPhase: %s, Node: %s, JDK: %s, Rust NDK: %s, CMake: %s, Build Tools: %s\n' "$CASE" "$image" "$phase" "$CANDIDATE_NODE_VERSION" "$CANDIDATE_JDK_MAJOR" "$CANDIDATE_RUST_NDK" "$CANDIDATE_CMAKE" "$CANDIDATE_BUILD_TOOLS"
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
log="$CASE/logs/${stamp}-node${CANDIDATE_NODE_VERSION}-jdk${CANDIDATE_JDK_MAJOR}-${phase}.log"
driver="$CASE/logs/${stamp}-driver.sh"
# Bind an immutable per-run copy so later edits cannot change a running shell.
cp -- "$ROOT/docker/tests/validate-toolchain.sh" "$driver"
reporter="$CASE/logs/${stamp}-report.gradle"
cp -- "$ROOT/docker/tests/report-toolchain.gradle" "$reporter"
set +e
docker run --rm --init --network bridge --user "$(id -u):$(id -g)" \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --env CANDIDATE_NODE_VERSION --env CANDIDATE_JDK_MAJOR --env CANDIDATE_RUST_NDK --env CANDIDATE_CMAKE --env CANDIDATE_BUILD_TOOLS \
  "${extra_environment[@]}" "${extra_mounts[@]}" \
  --env BANGUMI_BUILD_JOBS="${BANGUMI_BUILD_JOBS:-4}" \
  --mount "type=bind,source=$CASE/repo,target=/repo" \
  --mount "type=bind,source=$CASE/repo/src,target=/workspace/src,readonly" \
  --mount "type=bind,source=$CASE/repo/android,target=/workspace/android" \
  --mount "type=bind,source=$CASE/repo/node_modules,target=/workspace/node_modules" \
  --mount "type=bind,source=$CASE/repo/metro-cache,target=/workspace/metro-cache" \
  --mount "type=bind,source=$CASE/tools,target=/candidate-tools" \
  --mount "type=bind,source=$CASE/cache/gradle,target=/home/dev/.gradle" \
  --mount "type=bind,source=$CASE/cache/yarn,target=/home/dev/.cache/yarn" \
  --mount "type=bind,source=$CASE/cache/cargo-registry,target=/home/dev/.cargo/registry" \
  --mount "type=bind,source=$CASE/cache/cargo-git,target=/home/dev/.cargo/git" \
  --mount "type=bind,source=$driver,target=/validation-driver.sh,readonly" \
  --mount "type=bind,source=$reporter,target=/validation-report.gradle,readonly" \
  --entrypoint /bin/bash "$image" /validation-driver.sh --inside "$phase" 2>&1 | tee "$log"
statuses=("${PIPESTATUS[@]}")
status="${statuses[0]}"
if [[ "$status" == 0 && "${statuses[1]}" != 0 ]]; then status="${statuses[1]}"; fi
set -e
(cd -- "$ROOT" && sha256sum --check "$CASE/locks.sha256")
(cd -- "$CASE/repo" && sha256sum --check "$CASE/locks.sha256")
printf 'Validation exit: %s\nLog: %s\n' "$status" "$log"
exit "$status"
