#!/usr/bin/env python3
# @Author: Q16KBreak
#
# 不启动 Docker daemon，检查 Compose 安全边界和镜像依赖层的缓存输入。
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

DOCKER = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('docker'), '未安装 Docker CLI，跳过 Compose 解析')
class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(['docker', 'compose', '-f', str(DOCKER / 'compose.yml'),
                                 'config', '--format', 'json'],
                                env=dict(os.environ, LOCAL_UID='2345', LOCAL_GID='3456', BANGUMI_BUILD_JOBS='2'),
                                check=True, capture_output=True, text=True, timeout=20)
        cls.config = json.loads(result.stdout)
        cls.service = cls.config['services']['dev']

    def test_只共享宿主网络而不映射端口或特权设备(self):
        service = self.service
        self.assertEqual(service['network_mode'], 'host')
        for key in ['ports', 'devices', 'privileged']:
            self.assertFalse(service.get(key))
        self.assertIn('ALL', service['cap_drop'])
        self.assertIn('no-new-privileges:true', service['security_opt'])
        self.assertEqual(service['environment']['ADB_SERVER_SOCKET'], 'tcp:127.0.0.1:5037')
        for key in ['BANGUMI_METRO_HOST', 'REACT_NATIVE_PACKAGER_HOSTNAME', 'BANGUMI_NONINTERACTIVE']:
            self.assertNotIn(key, service['environment'])

    def test_构建与运行沿用相同非root身份(self):
        self.assertEqual(self.service['user'], '2345:3456')
        args = self.service['build']['args']
        self.assertEqual(str(args['LOCAL_UID']), '2345')
        self.assertEqual(str(args['LOCAL_GID']), '3456')
        self.assertEqual(str(self.service['environment']['BANGUMI_BUILD_JOBS']), '2')

    def test_宿主绑定只包含开发输入且不覆盖镜像依赖配置(self):
        allowed = {'/workspace/src', '/workspace/android', '/workspace/index.js',
                   '/workspace/index.android.js', '/workspace/tsconfig.json', '/workspace/metro.config.js'}
        bindings = [v for v in self.service['volumes'] if v['type'] == 'bind']
        self.assertEqual({v['target'] for v in bindings}, allowed)
        for binding in bindings:
            self.assertFalse(binding.get('bind', {}).get('create_host_path', True))
            self.assertEqual(binding.get('read_only', False), binding['target'] != '/workspace/android')
            self.assertNotIn('.android', Path(binding['source']).parts)
            self.assertNotIn('docker.sock', binding['source'])

    def test_缓存不会覆盖整个node_modules或HOME(self):
        caches = [v for v in self.service['volumes'] if v['type'] == 'volume']
        self.assertEqual(len(caches), 7)
        for volume in caches:
            self.assertNotIn(volume['target'], ['/workspace', '/workspace/node_modules', '/home/dev'])
        self.assertTrue(self.service.get('healthcheck'))


class CacheInputTests(unittest.TestCase):
    def test_依赖安装阶段不接受业务源码或易变运行配置(self):
        text = (DOCKER / 'Dockerfile').read_text().replace('\\\n', ' ')
        stage = ''
        copy_inputs = []
        installation = False
        for line in text.splitlines():
            match = re.match(r'FROM\s+.*\s+AS\s+(\S+)', line, re.I)
            if match:
                stage = match[1]
            if stage != 'dependencies':
                continue
            if line.startswith('COPY '):
                copy_inputs.append(line)
            if 'yarn install' in line:
                installation = True
        self.assertTrue(installation)
        self.assertTrue(copy_inputs)
        for line in copy_inputs:
            for forbidden in ['src/', 'android/', 'app.json', 'babel.config.js', 'entrypoint.sh', 'README', 'COPY . .']:
                self.assertNotIn(forbidden, line)

    def test_源码和密钥不纳入构建上下文(self):
        rules = [line.strip() for line in (DOCKER / 'Dockerfile.dockerignore').read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(rules[0], '**')
        # 白名单只能开放工具、清单、补丁和本地插件，不能开放业务/原生源码或私钥。
        allowed = ('docker/', 'packages/', 'eslint-rules/', 'app.json', 'babel.config.js')
        for rule in rules:
            if rule.startswith('!'):
                self.assertTrue(rule[1:].startswith(allowed), rule)
                self.assertNotIn('node_modules', rule)
                self.assertNotIn('keystore', rule)
                self.assertNotIn('.env', rule)


if __name__ == '__main__':
    unittest.main(verbosity=2)
