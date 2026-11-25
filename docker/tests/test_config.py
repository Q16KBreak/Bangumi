#!/usr/bin/env python3
# @Author: Q16KBreak
#
# 不启动 Docker daemon；检查一体化 Dev Container 的配置、镜像与安全边界。
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

DOCKER = Path(__file__).resolve().parents[1]
ROOT = DOCKER.parent


@unittest.skipUnless(shutil.which('docker'), '未安装 Docker CLI，跳过 Compose 解析')
class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 只读解析基础配置，不依赖 initializeCommand 产生的本地覆盖文件。
        result = subprocess.run(['docker', 'compose', '-f', str(DOCKER / 'compose.yml'),
                                 'config', '--format', 'json'],
                                env=dict(os.environ, LOCAL_UID='2345', LOCAL_GID='3456', BANGUMI_BUILD_JOBS='2'),
                                check=True, capture_output=True, text=True, timeout=20)
        cls.config = json.loads(result.stdout)
        cls.service = cls.config['services']['dev']

    def test_单一开发服务只使用本地镜像而不触发构建(self):
        self.assertEqual(set(self.config['services']), {'dev'})
        self.assertEqual(self.config['name'], 'bangumi-android-dev')
        self.assertEqual(self.service['image'], 'bangumi-android-dev:initialize-through-vscode')
        self.assertNotIn('build', self.service)
        self.assertEqual(self.service['pull_policy'], 'never')
        self.assertEqual(self.service['platform'], 'linux/amd64')
        self.assertEqual(self.service['working_dir'], '/repo')
        self.assertEqual(self.service['command'], ['workbench'])
        self.assertFalse(self.service.get('depends_on'))
        self.assertFalse(self.service.get('healthcheck'))
        # --print 只渲染计划，不构建镜像，也不需要 Docker daemon。
        result = subprocess.run(['docker', 'compose', '-f', str(DOCKER / 'compose.yml'),
                                 'build', '--print', 'dev'], check=True, capture_output=True,
                                text=True, timeout=20)
        if result.stdout.strip():
            self.assertFalse(json.loads(result.stdout).get('target'))

    def test_宿主网络与非特权安全边界(self):
        service = self.service
        self.assertEqual(service['network_mode'], 'host')
        for key in ['ports', 'devices', 'privileged', 'tmpfs']:
            self.assertFalse(service.get(key))
        self.assertIn('ALL', service['cap_drop'])
        self.assertIn('no-new-privileges:true', service['security_opt'])
        self.assertEqual(service['environment']['ADB_SERVER_SOCKET'], 'tcp:127.0.0.1:5037')
        self.assertEqual(service['environment']['BANGUMI_ADB_SERVER_MODE'], 'container')
        self.assertEqual(service['environment']['BANGUMI_ANDROID_ABI'], 'arm64-v8a')
        self.assertEqual(str(service['environment']['BANGUMI_CONTAINER']), '1')
        for key in ['BANGUMI_METRO_HOST', 'REACT_NATIVE_PACKAGER_HOSTNAME']:
            self.assertNotIn(key, service['environment'])

    def test_运行身份与基础默认变量正确插值(self):
        self.assertEqual(self.service['user'], '2345:3456')
        self.assertEqual(str(self.service['environment']['BANGUMI_BUILD_JOBS']), '2')

    def test_完整仓库与运行视图绑定到相同宿主目录(self):
        expected = {
            '/repo': ROOT,
            '/workspace/src': ROOT / 'src',
            '/workspace/android': ROOT / 'android',
            '/workspace/node_modules': ROOT / 'node_modules',
            '/workspace/metro-cache': ROOT / 'metro-cache',
        }
        bindings = [v for v in self.service['volumes'] if v['type'] == 'bind']
        self.assertEqual({v['target'] for v in bindings}, set(expected))
        for binding in bindings:
            self.assertEqual(Path(binding['source']), expected[binding['target']])
            self.assertFalse(binding.get('bind', {}).get('create_host_path', True))
            self.assertEqual(binding.get('read_only', False), binding['target'] == '/workspace/src')
            self.assertNotIn('docker.sock', binding['source'])
            self.assertNotIn('.android', Path(binding['source']).parts)

    def test_仅用户级缓存与ADB身份使用命名卷(self):
        volumes = [v for v in self.service['volumes'] if v['type'] == 'volume']
        self.assertEqual({v['target'] for v in volumes}, {
            '/home/dev/.gradle', '/home/dev/.cargo/registry', '/home/dev/.cargo/git',
            '/home/dev/.cache/yarn', '/home/dev/.android'
        })
        self.assertEqual({v['source'] for v in volumes}, {
            'gradle-home', 'cargo-registry', 'cargo-git', 'yarn-cache', 'adb-state'
        })
        self.assertEqual(len(volumes), 5)


class DevcontainerConfigTests(unittest.TestCase):
    def test_VSCode使用生成镜像覆盖并等待首次初始化(self):
        config = json.loads((ROOT / '.devcontainer' / 'devcontainer.json').read_text())
        self.assertEqual(config['dockerComposeFile'], ['../docker/compose.yml', '../docker/.generated/compose.yml'])
        self.assertEqual(config['service'], 'dev')
        self.assertEqual(config['runServices'], ['dev'])
        self.assertEqual(config['workspaceFolder'], '/repo')
        self.assertEqual(config['remoteUser'], 'dev')
        self.assertIs(config['updateRemoteUserUID'], False)
        self.assertIs(config['overrideCommand'], False)
        self.assertEqual(config['shutdownAction'], 'stopCompose')
        self.assertEqual(config['initializeCommand'],
                         ['bash', '${localWorkspaceFolder}/docker/devcontainer-host.sh'])
        self.assertEqual(config['postStartCommand'], '/usr/local/bin/bangumi init')
        self.assertEqual(config['waitFor'], 'postStartCommand')
        self.assertFalse(config.get('forwardPorts'))
        self.assertFalse(config.get('mounts'))
        for lifecycle in ['postCreateCommand', 'postAttachCommand']:
            self.assertNotIn(lifecycle, config)
        settings = config['customizations']['vscode']['settings']
        self.assertIs(settings['remote.autoForwardPorts'], False)
        self.assertIs(settings['remote.restoreForwardedPorts'], False)
        self.assertEqual(settings['typescript.tsdk'], 'node_modules/typescript/lib')
        self.assertTrue(settings['typescript.enablePromptUseWorkspaceTsdk'])
        self.assertEqual(settings['eslint.workingDirectories'][0]['directory'], '/repo')
        self.assertEqual(settings['npm.autoDetect'], 'off')
        self.assertNotIn('editor.formatOnSave', settings)

    def test_工作台与构建入口职责分离(self):
        text = (DOCKER / 'entrypoint.sh').read_text()
        workbench = text.split('  workbench)\n', 1)[1].split('    ;;', 1)[0]
        self.assertIn('source /usr/local/lib/bangumi/adb-manager.sh', workbench)
        self.assertIn('bangumi_ensure_adb', workbench)
        self.assertIn('exec sleep infinity', workbench)
        self.assertNotIn('prepare_runtime', workbench)
        self.assertNotIn('yarn install', workbench)
        self.assertNotIn('gradlew', workbench)
        prepare = text.split('prepare_runtime() {\n', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('prepare-workspace.cjs check', prepare)
        self.assertIn('prepare-workspace.cjs sync', prepare)
        self.assertIn('prepare-workspace.cjs configure', prepare)
        self.assertNotIn("node <<'NODE'", prepare)
        self.assertIn('prepare_runtime', text.split('  metro)\n', 1)[1].split('    ;;', 1)[0])
        build = text.split('  build)\n', 1)[1].split('    ;;', 1)[0]
        self.assertIn('prepare_runtime', build)
        self.assertIn('flock -n', build)
        self.assertIn('build-rust.sh /workspace', build)
        self.assertIn('assembleDebug', build)
        self.assertIn('[[ "$BANGUMI_ANDROID_ABI" == arm64-v8a ]]', text)
        self.assertNotIn('editor-entrypoint', text)
        self.assertNotIn('packages/env.js', text)

    def test_运行输入同步限制在四个公共配置文件(self):
        text = (DOCKER / 'prepare-workspace.cjs').read_text()
        sync = text.split('function syncRuntimeInputs(repo, workspace) {\n', 1)[1].split('\n}\n', 1)[0]
        self.assertIn("['index.js', 'index.android.js', 'tsconfig.json', 'metro.config.js']", sync)
        self.assertNotIn('package.json', sync)
        self.assertNotIn('app.json', sync)
        self.assertNotIn('babel.config.js', sync)


class ImageContractTests(unittest.TestCase):
    def test_工具链内联固定版本且不在镜像安装项目依赖(self):
        text = (DOCKER / 'Dockerfile').read_text()
        defaults = {
            'BASE_IMAGE': 'debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc',
            'JDK_VERSION': '17', 'NODE_VERSION': '26.13.1', 'YARN_VERSION': '1.22.22',
            'ANDROID_TOOLS_BUILD': '16111833', 'ANDROID_API': '34',
            'ANDROID_BUILD_TOOLS': '30.0.3',
            'ANDROID_CMAKE': '3.31.6', 'RN_NDK_VERSION': '23.1.7779620',
            'RUST_NDK_VERSION': '30.0.16248370', 'PLATFORM_TOOLS_VERSION': '37.0.3',
            'RUSTUP_VERSION': '1.29.3', 'RUST_VERSION': '1.100.0', 'CARGO_NDK_VERSION': '4.1.2',
        }
        header = text.split('FROM ', 1)[0]
        for name, value in defaults.items():
            with self.subTest(argument=name):
                self.assertIn(f'ARG {name}={value}\n', header)
        self.assertIn('openjdk-${JDK_VERSION}-jdk-headless', text)
        self.assertIn('commandlinetools-linux-${ANDROID_TOOLS_BUILD}_latest.zip', text)
        self.assertIn('"platforms;android-${ANDROID_API}"', text)
        self.assertIn('"build-tools;${ANDROID_BUILD_TOOLS}"', text)
        self.assertNotIn('ANDROID_LEGACY_BUILD_TOOLS', text)
        self.assertEqual(re.findall(r'"build-tools;[^"\n]+"', text), ['"build-tools;${ANDROID_BUILD_TOOLS}"'])
        self.assertIn('"cmake;${ANDROID_CMAKE}"', text)
        self.assertIn('"ndk;${RN_NDK_VERSION}" "ndk;${RUST_NDK_VERSION}"', text)
        self.assertIn('platform-tools_r${PLATFORM_TOOLS_VERSION}-linux.zip', text)
        self.assertIn('"$RUST_VERSION" --target aarch64-linux-android', text)
        self.assertIn('cargo install cargo-ndk --version "$CARGO_NDK_VERSION" --locked', text)
        self.assertIn('util-linux', text)
        self.assertIn('(set +o pipefail; yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null)', text)
        self.assertNotIn('install-toolchain.sh', text)
        self.assertNotRegex(text, re.compile(r'^FROM\s+.*\s+AS\s+dependencies\s*$', re.M | re.I))
        self.assertNotIn('COPY --from=dependencies', text)
        self.assertNotIn('yarn install', text)
        self.assertNotIn('npm install', text)
        self.assertNotIn('COPY . .', text)
        self.assertNotRegex(text, r'(?m)^\s*(?:&&\s*)?(?:node|yarn|rustc|cargo|adb)\s+--version\s*\|\s*grep\b')
        self.assertNotRegex(text, r'(?m)^\s*(?:&&\s*)?java\s+-version\s*\|\s*grep\b')

    def test_工具阶段相互独立并复制到开发镜像(self):
        text = (DOCKER / 'Dockerfile').read_text()
        stages = list(re.finditer(r'^FROM\s+([^\n]+?)\s+AS\s+([\w-]+)\s*$', text, re.M | re.I))
        self.assertEqual([match.group(2) for match in stages],
                         ['base', 'node', 'yarn', 'android-sdk', 'rust', 'android-config', 'dev'])
        self.assertEqual(stages[0].group(1), '--platform=linux/amd64 ${BASE_IMAGE}')
        for match in stages[1:5]:
            self.assertEqual(match.group(1), 'base')
        self.assertEqual(stages[5].group(1), 'node')
        self.assertEqual(stages[6].group(1), 'base')
        contents = {match.group(2): text[match.end():stages[index + 1].start() if index + 1 < len(stages) else None]
                    for index, match in enumerate(stages)}
        stage_args = {
            'base': {'JDK_VERSION'}, 'node': {'NODE_VERSION'}, 'yarn': {'YARN_VERSION'},
            'android-sdk': {'ANDROID_TOOLS_BUILD', 'ANDROID_API', 'ANDROID_BUILD_TOOLS',
                            'ANDROID_CMAKE', 'RN_NDK_VERSION',
                            'RUST_NDK_VERSION', 'PLATFORM_TOOLS_VERSION'},
            'rust': {'RUSTUP_VERSION', 'RUST_VERSION', 'CARGO_NDK_VERSION'},
            'android-config': set(),
            'dev': {'LOCAL_UID', 'LOCAL_GID', 'ANDROID_BUILD_TOOLS', 'ANDROID_CMAKE', 'RUST_NDK_VERSION', 'RUST_VERSION'},
        }
        for stage, expected in stage_args.items():
            with self.subTest(stage=stage):
                self.assertEqual(set(re.findall(r'^ARG\s+(\w+)', contents[stage], re.M)), expected)
        dev = contents['dev']
        for copy in ['COPY --from=node /usr/local/ /usr/local/',
                     'COPY --from=yarn /opt/yarn/ /opt/yarn/',
                     'COPY --from=android-sdk --chown=${LOCAL_UID}:${LOCAL_GID} /opt/android-sdk/ /opt/android-sdk/',
                     'COPY --from=rust /opt/cargo/bin/ /opt/cargo/bin/',
                     'COPY --from=rust /opt/rustup/ /opt/rustup/']:
            self.assertIn(copy, dev)
        self.assertNotIn('COPY --from=rust /opt/cargo/ /opt/cargo/', dev)
        self.assertIn('ANDROID_NDK_HOME=/opt/android-sdk/ndk/${RUST_NDK_VERSION}', dev)
        self.assertIn('RUSTUP_TOOLCHAIN=${RUST_VERSION}', dev)
        self.assertIn('BANGUMI_ANDROID_BUILD_TOOLS=${ANDROID_BUILD_TOOLS}', dev)
        self.assertIn('BANGUMI_CMAKE_DIR=/opt/android-sdk/cmake/${ANDROID_CMAKE}', dev)
        self.assertIn('cmdline-tools/latest/bin', dev)
        self.assertIn('install -d -m 0755 /usr/local/lib/bangumi', dev)
        self.assertLess(dev.index('install -d -m 0755 /usr/local/lib/bangumi'),
                        dev.index('COPY --chmod=0644 docker/adb-server.sh'))

    def test_所有RUN去除挂载选项后shell语法有效(self):
        text = (DOCKER / 'Dockerfile').read_text()
        instructions = re.findall(r'(?m)^RUN\s+((?:[^\n]*\\\n)*[^\n]*)', text)
        self.assertGreaterEqual(len(instructions), 8)
        for index, instruction in enumerate(instructions):
            with self.subTest(block=index):
                command = re.sub(r'\\\n\s*', ' ', instruction)
                command = re.sub(r'^(?:--mount=\S+\s+)+', '', command)
                result = subprocess.run(['bash', '-n'], input=command, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_隔离Android配置并仅在开发层加入运行入口(self):
        text = (DOCKER / 'Dockerfile').read_text()
        config = text.split('FROM node AS android-config\n', 1)[1].split('FROM base AS dev\n', 1)[0]
        self.assertIn('node packages/env.js android', config)
        self.assertNotIn('yarn install', config)
        self.assertNotIn('npm install', config)
        runtime = text.split('FROM base AS dev\n', 1)[1]
        for source in ['package.json', 'patches/', 'packages/patches/']:
            self.assertIn('/configuration/' + source, runtime)
        for source in ['babel.config.js', 'app.json']:
            self.assertIn('/configuration/' + source, runtime)
        self.assertIn('COPY eslint-rules/ /workspace/eslint-rules/', runtime)
        self.assertIn('WORKDIR /repo', runtime)
        self.assertIn('USER dev', runtime)
        self.assertIn('ENTRYPOINT ["/usr/local/bin/bangumi-entrypoint"]', runtime)
        self.assertIn('CMD ["workbench"]', runtime)
        for value in ['BANGUMI_CONTAINER=1', 'BANGUMI_ADB_SERVER_MODE=container',
                      'BANGUMI_ANDROID_ABI=arm64-v8a', 'BANGUMI_BUILD_JOBS=4']:
            self.assertIn(value, runtime)
        self.assertIn('ENV PATH=/usr/local/bin:', text)
        self.assertNotIn('editor-entrypoint', text)

    def test_升级验收仅在独立流程中显式运行(self):
        for name in ['Dockerfile', 'entrypoint.sh', 'devcontainer-host.sh']:
            for probe in ['validate-toolchain.sh', 'report-toolchain.gradle']:
                self.assertNotIn(probe, (DOCKER / name).read_text())
        config = (ROOT / '.devcontainer' / 'devcontainer.json').read_text()
        for probe in ['validate-toolchain.sh', 'report-toolchain.gradle']:
            self.assertNotIn(probe, config)
        rules = (DOCKER / 'Dockerfile.dockerignore').read_text().splitlines()
        self.assertIn('**/tests/**', rules)
        self.assertNotIn('!docker/tests/validate-toolchain.sh', rules)

    def test_源码密钥和锁文件不纳入构建上下文(self):
        rules = [line.strip() for line in (DOCKER / 'Dockerfile.dockerignore').read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(rules[0], '**')
        allowed = ('docker/', 'packages/', 'eslint-rules/', 'app.json', 'babel.config.js')
        for rule in rules:
            if rule.startswith('!'):
                self.assertTrue(rule[1:].startswith(allowed), rule)
                for forbidden in ['node_modules', 'keystore', '.env', '.lock', 'package-lock.json']:
                    self.assertNotIn(forbidden, rule)
        for forbidden in ['**/.git', '**/node_modules', '**/.env*', '**/*.lock',
                          '**/package-lock.json', '**/*.key', '**/*.pem', '**/*.keystore',
                          '**/adbkey*', 'src', 'android']:
            self.assertIn(forbidden, rules)

    def test_运行文件只在最后阶段COPY且均在白名单(self):
        text = (DOCKER / 'Dockerfile').read_text()
        prefix, runtime = text.split('FROM base AS dev\n', 1)
        rules = (DOCKER / 'Dockerfile.dockerignore').read_text().splitlines()
        helpers = {
            'entrypoint.sh': ('0755', '/usr/local/bin/bangumi-entrypoint'),
            'develop.sh': ('0755', '/usr/local/bin/bangumi'),
            'adb.sh': ('0755', '/usr/local/bin/adb'),
            'adb-manager.sh': ('0644', '/usr/local/lib/bangumi/adb-manager.sh'),
            'adb-server.sh': ('0644', '/usr/local/lib/bangumi/adb-server.sh'),
            'start-metro.cjs': ('0644', '/usr/local/lib/bangumi/start-metro.cjs'),
            'configure-debug-host.py': ('0644', '/usr/local/lib/bangumi/configure-debug-host.py'),
            'build-rust.sh': ('0644', '/usr/local/lib/bangumi/build-rust.sh'),
            'prepare-workspace.cjs': ('0644', '/usr/local/lib/bangumi/prepare-workspace.cjs'),
        }
        for name, (mode, target) in helpers.items():
            with self.subTest(name=name):
                self.assertNotIn('docker/' + name, prefix)
                self.assertIn(f'COPY --chmod={mode} docker/{name} {target}', runtime)
                self.assertIn('!docker/' + name, rules)
        self.assertNotIn('!docker/editor-entrypoint.cjs', rules)
        self.assertNotIn('!docker/install-toolchain.sh', rules)
        self.assertNotIn('!docker/tests/', rules)
        self.assertNotIn('!.devcontainer/', rules)


if __name__ == '__main__':
    unittest.main(verbosity=2)
