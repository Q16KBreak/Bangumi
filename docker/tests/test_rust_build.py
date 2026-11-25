#!/usr/bin/env python3
# @Author: Q16KBreak
#
# 不启动 Docker / Rust / NDK / 网络，用临时目录和假命令验证 build-rust.sh 的 Linux 构建流程。
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

DOCKER = Path(__file__).resolve().parents[1]
SCRIPT = DOCKER / 'build-rust.sh'


class RustBuildScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = self.root / 'project'
        self.rust = self.project / 'android' / 'rust'
        self.rust.mkdir(parents=True)
        (self.rust / 'Cargo.toml').write_text('[package]\nname = "ech-proxy"\n')
        self.prefix = self.rust / 'openssl' / 'install'
        self.source = self.rust / 'openssl' / 'build' / 'openssl-4.0.1'
        self.ndk = self.root / 'android-sdk' / 'ndk' / '30.0.16248370'
        self.toolchain = self.ndk / 'toolchains' / 'llvm' / 'prebuilt' / 'linux-x86_64' / 'bin'
        self.toolchain.mkdir(parents=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.log'

        self.env = {key: value for key, value in os.environ.items()
                    if key not in {'BANGUMI_BUILD_JOBS', 'ANDROID_HOME', 'ANDROID_NDK_HOME',
                                   'ANDROID_NDK_ROOT', 'OPENSSL_DIR', 'OPENSSL_INCLUDE_DIR',
                                   'OPENSSL_LIB_DIR', 'OPENSSL_STATIC'}}
        self.env['PATH'] = f"{self.bin}:{self.env['PATH']}"
        self.env['ANDROID_HOME'] = str(self.root / 'android-sdk')
        self.env['ANDROID_NDK_HOME'] = str(self.ndk)
        self.env['FAKE_LOG'] = str(self.log)
        self.env['FAKE_PREFIX'] = str(self.prefix)
        self._write_commands()

    def _command(self, path, body):
        path.write_text('#!/usr/bin/env bash\nset -eu\n' + textwrap.dedent(body).lstrip('\n'))
        path.chmod(0o755)

    def _write_commands(self):
        self._command(self.toolchain / 'llvm-ar', r'''
            printf 'llvm-ar args=%s\n' "$*" >> "$FAKE_LOG"
            [ -f "$2" ] || { printf 'archive missing: %s\n' "$2" >&2; exit 1; }
            printf 'object-bytes\n'
        ''')
        self._command(self.toolchain / 'llvm-nm', r'''
            printf 'llvm-nm args=%s\n' "$*" >> "$FAKE_LOG"
            cat >/dev/null
            if [ "${FAKE_NO_THREADS:-0}" = 1 ]; then
              printf '00000000 T CRYPTO_THREAD_run_once\n'
            else
              printf '00000000 T CRYPTO_THREAD_write_lock\n'
            fi
        ''')
        self._command(self.bin / 'curl', r'''
            printf 'curl args=%s\n' "$*" >> "$FAKE_LOG"
        ''')
        self._command(self.bin / 'tar', r'''
            printf 'tar args=%s\n' "$*" >> "$FAKE_LOG"
            dir=''
            previous=''
            for arg in "$@"; do
              if [ "$previous" = '-C' ]; then dir="$arg"; fi
              previous="$arg"
            done
            [ -n "$dir" ] || exit 2
            src="$dir/openssl-4.0.1"
            mkdir -p "$src"
            cat > "$src/Configure" <<'CONFIGURE'
            #!/usr/bin/env bash
            printf '%s\n' "$@" > "$PWD/configure.args"
            if [ "${FAKE_CONFIGURE_FAIL:-0}" = 1 ]; then exit 1; fi
            CONFIGURE
            chmod +x "$src/Configure"
        ''')
        self._command(self.bin / 'make', r'''
            printf 'make cwd=%s args=%s\n' "$PWD" "$*" >> "$FAKE_LOG"
            if [ "${FAKE_MAKE_FAIL:-0}" = 1 ] && [ "${1#-j}" != "$1" ]; then
              printf 'fake make failure\n' >&2
              exit 1
            fi
            if [ "$1" = 'install_sw' ]; then
              mkdir -p "$FAKE_PREFIX/lib" "$FAKE_PREFIX/include/openssl"
              : > "$FAKE_PREFIX/lib/libssl.a"
              : > "$FAKE_PREFIX/lib/libcrypto.a"
              : > "$FAKE_PREFIX/include/openssl/ech.h"
            fi
        ''')
        self._command(self.bin / 'nproc', r'''
            printf 'nproc\n' >> "$FAKE_LOG"
            printf '%s\n' "${FAKE_NPROC:-4}"
        ''')
        self._command(self.bin / 'cargo', r'''
            printf 'cargo cwd=%s args=%s\n' "$PWD" "$*" >> "$FAKE_LOG"
            if [ "${FAKE_CARGO_FAIL:-0}" = 1 ]; then
              printf 'fake cargo failure\n' >&2
              exit 1
            fi
            mkdir -p "$PWD/target/aarch64-linux-android/release"
            printf 'fresh-so\n' > "$PWD/target/aarch64-linux-android/release/libechproxy.so"
        ''')

    def _run(self, **environment):
        run_env = dict(self.env)
        run_env.update(environment)
        return subprocess.run(['bash', str(SCRIPT), str(self.project)], env=run_env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def _calls(self, prefix):
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text().splitlines() if line.startswith(prefix)]

    def _seed_openssl_cache(self):
        (self.prefix / 'lib').mkdir(parents=True)
        (self.prefix / 'lib' / 'libssl.a').write_text('cached')
        (self.prefix / 'lib' / 'libcrypto.a').write_text('cached')
        (self.prefix / '.threads-ok').write_text('')
        (self.prefix / '.toolchain').write_text(f'4.0.1|{self.ndk}\n')

    def _reset_openssl_state(self):
        shutil.rmtree(self.rust / 'openssl', ignore_errors=True)
        if self.log.exists():
            self.log.unlink()

    def _jni_library(self):
        return self.project / 'android' / 'app' / 'src' / 'main' / 'jniLibs' / 'arm64-v8a' / 'libechproxy.so'

    def test_缺少源码时自动下载且无需TTY(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any('openssl-4.0.1.tar.gz' in line for line in self._calls('curl')))
        self.assertNotIn('是否自动下载', result.stdout + result.stderr)
        self.assertTrue((self.source / 'configure.args').exists())

    def test_已校验的OpenSSL缓存直接复用(self):
        self._seed_openssl_cache()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        for prefix in ('curl', 'tar', 'make', 'llvm-ar'):
            self.assertEqual(self._calls(prefix), [], prefix)
        self.assertFalse((self.source / 'configure.args').exists())
        self.assertTrue(self._calls('cargo'))

    def test_旧OpenSSL缓存没有工具链标记时重新编译(self):
        self._seed_openssl_cache()
        (self.prefix / '.toolchain').unlink()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._calls('make'))
        self.assertEqual((self.prefix / '.toolchain').read_text(), f'4.0.1|{self.ndk}\n')

    def test_更换NDK时不复用旧编译器的OpenSSL缓存(self):
        self._seed_openssl_cache()
        custom = self.root / 'updated rust ndk'
        shutil.copytree(self.ndk, custom)
        result = self._run(ANDROID_NDK_HOME=str(custom))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._calls('make'))
        self.assertEqual((self.prefix / '.toolchain').read_text(), f'4.0.1|{custom}\n')

    def test_换NDK安装后线程失败不留下旧成功标记且回退必须重编(self):
        self._seed_openssl_cache()
        custom = self.root / 'failing new ndk'
        shutil.copytree(self.ndk, custom)
        failed = self._run(ANDROID_NDK_HOME=str(custom), FAKE_NO_THREADS='1')
        self.assertNotEqual(failed.returncode, 0)
        self.assertTrue(any('install_sw' in line for line in self._calls('make')))
        self.assertFalse((self.prefix / '.threads-ok').exists())
        self.assertFalse((self.prefix / '.toolchain').exists())
        self.log.write_text('')
        recovered = self._run()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertTrue(self._calls('make'))
        self.assertEqual((self.prefix / '.toolchain').read_text(), f'4.0.1|{self.ndk}\n')

    def test_Rust_NDK使用镜像环境配置而不绑定默认版本目录(self):
        custom = self.root / 'custom rust ndk'
        shutil.copytree(self.ndk, custom)
        self._command(custom / 'toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-ar', r'''
            printf 'custom-ndk-selected\n' >> "$FAKE_LOG"
            printf 'object-bytes\n'
        ''')
        result = self._run(ANDROID_NDK_HOME=str(custom))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._calls('custom-ndk-selected'), ['custom-ndk-selected'])

    def test_并发数优先使用BANGUMI_BUILD_JOBS(self):
        result = self._run(BANGUMI_BUILD_JOBS='3', FAKE_NPROC='9')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any('args=-j3' in line for line in self._calls('make')))
        self.assertNotIn('-j9', ' '.join(self._calls('make')))
        self.assertEqual(self._calls('nproc'), [])

    def test_未覆盖时使用nproc(self):
        result = self._run(FAKE_NPROC='6')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any('args=-j6' in line for line in self._calls('make')))

    def test_OpenSSL配置使用API21与no_shared但不传static标志(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.source / 'configure.args').read_text().splitlines()
        self.assertEqual(args[:2], ['android-arm64', '-D__ANDROID_API__=21'])
        self.assertIn(f'--prefix={self.prefix}', args)
        self.assertIn(f'--openssldir={self.prefix}', args)
        self.assertIn('no-shared', args)
        self.assertIn('no-tests', args)
        self.assertNotIn('-static', args)

    def test_线程校验通过后写入缓存标记(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._calls('llvm-nm'))
        self.assertTrue((self.prefix / '.threads-ok').exists())

    def test_线程校验失败则中止(self):
        result = self._run(FAKE_NO_THREADS='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('多线程', result.stderr)
        self.assertFalse((self.prefix / '.threads-ok').exists())
        self.assertEqual(self._calls('cargo'), [])

    def test_OpenSSL阶段失败不会继续后续构建(self):
        for failure in ('FAKE_CONFIGURE_FAIL', 'FAKE_MAKE_FAIL'):
            with self.subTest(failure=failure):
                self._reset_openssl_state()
                result = self._run(**{failure: '1'})
                self.assertNotEqual(result.returncode, 0)
                if failure == 'FAKE_CONFIGURE_FAIL':
                    self.assertEqual(self._calls('make'), [])
                else:
                    self.assertTrue(any('args=-j' in line for line in self._calls('make')))
                    self.assertFalse(any('install_sw' in line for line in self._calls('make')))
                self.assertEqual(self._calls('cargo'), [])
                self.assertFalse((self.prefix / '.threads-ok').exists())

    def test_cargo使用locked并复制JNI产物(self):
        self._seed_openssl_cache()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = f'cargo cwd={self.rust} args=ndk -t arm64-v8a --platform 21 build --release --locked'
        self.assertEqual(self._calls('cargo'), [expected])
        self.assertEqual(self._jni_library().read_text(), 'fresh-so\n')

    def test_cargo失败时不复制旧产物(self):
        self._seed_openssl_cache()
        stale = self._jni_library()
        stale.parent.mkdir(parents=True)
        stale.write_text('stale-so\n')
        result = self._run(FAKE_CARGO_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cargo ndk 编译失败', result.stderr)
        self.assertEqual(stale.read_text(), 'stale-so\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
