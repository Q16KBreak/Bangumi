'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')
const { prepare, MARKER } = require('../prepare-workspace.cjs')

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bangumi workspace '))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const repo = path.join(root, 'repo')
  const workspace = path.join(root, 'workspace')
  const modules = path.join(repo, 'node_modules')
  fs.mkdirSync(modules, { recursive: true })
  fs.mkdirSync(path.join(workspace, 'patches'), { recursive: true })
  fs.mkdirSync(path.join(workspace, 'eslint-rules'))
  fs.symlinkSync(modules, path.join(workspace, 'node_modules'))
  fs.writeFileSync(path.join(workspace, 'package.json'), JSON.stringify({ name: 'android', dependencies: { 'react-native': '0.72.10' } }))
  fs.writeFileSync(path.join(repo, 'package.json'), '{"name":"ios"}\n')
  fs.writeFileSync(path.join(repo, 'babel.config.js'), 'ios babel\n')
  fs.writeFileSync(path.join(repo, 'app.json'), 'ios app\n')
  for (const file of ['index.js', 'index.android.js', 'tsconfig.json', 'metro.config.js']) {
    fs.writeFileSync(path.join(repo, file), `host ${file}\n`)
  }
  fs.writeFileSync(path.join(workspace, 'babel.config.js'), 'android babel\n')
  fs.writeFileSync(path.join(workspace, 'app.json'), 'android app\n')
  fs.writeFileSync(path.join(workspace, 'patches', 'sample.patch'), 'android patch\n')
  fs.writeFileSync(path.join(workspace, 'eslint-rules', 'index.js'), 'android eslint\n')
  const calls = []
  const run = (command, args, options) => {
    calls.push({ command, args, options })
    if (command === 'yarn') {
      fs.mkdirSync(path.join(modules, 'react-native'), { recursive: true })
      fs.writeFileSync(path.join(modules, 'react-native', 'package.json'), '{"version":"0.72.10"}')
      fs.writeFileSync(path.join(modules, '.yarn-integrity'), '{}')
      fs.mkdirSync(path.join(modules, '.bin'), { recursive: true })
      fs.writeFileSync(path.join(modules, '.bin', 'patch-package'), 'fake executable')
    }
    return { status: 0 }
  }
  const invoke = (command = 'init', extra = {}) => prepare({ repo, workspace, command, run, log() {}, ...extra })
  return { root, repo, workspace, modules, calls, run, invoke }
}

function marker(f) {
  return JSON.parse(fs.readFileSync(path.join(f.modules, MARKER), 'utf8'))
}

test('首次只在真实仓库准备Android依赖并保留根iOS配置', t => {
  const f = fixture(t)
  const result = f.invoke()
  assert.equal(result.installed, true)
  assert.deepEqual(f.calls[0].args, ['install', '--no-lockfile', '--non-interactive'])
  assert.equal(f.calls[0].options.cwd, f.workspace)
  assert.equal(f.calls[0].options.env.CI, '1')
  assert.equal(f.calls[1].command, path.join(f.workspace, 'node_modules', '.bin', 'patch-package'))
  assert.deepEqual(f.calls[1].args, ['--error-on-fail'])
  assert.equal(marker(f).status, 'ready')
  assert.equal(fs.readFileSync(path.join(f.repo, 'package.json'), 'utf8'), '{"name":"ios"}\n')
  assert.equal(fs.readFileSync(path.join(f.repo, 'babel.config.js'), 'utf8'), 'ios babel\n')
  assert.equal(fs.readFileSync(path.join(f.workspace, 'babel.config.js'), 'utf8'), 'android babel\n')
  assert.equal(fs.readFileSync(path.join(f.workspace, 'index.js'), 'utf8'), 'host index.js\n')
  for (const file of ['yarn.lock', 'package-lock.json']) assert.equal(fs.existsSync(path.join(f.repo, file)), false)
})

test('已有匹配依赖只复用，保留模块内原生增量产物', t => {
  const f = fixture(t)
  f.invoke()
  fs.mkdirSync(path.join(f.modules, 'react-native', 'build'))
  fs.writeFileSync(path.join(f.modules, 'react-native', 'build', 'native.o'), 'keep')
  f.calls.length = 0
  assert.equal(f.invoke().installed, false)
  assert.equal(f.calls.length, 0)
  assert.equal(f.invoke('check').installed, false)
  assert.equal(f.calls.length, 0)
  assert.equal(fs.readFileSync(path.join(f.modules, 'react-native', 'build', 'native.o'), 'utf8'), 'keep')
})

test('业务与通用配置变化不重装依赖，重新启动可刷新原子替换文件', t => {
  const f = fixture(t)
  f.invoke()
  f.calls.length = 0
  const file = path.join(f.repo, 'metro.config.js')
  fs.writeFileSync(`${file}.new`, 'new resolver\n')
  fs.renameSync(`${file}.new`, file)
  assert.equal(f.invoke().installed, false)
  assert.equal(f.calls.length, 0)
  assert.equal(fs.readFileSync(path.join(f.workspace, 'metro.config.js'), 'utf8'), 'new resolver\n')
})

test('补丁或插件输入变化才更新受管理的依赖', t => {
  const f = fixture(t)
  f.invoke()
  const old = marker(f).fingerprint
  fs.writeFileSync(path.join(f.workspace, 'patches', 'sample.patch'), 'updated patch\n')
  assert.throws(() => f.invoke('check'), /run bangumi init/)
  f.calls.length = 0
  assert.equal(f.invoke().installed, true)
  assert.notEqual(marker(f).fingerprint, old)
  assert.equal(f.calls[0].command, 'yarn')
})

test('未知已有依赖不覆盖、不安装也不添加管理标记', t => {
  const f = fixture(t)
  fs.writeFileSync(path.join(f.modules, 'user-data'), 'keep')
  assert.throws(() => f.invoke(), /not managed/)
  assert.equal(f.calls.length, 0)
  assert.equal(fs.readFileSync(path.join(f.modules, 'user-data'), 'utf8'), 'keep')
  assert.equal(fs.existsSync(path.join(f.modules, MARKER)), false)
})

test('拒绝宿主依赖符号链接和错误的运行视图', t => {
  const f = fixture(t)
  fs.rmdirSync(f.modules)
  const external = path.join(f.root, 'external')
  fs.mkdirSync(external)
  fs.symlinkSync(external, f.modules)
  assert.throws(() => f.invoke(), /real directory/)
  fs.unlinkSync(f.modules)
  fs.mkdirSync(f.modules)
  fs.unlinkSync(path.join(f.workspace, 'node_modules'))
  fs.mkdirSync(path.join(f.workspace, 'node_modules'))
  assert.throws(() => f.invoke(), /same repository directory/)
  assert.equal(f.calls.length, 0)
})

test('安装失败保持可识别状态，检查失败，初始化可重试', t => {
  const f = fixture(t)
  assert.throws(() => f.invoke('init', { run: () => ({ status: 17 }) }), /installation failed/)
  assert.equal(marker(f).status, 'installing')
  assert.throws(() => f.invoke('check'), /run bangumi init/)
  assert.equal(f.invoke().installed, true)
  assert.equal(marker(f).status, 'ready')
})

test('Yarn清理顶层dot文件后失败仍可识别并重试受管目录', t => {
  const f = fixture(t)
  assert.throws(() => f.invoke('init', { run() {
    for (const entry of fs.readdirSync(f.modules, { withFileTypes: true })) {
      if (entry.name.startsWith('.') && entry.isFile()) fs.unlinkSync(path.join(f.modules, entry.name))
    }
    fs.writeFileSync(path.join(f.modules, 'partial-package'), 'generated during install')
    return { status: 1 }
  } }), /installation failed/)
  assert.equal(marker(f).status, 'installing')
  assert.equal(f.invoke().installed, true)
  assert.equal(marker(f).status, 'ready')
})

test('补丁失败或错误的RN版本不能标记为准备完成', t => {
  const f = fixture(t)
  assert.throws(() => f.invoke('init', { run(command, args, options) {
    return command === 'yarn' ? f.run(command, args, options) : { status: 1 }
  } }), /patches failed/)
  assert.equal(marker(f).status, 'installing')
  assert.throws(() => f.invoke('init', { run(command, args, options) {
    const result = f.run(command, args, options)
    if (command === 'yarn') fs.writeFileSync(path.join(f.modules, 'react-native', 'package.json'), '{"version":"0.88.1"}')
    return result
  } }), /do not match/)
  assert.equal(marker(f).status, 'installing')
})

test('安装后的Yarn绝对链接改为相对链接，宿主路径可解析', t => {
  const f = fixture(t)
  f.invoke('init', { run(command, args, options) {
    const result = f.run(command, args, options)
    if (command === 'yarn') {
      fs.writeFileSync(path.join(f.modules, 'react-native', 'cli.js'), 'fake cli')
      fs.symlinkSync(path.join(f.workspace, 'node_modules', 'react-native', 'cli.js'), path.join(f.modules, '.bin', 'rn'))
    }
    return result
  } })
  const link = path.join(f.modules, '.bin', 'rn')
  assert.equal(fs.readlinkSync(link), '../react-native/cli.js')
  assert.equal(fs.realpathSync(link), path.join(f.modules, 'react-native', 'cli.js'))
})

test('标记损坏或为符号链接时拒绝修改现有内容', t => {
  const f = fixture(t)
  const file = path.join(f.modules, MARKER)
  fs.mkdirSync(path.dirname(file))
  fs.writeFileSync(file, 'not json')
  assert.throws(() => f.invoke(), /Invalid dependency marker/)
  fs.unlinkSync(file)
  fs.symlinkSync(path.join(f.repo, 'package.json'), file)
  assert.throws(() => f.invoke(), /Invalid dependency marker/)
  assert.equal(f.calls.length, 0)
})

test('仅同步通用入口，不覆盖Android专用配置或写宿主文件', t => {
  const f = fixture(t)
  f.invoke('sync')
  assert.equal(f.calls.length, 0)
  assert.equal(fs.readFileSync(path.join(f.workspace, 'index.android.js'), 'utf8'), 'host index.android.js\n')
  assert.equal(fs.readFileSync(path.join(f.workspace, 'app.json'), 'utf8'), 'android app\n')
  fs.unlinkSync(path.join(f.workspace, 'index.js'))
  fs.symlinkSync(path.join(f.repo, 'index.js'), path.join(f.workspace, 'index.js'))
  assert.throws(() => f.invoke('sync'), /must not be a symbolic link/)
})
