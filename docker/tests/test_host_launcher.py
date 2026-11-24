#!/usr/bin/env python3
# 可选宿主兼容入口只转发；不运行真实 Docker、ADB 或依赖安装。
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'android-debug.sh'


class HostLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bangumi host launcher ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docker = self.root / 'project with spaces' / 'docker'
        self.docker.mkdir(parents=True)
        self.script = self.docker / 'android-debug.sh'
        shutil.copyfile(SOURCE, self.script)
        self.trace = self.root / 'calls.jsonl'
        (self.docker / 'devcontainer-host.sh').write_text(
            '#!/bin/bash\nprintf "initialize %s\\n" "$*" >> "$TRACE"\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        stub = self.bin / 'docker'
        stub.write_text('''#!/usr/bin/python3
import json, os, sys
with open(os.environ['TRACE'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
''')
        stub.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'], TRACE=str(self.trace))

    def run_script(self, *args):
        return subprocess.run(['bash', str(self.script), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def lines(self):
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    def test_帮助和未知命令不初始化镜像或依赖(self):
        self.assertEqual(self.run_script('help').returncode, 0)
        self.assertNotEqual(self.run_script('unknown').returncode, 0)
        self.assertEqual(self.lines(), [])

    def test_显式构建只调用宿主初始化构建选项(self):
        self.assertEqual(self.run_script('build-image').returncode, 0)
        self.assertEqual(self.lines(), ['initialize --build-image'])

    def test_停止不初始化且仅停止dev(self):
        self.assertEqual(self.run_script('down').returncode, 0)
        self.assertEqual(len(self.lines()), 1)
        call = json.loads(self.lines()[0])
        self.assertEqual(call[-2:], ['stop', 'dev'])
        self.assertNotIn('--volumes', call)
        self.assertNotIn('initialize', self.lines()[0])

    def test_构建转发使用同一容器且不要求宿主ADB(self):
        result = self.run_script('build')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lines()[0], 'initialize ')
        calls = [json.loads(line) for line in self.lines()[1:]]
        self.assertEqual(calls[0][-5:], ['--detach', '--wait', '--wait-timeout', '120', 'dev'])
        self.assertEqual(calls[1][-5:], ['exec', '-T', 'dev', '/usr/local/bin/bangumi', 'init'])
        self.assertEqual(calls[2][-5:], ['exec', '-T', 'dev', '/usr/local/bin/bangumi', 'build'])
        self.assertFalse(any('adb' in call for call in calls))

    def test_生成配置存在时转发保留该配置路径(self):
        generated = self.docker / '.generated'
        generated.mkdir()
        override = generated / 'compose.yml'
        override.write_text('services: {}\n')
        self.assertEqual(self.run_script('down').returncode, 0)
        self.assertIn(str(override), json.loads(self.lines()[0]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
