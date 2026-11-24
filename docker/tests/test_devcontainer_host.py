#!/usr/bin/env python3
# 在临时仓库中使用 mock Docker；从不连接真实 daemon 或安装项目依赖。
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'devcontainer-host.sh'
INPUTS = [
    'docker/Dockerfile', 'docker/Dockerfile.dockerignore', 'docker/entrypoint.sh',
    'docker/develop.sh', 'docker/adb.sh', 'docker/adb-manager.sh', 'docker/adb-server.sh',
    'docker/start-metro.cjs', 'docker/configure-debug-host.py', 'docker/build-rust.sh',
    'docker/prepare-workspace.cjs', 'packages/env.js', 'packages/android/package.json',
    'babel.config.js', 'app.json', 'eslint-rules/package.json', 'eslint-rules/index.js',
    'eslint-rules/utils.js', 'eslint-rules/rules/rule.js'
]
PATCHES = [
    'react-native-android-widget+0.5.2.patch', 'react-native-pager-view+6.2.0.patch',
    'react-native-realtimeblurview+1.1.3.patch', 'react-native-render-html+4.1.1.patch',
    'react-native-smb+0.2.4.patch', 'react-native-tab-view+3.5.2.patch'
]


class DevcontainerHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bangumi vscode host ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '项目 with spaces'
        self.root.mkdir()
        (self.root / '.git').mkdir()
        for name in INPUTS:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('fixture ' + name + '\n')
        for name in PATCHES:
            canonical = self.root / 'packages/patches' / name
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_text('patch ' + name + '\n')
            link = self.root / 'packages/android/patches' / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to('../../patches/' + name)
        self.script = self.root / 'docker/devcontainer-host.sh'
        shutil.copyfile(SOURCE, self.script)
        self.bin = Path(self.temp.name) / 'mock bin'
        self.bin.mkdir()
        self.trace = Path(self.temp.name) / 'calls.jsonl'
        self.images = Path(self.temp.name) / 'images.json'
        for name in ['id', 'uname', 'docker']:
            executable = self.bin / name
            executable.write_text('''#!/usr/bin/python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['MOCK_TRACE'], 'a') as stream:
    stream.write(json.dumps([name] + args) + '\\n')
if name == 'id':
    print(os.environ['MOCK_UID' if args == ['-u'] else 'MOCK_GID'])
elif name == 'uname':
    print(os.environ['MOCK_OS' if args == ['-s'] else 'MOCK_ARCH'])
elif name == 'docker':
    state = pathlib.Path(os.environ['MOCK_IMAGES'])
    images = json.loads(state.read_text()) if state.exists() else {}
    if args == ['compose', 'version']:
        sys.exit(int(os.environ.get('MOCK_COMPOSE_RC', '0')))
    if args == ['info']:
        sys.exit(int(os.environ.get('MOCK_DOCKER_RC', '0')))
    if len(args) == 5 and args[:4] == ['image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}']:
        image = images.get(args[4])
        if not image:
            print(os.environ.get('MOCK_IMAGE_STDERR', ''), file=sys.stderr)
            sys.exit(1)
        print(image)
        sys.exit(0)
    if args and args[0] == 'build':
        print(os.environ.get('MOCK_BUILD_STDERR', ''), file=sys.stderr)
        rc = int(os.environ.get('MOCK_BUILD_RC', '0'))
        if rc:
            sys.exit(rc)
        tag = args[args.index('--tag') + 1]
        images[tag] = os.environ.get('MOCK_BUILT_PLATFORM', 'linux/amd64')
        state.write_text(json.dumps(images))
        sys.exit(0)
    sys.exit(99)
''')
            executable.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        MOCK_TRACE=str(self.trace), MOCK_IMAGES=str(self.images),
                        MOCK_UID='1000', MOCK_GID='1000', MOCK_OS='Linux', MOCK_ARCH='x86_64')
        for name in ['LOCAL_UID', 'LOCAL_GID', 'COMPOSE_PROJECT_NAME', 'BANGUMI_ADB_SERVER_MODE',
                     'BANGUMI_ANDROID_ABI', 'BANGUMI_BUILD_JOBS', 'MOCK_COMPOSE_RC',
                     'MOCK_DOCKER_RC', 'MOCK_IMAGE_STDERR', 'MOCK_BUILD_STDERR',
                     'MOCK_BUILD_RC', 'MOCK_BUILT_PLATFORM']:
            self.env.pop(name, None)

    def run_check(self, *args, **variables):
        return subprocess.run(['bash', str(self.script), *args], cwd=self.root,
                              env=dict(self.env, **variables), text=True,
                              capture_output=True, timeout=10)

    def calls(self):
        if not self.trace.exists():
            return []
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def builds(self):
        return [call for call in self.calls() if call[:2] == ['docker', 'build']]

    def tag(self):
        return next(iter(json.loads(self.images.read_text())))

    def test_首次缺镜像只构建一次并创建所需目录(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'node_modules').is_dir())
        self.assertTrue((self.root / 'metro-cache').is_dir())
        self.assertEqual(len(self.builds()), 1)
        build = self.builds()[0]
        self.assertEqual(build[2:8], ['--platform', 'linux/amd64', '--target', 'dev', '--build-arg', 'LOCAL_UID=1000'])
        self.assertIn('LOCAL_GID=1000', build)
        self.assertEqual(build[build.index('--file') + 1], str(self.root / 'docker/Dockerfile'))
        self.assertEqual(build[-1], str(self.root))
        self.assertRegex(self.tag(), r'^bangumi-android-dev:[0-9a-f]{16}-u1000-g1000$')
        override = (self.root / 'docker/.generated/compose.yml').read_text()
        self.assertTrue(override.startswith('name: bangumi-android-dev\n'))
        self.assertIn('image: ' + self.tag(), override)
        self.assertIn('user: "1000:1000"', override)
        self.assertIn('BANGUMI_ADB_SERVER_MODE: container', override)
        self.assertIn('BANGUMI_ANDROID_ABI: arm64-v8a', override)
        self.assertIn('BANGUMI_BUILD_JOBS: "4"', override)
        self.assertFalse(any('--no-cache' in call or 'pull' in call or 'prune' in call for call in self.calls()))

    def test_已有镜像跳过且显式重建仍使用缓存(self):
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(len(self.builds()), 1)
        self.assertEqual(self.run_check('--build-image').returncode, 0)
        self.assertEqual(len(self.builds()), 2)
        self.assertNotIn('--no-cache', self.builds()[-1])

    def test_镜像输入变化切换tag而业务或宿主配置不改变(self):
        self.assertEqual(self.run_check().returncode, 0)
        first = self.tag()
        for name in ['src/example.ts', 'android/example.kt', 'docker/README.md',
                     'docker/devcontainer-host-extra.sh', '.devcontainer/devcontainer.json']:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('change\n')
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(len(self.builds()), 1)
        (self.root / 'docker/develop.sh').write_text('changed runtime script\n')
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(len(self.builds()), 2)
        self.assertNotEqual(first, self.builds()[-1][self.builds()[-1].index('--tag') + 1])

    def test_补丁目标和规则文件变化进入指纹(self):
        self.assertEqual(self.run_check().returncode, 0)
        (self.root / 'packages/patches' / PATCHES[0]).write_text('changed patch')
        self.assertEqual(self.run_check().returncode, 0)
        (self.root / 'eslint-rules/rules/new.js').write_text('new rule')
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(len(self.builds()), 3)

    def test_用户身份自动获取且冲突和root失败(self):
        result = self.run_check(MOCK_UID='2345', MOCK_GID='3456')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.tag().endswith('-u2345-g3456'))
        for variables in [dict(MOCK_UID='0'), dict(MOCK_GID='0'), dict(LOCAL_UID='1001'),
                          dict(LOCAL_GID='1001'), dict(LOCAL_UID=''), dict(LOCAL_GID='abc')]:
            with self.subTest(variables=variables):
                self.assertNotEqual(self.run_check(**variables).returncode, 0)
        self.assertEqual(self.run_check(LOCAL_UID='1000', LOCAL_GID='1000').returncode, 0)

    def test_非Linux或非x86架构失败(self):
        for variables in [dict(MOCK_OS='Darwin'), dict(MOCK_ARCH='aarch64')]:
            self.assertNotEqual(self.run_check(**variables).returncode, 0)
        self.assertFalse(self.builds())

    def test_真实git目录必须存在且不能是链接或文件(self):
        git = self.root / '.git'
        git.rmdir()
        self.assertNotEqual(self.run_check().returncode, 0)
        git.write_text('gitdir: /other')
        self.assertNotEqual(self.run_check().returncode, 0)
        git.unlink()
        git.symlink_to(self.root, target_is_directory=True)
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_已有项目目录保留内容而符号链接和文件被拒绝(self):
        for name in ['node_modules', 'metro-cache']:
            directory = self.root / name
            directory.mkdir()
            (directory / 'keep').write_text('untouched')
        self.assertEqual(self.run_check().returncode, 0)
        for name in ['node_modules', 'metro-cache']:
            self.assertEqual((self.root / name / 'keep').read_text(), 'untouched')
        for name in ['node_modules', 'metro-cache', 'docker/.generated']:
            with self.subTest(name=name):
                path = self.root / name
                shutil.rmtree(path)
                path.symlink_to(self.root, target_is_directory=True)
                self.assertNotEqual(self.run_check().returncode, 0)
                path.unlink()
                path.write_text('keep')
                self.assertNotEqual(self.run_check().returncode, 0)
                self.assertEqual(path.read_text(), 'keep')
                path.unlink()
                path.mkdir()

    @unittest.skipIf(os.geteuid() == 0, 'root 会绕过普通目录权限检查')
    def test_已有挂载目录不可写时在构建前拒绝(self):
        directory = self.root / 'node_modules'
        directory.mkdir()
        directory.chmod(0o500)
        try:
            result = self.run_check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('目录不可写或不可进入', result.stderr)
            self.assertFalse(self.builds())
        finally:
            directory.chmod(0o700)

    def test_ADB模式和并发仅更新运行覆盖不重新构建(self):
        self.assertEqual(self.run_check().returncode, 0)
        result = self.run_check(BANGUMI_ADB_SERVER_MODE='host', BANGUMI_BUILD_JOBS='12')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.builds()), 1)
        override = (self.root / 'docker/.generated/compose.yml').read_text()
        self.assertIn('BANGUMI_ADB_SERVER_MODE: host', override)
        self.assertIn('BANGUMI_BUILD_JOBS: "12"', override)
        for variables in [dict(BANGUMI_ADB_SERVER_MODE='invalid'), dict(BANGUMI_ANDROID_ABI='x86_64'),
                          dict(BANGUMI_BUILD_JOBS='0'), dict(BANGUMI_BUILD_JOBS='1;echo')]:
            self.assertNotEqual(self.run_check(**variables).returncode, 0)
        self.assertEqual((self.root / 'docker/.generated/compose.yml').read_text(), override)

    def test_构建失败透传错误且不产生覆盖配置(self):
        result = self.run_check(MOCK_BUILD_RC='17', MOCK_BUILD_STDERR='actual build failure')
        self.assertEqual(result.returncode, 17)
        self.assertIn('actual build failure', result.stderr)
        self.assertFalse((self.root / 'docker/.generated/compose.yml').exists())

    def test_构建成功后架构错误拒绝(self):
        result = self.run_check(MOCK_BUILT_PLATFORM='linux/arm64')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('linux/amd64', result.stderr)
        self.assertFalse((self.root / 'docker/.generated/compose.yml').exists())
        self.assertNotEqual(self.run_check().returncode, 0)
        self.assertEqual(len(self.builds()), 1)

    def test_项目名冲突不泄露敏感值(self):
        secret = 'private-project-secret'
        result = self.run_check(COMPOSE_PROJECT_NAME=secret)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(secret, result.stdout + result.stderr)
        (self.root / '.env').write_text('COMPOSE_PROJECT_NAME=' + secret + '\n')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(self.run_check(COMPOSE_PROJECT_NAME='bangumi-android-dev').returncode, 0)
        self.assertNotIn(secret, (self.root / 'docker/.generated/compose.yml').read_text())

    def test_Docker访问失败及缺少输入安全退出(self):
        for variables in [dict(MOCK_COMPOSE_RC='1'), dict(MOCK_DOCKER_RC='1')]:
            self.assertNotEqual(self.run_check(**variables).returncode, 0)
        self.assertFalse(self.builds())
        (self.root / 'docker/adb.sh').unlink()
        result = self.run_check(MOCK_IMAGE_STDERR='secret-inspect')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('docker/adb.sh', result.stderr)
        self.assertNotIn('secret-inspect', result.stdout + result.stderr)
        self.assertFalse(self.builds())

    def test_帮助无需Docker且拒绝额外参数(self):
        self.assertEqual(self.run_check('--help').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertNotEqual(self.run_check('--help', 'extra').returncode, 0)
        self.assertNotEqual(self.run_check('--unexpected').returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
