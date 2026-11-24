#!/usr/bin/env python3
# ADB manager 只用 mock 服务与临时文件验证，不调用真实 adb 或连接设备。
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class AdbManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bangumi adb manager ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.trace = self.root / 'trace'
        self.raw = self.root / 'adb'
        self.raw.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$TRACE"
''')
        self.raw.chmod(0o755)
        self.env = dict(os.environ, BANGUMI_CONTAINER='1', TRACE=str(self.trace),
                        TEST_STATE=str(self.root / 'state'), TEST_RAW=str(self.raw))
        self.env.pop('BANGUMI_ADB_SERVER_MODE', None)

    def run_shell(self, program, **env):
        return subprocess.run(['bash', '-c', program, 'test', str(SOURCE / 'adb-server.sh'),
                               str(SOURCE / 'adb-manager.sh'), str(SOURCE / 'adb.sh')],
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=10)

    def manager(self, body, **env):
        code = '''source "$1"; source "$2"
BANGUMI_ADB_REAL="$TEST_RAW"
bangumi_adb_state_dir() { mkdir -p "$TEST_STATE"; printf '%s\\n' "$TEST_STATE"; }
''' + body
        return self.run_shell(code, **env)

    def calls(self):
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    def test_host服务缺失或协议不兼容时不启动不杀进程(self):
        for probe in ['return 2', 'printf 40']:
            with self.subTest(probe=probe):
                result = self.manager('bangumi_adb_server_version() { ' + probe + '; }; bangumi_ensure_adb',
                                      BANGUMI_ADB_SERVER_MODE='host')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
        result = self.manager('bangumi_adb_server_version() { printf 41; }; bangumi_ensure_adb',
                              BANGUMI_ADB_SERVER_MODE='host')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_container端口被其他服务占用或非法响应不替换(self):
        for probe in ['printf 41', 'return 1']:
            with self.subTest(probe=probe):
                result = self.manager('bangumi_adb_server_version() { ' + probe + '; }; bangumi_ensure_adb')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])

    def test_陈旧或被复用PID不能让外部server被误认(self):
        state = self.root / 'state'
        state.mkdir()
        (state / 'adb.pid').write_text('999999 1\n')
        result = self.manager('bangumi_adb_server_version() { printf 41; }; bangumi_ensure_adb')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('非本容器', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_监听socket只属于真实持有该inode的进程(self):
        # 使用随机本地端口测试 inode 归属，不访问实际 ADB 或 Metro 端口。
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port_hex = f'{listener.getsockname()[1]:04X}'
        code = '''source "$1"; source "$2"
source <(python3 - "$2" "$PORT_HEX" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
print(text.replace('0100007F:13AD', '0100007F:' + sys.argv[2]))
PY
)
bangumi_adb_owns_listener "$TARGET_PID"
'''
        result = self.run_shell(code, PORT_HEX=port_hex, TARGET_PID=str(os.getpid()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.run_shell(code, PORT_HEX=port_hex, TARGET_PID='999999').returncode, 0)

    def test_本机IPv4和IPv6监听均阻止复用同一端口(self):
        for family, host in [(socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')]:
            with self.subTest(family=family):
                listener = socket.socket(family)
                try:
                    listener.bind((host, 0))
                except OSError:
                    listener.close()
                    continue
                listener.listen(1)
                port_hex = f'{listener.getsockname()[1]:04X}'
                code = '''source <(python3 - "$2" "$PORT_HEX" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
print(text.replace('== 13AD', '== ' + sys.argv[2]))
PY
)
bangumi_adb_port_available
'''
                try:
                    result = self.run_shell(code, PORT_HEX=port_hex)
                    self.assertNotEqual(result.returncode, 0)
                finally:
                    listener.close()

    def test_无效模式和非容器拒绝且不调用adb(self):
        self.assertNotEqual(self.manager('bangumi_ensure_adb', BANGUMI_ADB_SERVER_MODE='invalid').returncode, 0)
        self.assertNotEqual(self.manager('bangumi_ensure_adb', BANGUMI_CONTAINER='0').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_wrapper版本和帮助不启动服务且拦截server参数(self):
        code = '''source "$1"; source "$2"
BANGUMI_ADB_REAL="$TEST_RAW"
bangumi_ensure_adb() { printf 'ensure\\n' >> "$TRACE"; }
# 只抽取 wrapper 的参数分发，source 被 mock 的公共路径替代。
source <(python3 - "$3" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
print(text.replace('source /usr/local/lib/bangumi/adb-server.sh', ':')
          .replace('source /usr/local/lib/bangumi/adb-manager.sh', ':'))
PY
) version
'''
        result = self.run_shell(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['version'])
        self.trace.unlink()
        for args in ['-H other devices', '-P5038 devices', '-L tcp:127.0.0.1:1234 devices',
                     '-a devices', 'kill-server', 'server nodaemon', '-s serial kill-server',
                     'pair host:123 123456', 'pair host:123']:
            with self.subTest(args=args):
                result = self.run_shell(code.replace(') version', ') ' + args))
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [])

    def test_wrapper普通命令先确保server且保留带空格序列号(self):
        code = '''source "$1"; source "$2"
BANGUMI_ADB_REAL="$TEST_RAW"
bangumi_ensure_adb() { printf 'ensure\\n' >> "$TRACE"; }
source <(python3 - "$3" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
print(text.replace('source /usr/local/lib/bangumi/adb-server.sh', ':')
          .replace('source /usr/local/lib/bangumi/adb-manager.sh', ':'))
PY
) -s 'device name' shell getprop ro.product.cpu.abilist
'''
        result = self.run_shell(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ['ensure', '-s device name shell getprop ro.product.cpu.abilist'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
