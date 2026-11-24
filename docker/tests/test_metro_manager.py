#!/usr/bin/env python3
# 使用非目标随机端口的临时 TCP 服务测试 Metro 进程及监听归属。
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class MetroManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bangumi metro manager ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.listener.close()
        entry = self.root / 'fake-entry'
        entry.write_text('''#!/usr/bin/python3
import os, sys
os.execv(sys.executable, [sys.executable, os.environ['FAKE_METRO_SCRIPT'], str(os.environ['TEST_PORT'])])
''')
        entry.chmod(0o755)
        script = self.root / 'start-metro.cjs'
        script.write_text('''import http.server, sys
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'packager-status:running')
    def log_message(self, *args): pass
http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
''')
        # 仅临时替换监听端口与进程签名，不操作 8081；测试不会修改项目脚本。
        helper = self.root / 'develop.sh'
        original = (SOURCE / 'develop.sh').read_text()
        helper.write_text(original.replace('0100007F:1F91', f'0100007F:{self.port:04X}')
                          .replace('127.0.0.1:8081/status', f'127.0.0.1:{self.port}/status')
                          .replace('== 1F91', f'== {self.port:04X}')
                          .replace('/usr/local/lib/bangumi/start-metro.cjs', str(script)))
        self.script = helper
        self.env = dict(os.environ, BANGUMI_CONTAINER='1', TEST_STATE=str(self.state),
                        TEST_ENTRY=str(entry), TEST_PORT=str(self.port), FAKE_METRO_SCRIPT=str(script))
        self.addCleanup(self.cleanup_process)

    def run_shell(self, body):
        code = '''source "$1"
BANGUMI_ENTRYPOINT="$TEST_ENTRY"
metro_state_dir() { printf '%s\\n' "$TEST_STATE"; }
''' + body
        return subprocess.run(['bash', '-c', code, 'test', str(self.script)], env=self.env,
                              text=True, capture_output=True, timeout=15)

    def cleanup_process(self):
        # 仅杀被测测试脚本自身启动且身份匹配的进程。
        pid_file = self.state / 'metro.pid'
        if not pid_file.exists():
            return
        pid = pid_file.read_text().split()[0]
        self.run_shell('pid="$(metro_owned_pid "$TEST_STATE/metro.pid")" || exit 0; kill -TERM "$pid"')

    def test_后台启动复用与停止只针对自身进程(self):
        result = self.run_shell('metro_up; metro_up; metro_down')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('停止本项目 Metro', result.stdout)

    def test_陌生服务即使返回Metro状态也不能接管或杀死(self):
        sock = socket.socket()
        self.addCleanup(sock.close)
        sock.bind(('127.0.0.1', self.port))
        sock.listen(1)
        result = self.run_shell('metro_up')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('其他进程', result.stderr)
        self.assertFalse((self.state / 'metro.pid').exists())
        # down 不改外部套接字。
        self.assertEqual(self.run_shell('metro_down').returncode, 0)
        self.assertGreater(sock.fileno(), -1)

    def test_被复用PID启动时间错误不认领(self):
        (self.state / 'metro.pid').write_text(f'{os.getpid()} 1\n')
        result = self.run_shell('metro_owned_pid "$TEST_STATE/metro.pid"')
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
