#!/usr/bin/env python3
# 容器开发命令的 mock 回归及 ADB smart socket 协议，不连接 Docker 或真实设备。
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class DebugScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bangumi develop test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.trace = self.root / 'trace.jsonl'
        self.prefs = self.root / 'private preferences.xml'
        self.writes = self.root / 'write count'
        self.lib = self.root / 'lib'
        self.lib.mkdir()
        helper = self.lib / 'configure-debug-host.py'
        helper.write_text('''import base64, json, os, pathlib, sys
trace = pathlib.Path(os.environ['TRACE'])
value = sys.stdin.read()
with trace.open('a') as stream: stream.write(json.dumps(['helper-stdin', value]) + '\\n')
if os.environ.get('FAIL_HELPER'): sys.exit(17)
xml = '<map><string name="debug_http_host">127.0.0.1:8081</string></map>'
print(os.environ.get('HELPER_OUTPUT', base64.b64encode(xml.encode()).decode()))
''')
        adb = self.bin / 'adb'
        adb.write_text('''#!/usr/bin/python3
import base64, json, os, pathlib, sys
args = sys.argv[1:]
def record(call):
    with open(os.environ['TRACE'], 'a') as stream: stream.write(json.dumps(call) + '\\n')
record(['adb'] + args)
if os.environ.get('FAIL_COMMAND') in args: sys.exit(17)
prefs = pathlib.Path(os.environ['PREFS_STATE'])
if args[:1] == ['devices']:
    print('List of devices attached\\n' + os.environ.get('DEVICES', 'phone-one device model:test'))
    sys.exit(int(os.environ.get('DEVICES_RC', '0')))
if 'getprop' in args:
    print(os.environ.get('ABILIST', 'arm64-v8a,armeabi-v7a'))
elif 'dumpsys' in args:
    print(os.environ.get('POWER_DUMP' if 'power' in args else 'POLICY_DUMP', ''))
elif 'run-as' in args and 'sh' in args:
    if os.environ.get('PREFS_READ_RC'): sys.exit(int(os.environ['PREFS_READ_RC']))
    snapshot = 'present:' + base64.encodebytes(prefs.read_bytes()).decode() if prefs.exists() else 'missing:'
    print(os.environ.get('PREFS_READ_OUTPUT', snapshot), end='')
elif 'run-as' in args and 'dd' in args:
    content = sys.stdin.buffer.read()
    record(['prefs-write', base64.b64encode(content).decode()])
    counter = pathlib.Path(os.environ['PREFS_WRITES'])
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    failure = os.environ.get('FAIL_PREFS_WRITE', '')
    if failure == 'always' or failure == 'once' and count == 1:
        prefs.write_bytes(content[:max(1, len(content) // 2)])
        sys.exit(17)
    prefs.write_bytes(content)
''')
        adb.chmod(0o755)
        entry = self.bin / 'bangumi-entrypoint'
        entry.write_text('''#!/usr/bin/python3
import json, os, pathlib, sys
with open(os.environ['TRACE'], 'a') as stream: stream.write(json.dumps(['entrypoint'] + sys.argv[1:]) + '\\n')
sys.exit(int(os.environ.get('ENTRY_RC', '0')))
''')
        entry.chmod(0o755)
        self.env = dict(os.environ, BANGUMI_CONTAINER='1', BANGUMI_PROJECT_ROOT=str(self.project),
                        TRACE=str(self.trace), PREFS_STATE=str(self.prefs), PREFS_WRITES=str(self.writes),
                        TEST_ADB=str(adb), TEST_ENTRY=str(entry), TEST_LIB=str(self.lib))
        for name in ['ANDROID_SERIAL', 'BANGUMI_ANDROID_ABI', 'FAIL_COMMAND', 'DEVICES', 'FAIL_METRO']:
            self.env.pop(name, None)

    def run_script(self, *args, **env):
        code = '''source "$1"
ADB_BIN="$TEST_ADB"
BANGUMI_LIB="$TEST_LIB"
BANGUMI_ENTRYPOINT="$TEST_ENTRY"
metro_up() {
  printf '["metro-up"]\\n' >> "$TRACE"
  [[ -z "${FAIL_METRO:-}" ]]
}
main "${@:2}"
'''
        return subprocess.run(['bash', '-c', code, 'test', str(SOURCE / 'develop.sh'), *args],
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=10)

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def make_apk(self):
        apk = self.project / 'android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk'
        apk.parent.mkdir(parents=True, exist_ok=True)
        apk.touch()
        return apk

    def assert_not_started(self):
        self.assertFalse(any(call[0] == 'adb' and 'start' in call for call in self.calls()))

    def test_帮助与构建不依赖ADB(self):
        self.assertEqual(self.run_script('help').returncode, 0)
        self.assertEqual(self.calls(), [])
        result = self.run_script('build')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [['entrypoint', 'build']])

    def test_容器之外和无效ABI拒绝运行(self):
        self.assertNotEqual(self.run_script('help', BANGUMI_CONTAINER='0').returncode, 0)
        for command in ['build', 'metro', 'up']:
            result = self.run_script(command, BANGUMI_ANDROID_ABI='x86_64')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('arm64-v8a', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_非法地址与配对码参数被拒绝(self):
        for endpoint in ['127.0.0.1:0', '127.0.0.1:65536', 'host', 'host;echo:123']:
            self.assertNotEqual(self.run_script('start', endpoint).returncode, 0)
        self.assertNotEqual(self.run_script('pair', 'phone:123', '123456').returncode, 0)
        self.assertNotEqual(self.run_script('pair', 'phone:123').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_多设备与不完整设备列表均不猜测(self):
        for extra in [dict(DEVICES='one device\ntwo device'),
                      dict(DEVICES='one device', DEVICES_RC='17'),
                      dict(DEVICES='one offline\ntwo unauthorized')]:
            with self.subTest(extra=extra):
                self.trace.unlink(missing_ok=True)
                self.assertNotEqual(self.run_script('start', **extra).returncode, 0)
                self.assertFalse(any('install' in call or call[0] == 'entrypoint' for call in self.calls()))

    def test_指定mDNS设备保留空格且安装前验证ABI(self):
        apk = self.make_apk()
        serial = 'adb-phone (2)._adb-tls-connect._tcp'
        result = self.run_script('install', '--device', serial, DEVICES=f'{serial} device\nother device')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index(['adb', '-s', serial, 'shell', 'getprop', 'ro.product.cpu.abilist']),
                        calls.index(['adb', '-s', serial, 'install', '-r', str(apk)]))
        self.assertFalse(any('reverse' in call for call in calls))

    def test_设备ABI读取失败或不兼容不安装(self):
        self.make_apk()
        for extra in [dict(ABILIST='x86_64,x86'), dict(ABILIST=''), dict(FAIL_COMMAND='getprop'),
                      dict(BANGUMI_ANDROID_ABI='x86_64')]:
            with self.subTest(extra=extra):
                self.trace.unlink(missing_ok=True)
                self.assertNotEqual(self.run_script('start', **extra).returncode, 0)
                self.assertFalse(any('install' in call or call[0] == 'entrypoint' for call in self.calls()))

    def test_显式IP与同机mDNS同时出现只选IP(self):
        apk = self.make_apk()
        serial = '192.0.2.1:43210'
        mdns = 'adb-phone (2)._adb-tls-connect._tcp'
        result = self.run_script('start', serial, DEVICES=f'{mdns} device\n{serial} device')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index(['adb', 'connect', serial]), calls.index(['adb', 'devices', '-l']))
        self.assertIn(['adb', '-s', serial, 'install', '-r', str(apk)], calls)
        self.assertFalse(any(call[:3] == ['adb', '-s', mdns] for call in calls))

    def test_显式IP不能回退到其他在线设备(self):
        result = self.run_script('start', '192.0.2.1:43210', DEVICES='other device')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不会使用其他设备', result.stderr)
        self.assertFalse(any('install' in call or call[0] == 'entrypoint' for call in self.calls()))

    def test_显式设备与环境变量冲突时拒绝(self):
        result = self.run_script('start', '--device', 'one', ANDROID_SERIAL='two')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_start按构建安装偏好reverse启动顺序(self):
        apk = self.make_apk()
        serial = 'phone-one'
        result = self.run_script('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        build = calls.index(['entrypoint', 'build'])
        install = calls.index(['adb', '-s', serial, 'install', '-r', str(apk)])
        stop = calls.index(['adb', '-s', serial, 'shell', 'am', 'force-stop', 'com.czy0729.bangumi.dev'])
        helper = next(i for i, call in enumerate(calls) if call[0] == 'helper-stdin')
        reverse = calls.index(['adb', '-s', serial, 'reverse', 'tcp:8081', 'tcp:8081'])
        start = calls.index(['adb', '-s', serial, 'shell', 'am', 'start', '-W', '-n',
                             'com.czy0729.bangumi.dev/com.czy0729.bangumi.MainActivity'])
        self.assertLess(calls.index(['metro-up']), build)
        self.assertLess(build, install)
        self.assertLess(install, stop)
        self.assertLess(stop, helper)
        self.assertLess(helper, reverse)
        self.assertLess(reverse, start)
        self.assertIn(b'127.0.0.1:8081', self.prefs.read_bytes())
        self.assertFalse(any(part in {'uninstall', 'clear', 'settings', 'input', 'keyevent', 'kill-server',
                                      'start-server', '--remove-all'} for call in calls for part in call))

    def test_Metro或编译失败不安装(self):
        self.make_apk()
        for extra in [dict(FAIL_METRO='1'), dict(ENTRY_RC='17')]:
            with self.subTest(extra=extra):
                self.trace.unlink(missing_ok=True)
                self.assertNotEqual(self.run_script('start', **extra).returncode, 0)
                self.assertFalse(any('install' in call for call in self.calls()))

    def test_已有偏好被完整传入并写回(self):
        self.make_apk()
        old = b'<map><string name="keep">original</string></map>\\n'
        new = b'<map><string name="debug_http_host">127.0.0.1:8081</string></map>'
        self.prefs.write_bytes(old)
        result = self.run_script('start', HELPER_OUTPUT=base64.b64encode(new).decode())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['helper-stdin', base64.b64encode(old).decode()], self.calls())
        self.assertEqual(self.prefs.read_bytes(), new)

    def test_已有偏好写失败恢复且停止(self):
        self.make_apk()
        for old in [b'<map><string name="keep">original</string></map>', b'']:
            with self.subTest(old=old):
                self.trace.unlink(missing_ok=True)
                self.writes.unlink(missing_ok=True)
                self.prefs.write_bytes(old)
                result = self.run_script('start', FAIL_PREFS_WRITE='once')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('已恢复', result.stderr)
                self.assertEqual(self.prefs.read_bytes(), old)
                self.assert_not_started()
                self.assertFalse(any('reverse' in call for call in self.calls()))

    def test_新偏好写失败不删除且不启动(self):
        self.make_apk()
        result = self.run_script('start', FAIL_PREFS_WRITE='once')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不会自动删除', result.stderr)
        self.assertTrue(self.prefs.exists())
        self.assertFalse(any('rm' in call or 'reverse' in call for call in self.calls()))
        self.assert_not_started()

    def test_偏好生成读取及目录失败不写入(self):
        self.make_apk()
        old = b'<map><string name="keep">untouched</string></map>'
        for extra in [dict(FAIL_COMMAND='force-stop'), dict(PREFS_READ_RC='17'),
                      dict(PREFS_READ_OUTPUT='unexpected'), dict(PREFS_READ_OUTPUT='present:@@bad'),
                      dict(FAIL_HELPER='1'), dict(HELPER_OUTPUT=''), dict(HELPER_OUTPUT='@@bad'),
                      dict(FAIL_COMMAND='mkdir')]:
            with self.subTest(extra=extra):
                self.trace.unlink(missing_ok=True)
                self.prefs.write_bytes(old)
                self.assertNotEqual(self.run_script('start', **extra).returncode, 0)
                self.assertEqual(self.prefs.read_bytes(), old)
                self.assertFalse(any('dd' in call or 'reverse' in call for call in self.calls()))
                self.assert_not_started()

    def test_恢复失败警告且不启动(self):
        self.make_apk()
        self.prefs.write_bytes(b'<map/>')
        result = self.run_script('start', FAIL_PREFS_WRITE='always')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('恢复开发包原有偏好也失败', result.stderr)
        self.assert_not_started()

    def test_reverse失败或安装失败不启动(self):
        self.make_apk()
        for failure in ['reverse', 'install']:
            with self.subTest(failure=failure):
                self.trace.unlink(missing_ok=True)
                result = self.run_script('start', FAIL_COMMAND=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assert_not_started()
                self.assertFalse(any('dumpsys' in call for call in self.calls()))

    def test_休眠锁屏仅警告不修改手机策略(self):
        self.make_apk()
        for extra in [dict(POWER_DUMP='mWakefulness=Dozing'), dict(POLICY_DUMP='showing=true'),
                      dict(POLICY_DUMP='mShowingLockscreen=true')]:
            with self.subTest(extra=extra):
                self.trace.unlink(missing_ok=True)
                result = self.run_script('start', **extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('休眠、锁屏或 Doze', result.stderr)
                self.assertFalse(any(part in {'input', 'keyevent', 'settings', 'svc', 'wm'}
                                     for call in self.calls() for part in call))


class SmartSocketTests(unittest.TestCase):
    def probe(self, response):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(5)
        port = listener.getsockname()[1]
        requests = []

        def serve():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    request = b''
                    while len(request) < 16:
                        block = connection.recv(16 - len(request))
                        if not block:
                            break
                        request += block
                    requests.append(request)
                    connection.sendall(response)
            finally:
                listener.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = subprocess.run(['bash', '-c', 'source "$1"; bangumi_adb_server_version 127.0.0.1 "$2"',
                                 'test', str(SOURCE / 'adb-server.sh'), str(port)],
                                text=True, capture_output=True, timeout=8)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(requests, [b'000chost:version'])
        return result

    def test_读取官方协议返回十进制版本(self):
        result = self.probe(b'OKAY00040029')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '41\n')

    def test_拒绝失败畸形和超长响应(self):
        for response in [b'FAIL0004test', b'OKAYzzzz', b'OKAYffff', b'OKAY0004xxxx']:
            self.assertNotEqual(self.probe(response).returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
