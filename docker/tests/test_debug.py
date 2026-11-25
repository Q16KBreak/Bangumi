#!/usr/bin/env python3
# @Author: Q16KBreak
#
# 使用假 Docker/ADB 和临时 smart socket 验证宿主联调脚本，不安装依赖或连接手机。
# reverse-only：Metro 只在容器内监听，手机经 adb reverse 访问 127.0.0.1:8081。
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
HELPER_CMD = ['exec', '-T', 'dev', 'python3',
              '/usr/local/lib/bangumi/configure-debug-host.py']


class DebugScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bangumi docker test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with spaces'
        self.docker = self.project / 'docker'
        self.docker.mkdir(parents=True)
        for name in ['android-debug.sh', 'adb-server.sh']:
            shutil.copyfile(SOURCE / name, self.docker / name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.trace = self.root / 'trace.jsonl'
        self.prefs = self.root / 'private preferences.xml'
        stub = '''#!/usr/bin/env python3
import base64, json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
HELPER = '/usr/local/lib/bangumi/configure-debug-host.py'
def record(call):
    with open(os.environ['TRACE'], 'a') as trace:
        trace.write(json.dumps(call) + '\\n')
record([name] + args)
if name == 'sudo':
    # 模拟 sudo 清理环境，只有显式 env 白名单才能把变量带给 Docker。
    clean = {key: value for key, value in os.environ.items()
             if key not in ['LOCAL_UID', 'LOCAL_GID', 'BANGUMI_BUILD_JOBS', 'BANGUMI_METRO_HOST']}
    os.execvpe(args[0], args, clean)
if os.environ.get('FAIL_COMMAND') in args:
    sys.exit(17)
if name == 'ip':
    # 仅作哨兵：reverse-only 脚本不应调用 ip，调用会被 trace 记录并让测试失败。
    print(os.environ.get('IP_ROUTE', args[-1] + ' via 192.0.2.1 dev wlan0 src 192.0.2.10 uid 1000\\n    cache'))
if name == 'docker':
    record(['docker-env', os.environ.get('BANGUMI_METRO_HOST', '')])
    if 'ps' in args:
        print(os.environ.get('RUNNING_CONTAINER', ''))
    if HELPER in args:
        # helper 不再接受参数；固定转换逻辑由镜像测试覆盖，这里验证宿主传输协议。
        if args[-1] != HELPER:
            sys.exit(18)
        record(['helper-stdin', sys.stdin.read()])
        xml = '<map><string name="debug_http_host">127.0.0.1:8081</string></map>'
        print(os.environ.get('HELPER_OUTPUT', base64.b64encode(xml.encode()).decode()))
if name == 'adb':
    prefs = pathlib.Path(os.environ['PREFS_STATE'])
    if args == ['version']:
        print('Android Debug Bridge version 1.0.41\\nVersion ' + os.environ.get('ADB_VERSION', '37.0.1-15733141'))
    elif args[:1] == ['devices']:
        print('List of devices attached\\n' + os.environ.get('DEVICES', 'phone-one device model:test'))
        sys.exit(int(os.environ.get('DEVICES_RC', '0')))
    elif 'dumpsys' in args:
        if 'power' in args:
            print(os.environ.get('POWER_DUMP', ''))
        elif 'policy' in args:
            print(os.environ.get('POLICY_DUMP', ''))
        elif 'window' in args:
            print(os.environ.get('WINDOW_DUMP', ''))
    elif 'run-as' in args and 'sh' in args:
        if os.environ.get('PREFS_READ_RC'):
            sys.exit(int(os.environ['PREFS_READ_RC']))
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
'''
        for name in ['docker', 'adb', 'sudo', 'ip']:
            path = self.bin / name
            path.write_text(stub)
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        TRACE=str(self.trace), PREFS_STATE=str(self.prefs),
                        PREFS_WRITES=str(self.root / 'prefs writes'), LOCAL_UID='1000', LOCAL_GID='1000')
        for name in ['ANDROID_SERIAL', 'DOCKER_USE_SUDO', 'BANGUMI_ADB_BIN', 'BANGUMI_METRO_HOST',
                     'BANGUMI_BUILD_JOBS']:
            self.env.pop(name, None)

    def run_script(self, *args, **env):
        # 用函数覆盖协议探测；实际 socket 协议在独立测试中验证。
        code = '''source "$1"
bangumi_adb_server_version() {
  if [[ -n "${SERVER_STATUS:-}" ]]; then return "$SERVER_STATUS"; fi
  printf '%s\\n' "${SERVER_PROTOCOL:-41}"
}
main "${@:2}"
'''
        result = subprocess.run(['bash', '-c', code, 'test', str(self.docker / 'android-debug.sh'), *args],
                                env=dict(self.env, **env), text=True, capture_output=True, timeout=10)
        return result

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def make_apk(self):
        apk = self.project / 'android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk'
        apk.parent.mkdir(parents=True, exist_ok=True)
        apk.touch()
        return apk

    def start_call(self, serial='phone-one'):
        return ['adb', '-s', serial, 'shell', 'am', 'start', '-W', '-n',
                'com.czy0729.bangumi.dev/com.czy0729.bangumi.MainActivity']

    def assert_not_started(self):
        self.assertFalse(any(call[0] == 'adb' and 'start' in call for call in self.calls()))

    def assert_reverse_only(self, serial):
        calls = self.calls()
        reverse = ['adb', '-s', serial, 'reverse', 'tcp:8081', 'tcp:8081']
        self.assertEqual([call for call in calls if 'reverse' in call], [reverse])
        self.assertFalse(any('--remove-all' in part or '--list' in part
                             for call in calls for part in call))
        self.assertFalse(any('kill-server' in part or 'start-server' in part
                             for call in calls for part in call))
        self.assertFalse(any(part in {'root', 'unroot', '-a'} for call in calls for part in call))
        return reverse

    def assert_screen_probe_readonly(self, serial='phone-one'):
        calls = self.calls()
        # 只读且收窄：power 查休眠/Doze，window policy 查锁屏；不退回升级为 dumpsys window。
        self.assertIn(['adb', '-s', serial, 'shell', 'dumpsys', 'power'], calls)
        self.assertIn(['adb', '-s', serial, 'shell', 'dumpsys', 'window', 'policy'], calls)
        self.assertFalse(any('dumpsys' in call and 'window' in call and 'policy' not in call
                             for call in calls))
        # 绝不唤醒、解锁或修改省电/网络/锁屏设置。
        forbidden = {'input', 'keyevent', 'KEYCODE_WAKEUP', 'dismiss-keyguard', 'svc', 'settings', 'wm'}
        self.assertFalse(any(part in forbidden for call in calls for part in call))

    def test_帮助不要求Docker或ADB(self):
        result = self.run_script('help', BANGUMI_ADB_BIN='/missing/adb')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_拒绝未知命令及多余参数(self):
        for args in [('unknown',), ('build', 'extra'), ('pair',)]:
            self.assertNotEqual(self.run_script(*args).returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_无效端口和命令注入在调用外部程序前拒绝(self):
        for endpoint in ['127.0.0.1:0', '127.0.0.1:65536', 'host', 'host:abc', 'host;echo:123', '-host:123']:
            self.assertNotEqual(self.run_script('start', endpoint).returncode, 0, endpoint)
        self.assertEqual(self.calls(), [])

    def test_仅构建不要求ADB或手机(self):
        result = self.run_script('build', BANGUMI_ADB_BIN='/missing/adb')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertFalse(any(call[0] == 'adb' for call in calls))
        self.assertTrue(any(call[-6:] == ['run', '--rm', '--no-deps', '-T', 'dev', 'build'] for call in calls))
        self.assertTrue(any(str(self.docker / 'compose.yml') in call for call in calls))

    def test_已有运行容器时复用原生增量产物(self):
        result = self.run_script('build', BANGUMI_ADB_BIN='/missing/adb', RUNNING_CONTAINER='running-id')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertTrue(any(call[-5:] == ['exec', '-T', 'dev', '/usr/local/bin/bangumi-entrypoint', 'build']
                            for call in calls))
        self.assertFalse(any('run' in call for call in calls))
        self.assertFalse(any(call[0] == 'adb' for call in calls))

    def test_构建失败保留错误码(self):
        self.assertEqual(self.run_script('build', FAIL_COMMAND='run').returncode, 17)

    def test_多设备拒绝猜测(self):
        result = self.run_script('start', DEVICES='one device\ntwo device')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('多台手机', result.stderr)
        self.assertFalse(any(call[0] == 'docker' for call in self.calls()))

    def test_离线与未授权设备不可安装(self):
        result = self.run_script('install', DEVICES='one offline\ntwo unauthorized')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('install' in call for call in self.calls()))

    def test_指定序列号且路径空格不拆分并reverse完整序列号(self):
        apk = self.make_apk()
        serial = '[::1]:43210'
        result = self.run_script('start', serial, ANDROID_SERIAL=serial, DEVICES=f'one device\n{serial} device')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertIn(['adb', '-s', serial, 'install', '-r', str(apk)], calls)
        reverse = self.assert_reverse_only(serial)
        start = ['adb', '-s', serial, 'shell', 'am', 'start', '-W', '-n',
                 'com.czy0729.bangumi.dev/com.czy0729.bangumi.MainActivity']
        self.assertIn(start, calls)
        self.assertLess(calls.index(reverse), calls.index(start))

    def test_mDNS序列号包含空格时保持完整(self):
        apk = self.make_apk()
        serial = 'adb-phone (2)._adb-tls-connect._tcp'
        for selected in ['', serial]:
            result = self.run_script('install', ANDROID_SERIAL=selected,
                                     DEVICES=f'{serial}     device product:test\noffline-phone offline')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls().count(['adb', '-s', serial, 'install', '-r', str(apk)]), 2)
        # install 只安装，不建立 reverse，也不启动应用。
        self.assertFalse(any('reverse' in call for call in self.calls()))
        self.assert_not_started()

    def test_连接失败但返回零时不使用其他已有手机(self):
        result = self.run_script('start', '192.0.2.1:43210', DEVICES='other-phone device')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不会使用其他设备', result.stderr)
        self.assertFalse(any(call[0] == 'docker' or 'install' in call for call in self.calls()))

    def test_设备列表有输出但失败时不使用不完整结果(self):
        result = self.run_script('start', DEVICES='other-phone device', DEVICES_RC='17')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('读取 ADB 设备列表失败', result.stderr)
        self.assertFalse(any(call[0] == 'docker' or 'install' in call for call in self.calls()))

    def test_start地址与指定序列号冲突时立即拒绝(self):
        result = self.run_script('start', '192.0.2.1:43210', ANDROID_SERIAL='other-phone')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ANDROID_SERIAL 与 start 地址不同', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_既有服务版本不兼容时不重启(self):
        result = self.run_script('devices', SERVER_PROTOCOL='40')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('start-server' in call or 'kill-server' in call for call in self.calls()))

    def test_非ADB端口不替换(self):
        result = self.run_script('devices', SERVER_STATUS='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('start-server' in call for call in self.calls()))

    def test_客户端版本不同则拒绝(self):
        result = self.run_script('devices', ADB_VERSION='36.0.0-test')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)

    def test_配对码不接受参数且非交互终端拒绝配对(self):
        self.assertNotEqual(self.run_script('pair', 'phone:123', '123456').returncode, 0)
        result = self.run_script('pair', 'phone:123')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('pair' in call for call in self.calls()))

    def test_停止容器不操作宿主ADB且sudo只转发用户与并发(self):
        result = self.run_script('down', DOCKER_USE_SUDO='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertFalse(any(call[0] == 'adb' for call in calls))
        sudo = [call for call in calls if call[0] == 'sudo']
        self.assertTrue(sudo)
        self.assertTrue(all(call[:6] == ['sudo', 'env', 'LOCAL_UID=1000', 'LOCAL_GID=1000',
                                        'BANGUMI_BUILD_JOBS=4', 'docker'] for call in sudo))
        self.assertFalse(any('BANGUMI_METRO_HOST' in part for call in sudo for part in call))

    def test_up只启动Metro和共享ADB不要求设备(self):
        for devices in ['', 'usb-phone device', 'one device\ntwo device', 'one offline']:
            with self.subTest(devices=devices):
                self.trace.write_text('')
                result = self.run_script('up', DEVICES=devices)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls()
                self.assertTrue(any(call[0] == 'docker' and 'up' in call for call in calls))
                self.assertFalse(any(call[0] == 'ip' for call in calls))
                self.assertFalse(any('devices' in call or 'connect' in call or 'reverse' in call
                                     for call in calls))

    def test_up不再依赖宿主ip命令(self):
        # 隔离 PATH：reverse-only 的 up 只需要 bash/dirname/docker/adb。
        isolated = self.root / 'isolated-bin'
        isolated.mkdir()
        for name in ['bash', 'dirname', 'python3']:
            (isolated / name).symlink_to(shutil.which(name))
        for name in ['adb', 'docker']:
            (isolated / name).symlink_to(self.bin / name)
        result = self.run_script('up', PATH=str(isolated))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] == 'ip' for call in self.calls()))

    def test_sudo只转发白名单且不传遗留Metro地址(self):
        result = self.run_script('up', DOCKER_USE_SUDO='1', BANGUMI_METRO_HOST='10.20.30.40')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        sudo = [call for call in calls if call[0] == 'sudo']
        self.assertTrue(sudo)
        self.assertTrue(all(call[:6] == ['sudo', 'env', 'LOCAL_UID=1000', 'LOCAL_GID=1000',
                                        'BANGUMI_BUILD_JOBS=4', 'docker'] for call in sudo))
        self.assertFalse(any('BANGUMI_METRO_HOST' in part for call in sudo for part in call))
        self.assertTrue(all(call[1] == '' for call in calls if call[0] == 'docker-env'))

    def test_遗留MetroIPv4变量被忽略且不探路由(self):
        self.make_apk()
        for host in ['10.20.30.40', 'not-an-ip', '127.0.0.1']:
            with self.subTest(host=host):
                self.trace.write_text('')
                self.prefs.unlink(missing_ok=True)
                result = self.run_script('start', BANGUMI_METRO_HOST=host)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls()
                self.assertFalse(any(call[0] == 'ip' for call in calls))
                self.assertEqual(len([call for call in calls if call[-5:] == HELPER_CMD]), 1)
                self.assertIn(b'127.0.0.1:8081', self.prefs.read_bytes())

    def test_start按安装_偏好_reverse_启动顺序且不删除其他映射(self):
        apk = self.make_apk()
        serial = 'phone-one'
        package = 'com.czy0729.bangumi.dev'
        prefs = 'shared_prefs/com.czy0729.bangumi.dev_preferences.xml'
        result = self.run_script('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        stop = ['adb', '-s', serial, 'shell', 'am', 'force-stop', package]
        mkdir = ['adb', '-s', serial, 'shell', '-T', 'run-as', package, 'mkdir', '-p', 'shared_prefs']
        write = ['adb', '-s', serial, 'shell', '-T', 'run-as', package, 'dd', f'of={prefs}']
        start = ['adb', '-s', serial, 'shell', 'am', 'start', '-W', '-n',
                 package + '/com.czy0729.bangumi.MainActivity']
        read = next(call for call in calls if 'sh' in call)
        helper = next(index for index, call in enumerate(calls) if call[-5:] == HELPER_CMD)
        install = ['adb', '-s', serial, 'install', '-r', str(apk)]
        reverse = self.assert_reverse_only(serial)
        self.assertIn(['helper-stdin', ''], calls)
        self.assertLess(calls.index(install), calls.index(stop))
        self.assertLess(calls.index(stop), calls.index(read))
        self.assertLess(calls.index(read), helper)
        self.assertLess(helper, calls.index(mkdir))
        self.assertLess(calls.index(mkdir), calls.index(write))
        self.assertLess(calls.index(write), calls.index(reverse))
        self.assertLess(calls.index(reverse), calls.index(start))
        self.assertEqual(self.prefs.read_text(),
                         '<map><string name="debug_http_host">127.0.0.1:8081</string></map>')
        self.assertFalse(any(call[0] == 'ip' for call in calls))
        forbidden = {'uninstall', 'clear', 'settings', 'input', 'keyevent', 'svc', 'wm'}
        self.assertFalse(any(part in forbidden for call in calls for part in call))
        self.assertTrue(all(package in call for call in calls if 'run-as' in call))
        self.assertTrue(read[-1].startswith("'if [ -f " + prefs))
        self.assertTrue(read[-1].endswith("fi'"))

    def test_helper无IP参数固定写入回环地址且旧偏好完整传入(self):
        self.make_apk()
        old = b'<map><boolean name="keep" value="true"/><string name="debug_http_host">10.0.0.2:8081</string></map>'
        self.prefs.write_bytes(old)
        result = self.run_script('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        helper = [call for call in calls if '/usr/local/lib/bangumi/configure-debug-host.py' in call]
        self.assertEqual(len(helper), 1)
        self.assertEqual(helper[0][-5:], HELPER_CMD)
        # helper 路径必须是最后一个参数：宿主不再传 IP，固定回环地址由容器内脚本写入。
        self.assertEqual(helper[0][-1], HELPER_CMD[-1])
        self.assertIn(['helper-stdin', base64.b64encode(old).decode()], calls)
        self.assertEqual(self.prefs.read_bytes(),
                         b'<map><string name="debug_http_host">127.0.0.1:8081</string></map>')

    def test_已有偏好base64完整交给容器且原样写回helper结果(self):
        self.make_apk()
        old = '<map><boolean name="keep" value="true"/><string name="debug_http_host">old:8081</string></map>\n'.encode()
        new = old.replace(b'old:8081', b'127.0.0.1:8081')
        self.prefs.write_bytes(old)
        result = self.run_script('start', HELPER_OUTPUT=base64.b64encode(new).decode())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['helper-stdin', base64.b64encode(old).decode()], self.calls())
        self.assertEqual(self.prefs.read_bytes(), new)
        self.assertEqual(len([call for call in self.calls() if call[0] == 'prefs-write']), 1)
        self.assertIn(['adb', '-s', 'phone-one', 'reverse', 'tcp:8081', 'tcp:8081'], self.calls())

    def test_mDNS含空格序列号配置偏好和reverse时不拆分(self):
        self.make_apk()
        serial = 'adb-phone (2)._adb-tls-connect._tcp'
        result = self.run_script('start', ANDROID_SERIAL=serial, DEVICES=f'{serial} device')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertTrue(all(call[2] == serial for call in calls if call[:2] == ['adb', '-s']))
        self.assertIn(['adb', '-s', serial, 'reverse', 'tcp:8081', 'tcp:8081'], calls)
        self.assertFalse(any(call[0] == 'ip' for call in calls))

    def test_显式IP与mDNS同机两条记录时按显式地址选择(self):
        apk = self.make_apk()
        serial = '192.168.50.23:43210'
        mdns = 'adb-phone (2)._adb-tls-connect._tcp'
        result = self.run_script('start', serial, DEVICES=f'{mdns} device\n{serial} device')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        # 同一手机的 IP 与 mDNS 两条记录不再触发多设备拒绝，也不会误选 mDNS。
        self.assertIn(['adb', 'connect', serial], calls)
        self.assertIn(['adb', '-s', serial, 'install', '-r', str(apk)], calls)
        self.assertIn(['adb', '-s', serial, 'reverse', 'tcp:8081', 'tcp:8081'], calls)
        self.assertFalse(any(call[:3] == ['adb', '-s', mdns] for call in calls))
        self.assertLess(calls.index(['adb', 'connect', serial]), calls.index(['adb', 'devices', '-l']))

    def test_休眠仅警告仍启动且不唤醒解锁(self):
        self.make_apk()
        result = self.run_script('start', POWER_DUMP='mWakefulness=Asleep mWakefulnessChanging=false')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('休眠、锁屏或 Doze', result.stderr)
        self.assertIn(self.start_call(), self.calls())
        self.assert_screen_probe_readonly()

    def test_Doze状态仅警告仍启动且不唤醒解锁(self):
        self.make_apk()
        # 本次真机实际值是 Dozing：必须命中警告，但仅提醒不拒绝启动。
        result = self.run_script('start', POWER_DUMP='mWakefulness=Dozing mWakefulnessChanging=false')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('休眠、锁屏或 Doze', result.stderr)
        self.assertIn(self.start_call(), self.calls())
        self.assert_screen_probe_readonly()

    def test_锁屏policy显示showing_true仅警告(self):
        self.make_apk()
        policy = ('WINDOW MANAGER POLICY STATE\n  KeyguardServiceDelegate\n'
                  '    showing=true\n    showingAndNotOccluded=false\n    inputRestricted=true\n')
        result = self.run_script('start', POLICY_DUMP=policy)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('休眠、锁屏或 Doze', result.stderr)
        self.assertIn(self.start_call(), self.calls())
        self.assert_screen_probe_readonly()

    def test_旧锁屏字段兼容仅警告(self):
        self.make_apk()
        for policy in ['mShowingLockscreen=true', 'mDreamingLockscreen=true']:
            with self.subTest(policy=policy):
                self.trace.write_text('')
                result = self.run_script('start', POLICY_DUMP=policy)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('休眠、锁屏或 Doze', result.stderr)
                self.assertIn(self.start_call(), self.calls())
                self.assert_screen_probe_readonly()

    def test_屏幕状态探测失败只提醒不阻断(self):
        self.make_apk()
        result = self.run_script('start', FAIL_COMMAND='dumpsys')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('无法读取手机屏幕', result.stderr)
        self.assertIn(self.start_call(), self.calls())
        self.assert_screen_probe_readonly()

    def test_reverse失败停止且不启动应用(self):
        self.make_apk()
        result = self.run_script('start', FAIL_COMMAND='reverse')
        self.assertEqual(result.returncode, 1)
        self.assertIn('reverse', result.stderr)
        self.assertIn('不会启动应用', result.stderr)
        self.assert_not_started()
        calls = self.calls()
        self.assertFalse(any('dumpsys' in call for call in calls))
        self.assertFalse(any('kill-server' in call or 'start-server' in call for call in calls))

    def test_停止读取生成创建目录失败均不写偏好不启动(self):
        self.make_apk()
        old = b'<map><string name="keep">untouched</string></map>'
        for extra in [{'FAIL_COMMAND': 'force-stop'}, {'PREFS_READ_RC': '17'},
                      {'PREFS_READ_OUTPUT': 'unexpected'}, {'PREFS_READ_OUTPUT': 'present:@@bad'},
                      {'FAIL_COMMAND': 'python3'}, {'HELPER_OUTPUT': ''}, {'HELPER_OUTPUT': '@@bad'},
                      {'FAIL_COMMAND': 'mkdir'}]:
            with self.subTest(extra=extra):
                self.trace.write_text('')
                self.prefs.write_bytes(old)
                result = self.run_script('start', **extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.prefs.read_bytes(), old)
                self.assert_not_started()
                self.assertFalse(any('dd' in call or 'reverse' in call for call in self.calls()))

    def test_已有偏好写失败恢复旧内容且不启动(self):
        self.make_apk()
        old = b'<map><string name="keep">original</string></map>\n'
        self.prefs.write_bytes(old)
        result = self.run_script('start', FAIL_PREFS_WRITE='once')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('已恢复', result.stderr)
        self.assertEqual(self.prefs.read_bytes(), old)
        self.assertEqual(len([call for call in self.calls() if call[0] == 'prefs-write']), 2)
        self.assert_not_started()
        self.assertFalse(any('reverse' in call for call in self.calls()))

    def test_已有空偏好写失败仍恢复空文件(self):
        self.make_apk()
        self.prefs.write_bytes(b'')
        result = self.run_script('start', FAIL_PREFS_WRITE='once')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.prefs.exists())
        self.assertEqual(self.prefs.read_bytes(), b'')
        self.assert_not_started()

    def test_新偏好写失败明确警告且不自动删除或启动(self):
        self.make_apk()
        result = self.run_script('start', FAIL_PREFS_WRITE='once')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.prefs.exists())
        self.assertIn('可能留有不完整内容', result.stderr)
        self.assertIn('不会自动删除', result.stderr)
        self.assertFalse(any('rm' in call for call in self.calls()))
        self.assert_not_started()

    def test_恢复旧偏好也失败时明确警告且不启动(self):
        self.make_apk()
        self.prefs.write_bytes(b'<map><string name="keep">original</string></map>')
        result = self.run_script('start', FAIL_PREFS_WRITE='always')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('恢复开发包原有偏好也失败', result.stderr)
        self.assert_not_started()
        self.assertFalse(any('reverse' in call for call in self.calls()))

    def test_安装失败不停止或配置应用(self):
        self.make_apk()
        result = self.run_script('start', FAIL_COMMAND='install')
        self.assertEqual(result.returncode, 17)
        calls = self.calls()
        self.assertFalse(any('force-stop' in call or 'run-as' in call or 'python3' in call
                             or 'reverse' in call for call in calls))
        self.assert_not_started()

    def test_帮助镜像构建纯编译停止不探测设备或地址(self):
        for command in ['help', 'build-image', 'build', 'down']:
            with self.subTest(command=command):
                self.trace.write_text('')
                result = self.run_script(command, BANGUMI_METRO_HOST='not-an-ip',
                                         BANGUMI_ADB_BIN='/missing/adb', FAIL_COMMAND='ip')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(call[0] in ['ip', 'adb'] for call in self.calls()))


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
