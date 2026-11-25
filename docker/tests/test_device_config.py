#!/usr/bin/env python3
# @Author: Q16KBreak
#
# 仅用 Python 标准库验证固定回环调试偏好转换与容器静态接线，不访问 ADB 或设备。
import base64
from pathlib import Path
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

DOCKER = Path(__file__).resolve().parents[1]
HELPER = DOCKER / 'configure-debug-host.py'
LAN = '192.168.3.13'
TARGET = '127.0.0.1:8081'
ERROR = b'[bangumi] Invalid SharedPreferences input.\n'


class DeviceConfigTests(unittest.TestCase):
    def run_helper(self, payload=b'', args=None):
        return subprocess.run(
            [sys.executable, str(HELPER), *(args if args is not None else [])],
            input=payload, capture_output=True, timeout=10, check=False)

    def configure(self, xml=None, payload=None):
        if payload is None:
            payload = base64.b64encode(xml) if xml is not None else b''
        result = self.run_helper(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'')
        output = base64.b64decode(result.stdout, validate=True)
        self.assertEqual(base64.b64encode(output), result.stdout)
        return ET.fromstring(output), output

    def assert_rejected(self, payload, args=None):
        result = self.run_helper(payload, args)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, ERROR)

    def test_空输入只新增回环调试宿主键(self):
        root, _ = self.configure()
        self.assertEqual(root.tag, 'map')
        self.assertEqual(len(root), 1)
        self.assertEqual(root[0].tag, 'string')
        self.assertEqual(root[0].attrib, {'name': 'debug_http_host'})
        self.assertEqual(root[0].text, TARGET)

    def test_仅替换已有宿主且保留其他偏好和次序(self):
        xml = '''<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<map>
  <boolean name="remote_js_debug" value="true" />
  <boolean name="hot_module_replacement" value="false" />
  <boolean name="hot_module_replacement_enabled" value="false" />
  <boolean name="live_reload" value="true" />
  <string name="secret">私密 &amp; &lt;value&gt;</string>
  <int name="counter" value="42" />
  <long name="timestamp" value="1234567890123" />
  <float name="scale" value="1.25" />
  <set name="tags"><string>甲</string><string>乙</string></set>
  <string name="debug_http_host">192.168.3.13:8081</string>
  <string name="empty" />
</map>'''.encode()
        root, _ = self.configure(xml)
        expected = ET.fromstring(xml)
        expected.find("string[@name='debug_http_host']").text = TARGET
        self.assertEqual(ET.tostring(root), ET.tostring(expected))

    def test_缺失宿主键时保留其他偏好并追加(self):
        root, _ = self.configure(b'<map><boolean name="remote_js_debug" value="false" /></map>')
        self.assertEqual([child.get('name') for child in root], ['remote_js_debug', 'debug_http_host'])
        self.assertEqual(root[0].get('value'), 'false')
        self.assertEqual(root[1].text, TARGET)

    def test_保留注释处理指令和转义值(self):
        xml = b'<map><!-- keep --><?keep value?><string name="keep">a&amp;b&lt;c</string></map>'
        root, output = self.configure(xml)
        self.assertIn(b'<!-- keep -->', output)
        self.assertIn(b'<?keep value?>', output)
        self.assertEqual(root.find("string[@name='keep']").text, 'a&b<c')

    def test_支持规范base64折行与空白空输入(self):
        encoded = base64.b64encode(b'<map><string name="keep">value</string></map>')
        wrapped = b' \t\r\n' + b'\r\n'.join(encoded[i:i + 8] for i in range(0, len(encoded), 8)) + b'\n'
        root, _ = self.configure(payload=wrapped)
        self.assertEqual(root.find("string[@name='keep']").text, 'value')
        root, _ = self.configure(payload=b' \t\r\n')
        self.assertEqual(len(root), 1)
        self.assertEqual(root[0].text, TARGET)

    def test_支持合法UTF16文档且输出UTF8(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><map><string name="keep">值</string></map>'.encode('utf-16')
        root, output = self.configure(xml)
        self.assertEqual(root.find("string[@name='keep']").text, '值')
        self.assertIn(b"encoding='utf-8'", output)

    def test_相同输入重复执行输出稳定(self):
        _, first = self.configure(b'<map><string name="keep">value</string></map>')
        _, second = self.configure(first)
        self.assertEqual(first, second)

    def test_旧局域网调试地址固定改为回环(self):
        root, _ = self.configure(
            b'<map><string name="debug_http_host">192.168.3.13:8081</string></map>')
        self.assertEqual(root[0].text, TARGET)

    def test_无参数接口且任何参数都失败关闭(self):
        root, _ = self.configure()
        self.assertEqual(root[0].text, TARGET)
        for args in [[LAN], ['127.0.0.1'], [LAN, 'extra'], ['--help']]:
            with self.subTest(args=args):
                self.assert_rejected(b'', args)

    def test_拒绝非法或非规范base64且不泄露输入(self):
        for payload in [b'secret!@#', b'AA', b'===', b'====', b'AA===', b'AB==',
                        b'PG1hcC8+====', b'PG1hcC8+\x00', b'PG1hcC8+\xff', b'PG1hcC8+\v']:
            with self.subTest(payload=payload):
                self.assert_rejected(payload)

    def test_拒绝非法XML错误根和非string宿主键(self):
        invalid = [
            b'not XML: secret value', b'<map>', b'<map/><map/>', b'<map>\x00</map>',
            b'<preferences/>', b'<map xmlns="urn:wrong"/>', b'<MAP/>',
            b'<map><int name="debug_http_host" value="1" /></map>',
            b'<map><boolean name="debug_http_host" value="true" /></map>',
            b'<map><set name="debug_http_host"><string>secret</string></set></map>',
            b'<map><string name="debug_http_host"><string>secret</string></string></map>',
            b'<map><string name="debug_http_host">a</string><string name="debug_http_host">b</string></map>',
            b'<map><string name="debug_http_host"/><int name="debug_http_host" value="1"/></map>',
            b'<?xml version="1.0" encoding="unknown-secret"?><map/>',
            b'<?xml version="1.0" encoding="utf-8"?><map>\xff</map>'
        ]
        for xml in invalid:
            with self.subTest(xml=xml):
                self.assert_rejected(base64.b64encode(xml))

    def test_拒绝内部外部及UTF16编码DTD和实体(self):
        documents = [
            '<!DOCTYPE map><map/>',
            '<!DOCTYPE map SYSTEM "file:///secret"><map/>',
            '<!DOCTYPE map SYSTEM "https://example.invalid/secret"><map/>',
            '<!DOCTYPE map [<!ENTITY secret "private">]><map><string name="keep">&secret;</string></map>',
            '<!DOCTYPE map [<!ENTITY secret SYSTEM "file:///secret">]><map/>',
            '<!DOCTYPE map [<!ENTITY a "private"><!ENTITY b "&a;&a;&a;">]><map>&b;</map>'
        ]
        for xml in documents:
            for encoding in ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be']:
                with self.subTest(xml=xml, encoding=encoding):
                    self.assert_rejected(base64.b64encode(xml.encode(encoding)))
        self.assert_rejected(base64.b64encode(b'<map>&undeclared;</map>'))

    def test_编码输入和解码XML均有大小上限(self):
        self.assert_rejected(b' ' * (2 * 1024 * 1024 + 1))
        oversized = b'<map><string name="keep">' + b'x' * (1024 * 1024) + b'</string></map>'
        self.assert_rejected(base64.b64encode(oversized))

    def test_输出扩展超限和异常深度也不输出部分结果或异常内容(self):
        oversized_output = b'<map><string name="keep">' + b'>' * (300 * 1024) + b'</string></map>'
        self.assert_rejected(base64.b64encode(oversized_output))
        nested = b'<map>' + b'<set>' * 2000 + b'</set>' * 2000 + b'</map>'
        self.assert_rejected(base64.b64encode(nested))


class ContainerContractTests(unittest.TestCase):
    def test_Compose仅保留宿主ADB和回环健康检查且不再传递LAN地址(self):
        text = (DOCKER / 'compose.yml').read_text()
        environment = re.search(r'^    environment:\n((?:^      .*\n)+)', text, re.M)
        self.assertIsNotNone(environment)
        self.assertIn('      ADB_SERVER_SOCKET: tcp:127.0.0.1:5037\n', environment[1])
        self.assertNotIn('BANGUMI_METRO_HOST', text)
        self.assertNotIn('REACT_NATIVE_PACKAGER_HOSTNAME', text)
        self.assertIn('    network_mode: host\n', text)
        self.assertNotRegex(text, re.compile(r'^    (?:ports|devices|privileged):', re.M))
        self.assertIn("http://127.0.0.1:8081/status", text)
        self.assertNotIn('0.0.0.0:8081', text)

    def test_entrypoint错误提示固定为回环8081(self):
        text = (DOCKER / 'entrypoint.sh').read_text()
        self.assertIn('loopback development server on 127.0.0.1:8081', text)
        self.assertNotIn('LAN', text)
        self.assertNotIn('BANGUMI_METRO_HOST', text)

    def test_helper与Rust脚本仅在运行层COPY不影响依赖层(self):
        text = (DOCKER / 'Dockerfile').read_text()
        copies = [line for line in text.splitlines() if line.startswith('COPY ')]
        expected = 'COPY --chmod=0644 docker/configure-debug-host.py /usr/local/lib/bangumi/configure-debug-host.py'
        self.assertIn(expected, copies)
        self.assertIn('COPY --chmod=0644 docker/build-rust.sh /usr/local/lib/bangumi/build-rust.sh', copies)
        self.assertEqual(text.count('configure-debug-host.py'), 2)
        prefix = text.split('FROM toolchain AS dev\n', 1)[0]
        self.assertNotIn('configure-debug-host', prefix)
        self.assertNotIn('build-rust.sh', prefix)
        self.assertNotIn('BANGUMI_METRO_HOST', text)
        self.assertIn('python3', prefix)

    def test_构建白名单包含helper但不包含测试(self):
        rules = (DOCKER / 'Dockerfile.dockerignore').read_text().splitlines()
        self.assertIn('!docker/configure-debug-host.py', rules)
        self.assertIn('**/tests/**', rules)
        self.assertNotIn('!docker/tests/', rules)


if __name__ == '__main__':
    unittest.main(verbosity=2)
