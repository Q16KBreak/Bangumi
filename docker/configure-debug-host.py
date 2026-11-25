#!/usr/bin/env python3
# @Author: Q16KBreak
#
# 仅转换 React Native 调试偏好的 base64 XML；固定写入 adb reverse 的回环地址。
import base64
import binascii
import re
import sys
import xml.etree.ElementTree as ET

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_XML_BYTES = 1024 * 1024
KEY = 'debug_http_host'
TARGET = '127.0.0.1:8081'
ERROR = '[bangumi] Invalid SharedPreferences input.\n'


class PreferenceTreeBuilder(ET.TreeBuilder):
    def __init__(self):
        super().__init__(insert_comments=True, insert_pis=True)

    def doctype(self, name, pubid, system):
        # 在解析任何 DTD 子集或实体之前失败，包括 UTF-16 编码输入。
        raise ValueError('DTD is not allowed')


def configure_debug_host(payload):
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError('Input is too large')
    # 接受 Android/shell base64 的常规折行，不放过其他非法字节或非规范 padding。
    encoded = re.sub(rb'[ \t\r\n]', b'', payload)
    if encoded:
        xml = base64.b64decode(encoded, validate=True)
        if base64.b64encode(xml) != encoded or len(xml) > MAX_XML_BYTES:
            raise ValueError('Invalid or oversized base64 XML')
        parser = ET.XMLParser(target=PreferenceTreeBuilder())
        root = ET.fromstring(xml, parser=parser)
    else:
        root = ET.Element('map')
    if root.tag != 'map':
        raise ValueError('SharedPreferences root must be map')
    matches = [child for child in root if child.get('name') == KEY]
    if len(matches) > 1:
        raise ValueError('Duplicate debug host key')
    if matches:
        target = matches[0]
        if target.tag != 'string' or len(target):
            raise ValueError('Debug host must be a plain string')
    else:
        target = ET.SubElement(root, 'string', {'name': KEY})
    target.text = TARGET
    result = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if len(result) > MAX_XML_BYTES:
        raise ValueError('Output XML is too large')
    return base64.b64encode(result)


def main():
    try:
        if len(sys.argv) != 1:
            raise ValueError('This helper takes no arguments')
        payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        result = configure_debug_host(payload)
    except (ValueError, binascii.Error, ET.ParseError, LookupError, RecursionError):
        # 不回显 XML、base64、解析异常或其中的偏好值。
        sys.stderr.write(ERROR)
        return 1
    sys.stdout.buffer.write(result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
