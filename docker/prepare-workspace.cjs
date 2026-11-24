/*
 * 首次进入容器时准备仓库中的 Android 依赖，不切换宿主默认 iOS 配置。
 * 只管理带本工具标记的 node_modules；未知依赖绝不覆盖。
 */
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { spawnSync } = require('node:child_process')

// Yarn 1 removes extraneous top-level dot files, but preserves dot directories.
const STATE_DIRECTORY = '.bangumi-android-dependencies'
const MARKER = path.join(STATE_DIRECTORY, 'state.json')
const SCHEMA = 1

function fail(message) {
  throw new Error(`[bangumi-init] ${message}`)
}

function realDirectory(directory, label, create = false) {
  if (!fs.existsSync(directory) && !fs.lstatSync(path.dirname(directory)).isSymbolicLink() && create) {
    fs.mkdirSync(directory)
  }
  const stat = fs.lstatSync(directory)
  if (!stat.isDirectory() || stat.isSymbolicLink()) fail(`${label} must be a real directory: ${directory}`)
  return stat
}

function dependencyFingerprint(workspace) {
  const hash = crypto.createHash('sha256')
  hash.update(`bangumi-android-dependencies:${SCHEMA}:${process.platform}:${process.arch}:${process.version}\n`)
  const add = file => {
    hash.update(`${path.relative(workspace, file)}\0`)
    hash.update(fs.readFileSync(file))
    hash.update('\0')
  }
  const walk = directory => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(file)
      else add(file)
    }
  }
  add(path.join(workspace, 'package.json'))
  walk(path.join(workspace, 'patches'))
  walk(path.join(workspace, 'eslint-rules'))
  return hash.digest('hex')
}

function readMarker(file) {
  if (!fs.existsSync(file)) {
    try {
      if (fs.lstatSync(file).isSymbolicLink()) fail('Dependency marker must not be a symbolic link')
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
    }
    return null
  }
  if (!fs.lstatSync(file).isFile() || fs.lstatSync(file).isSymbolicLink()) fail('Invalid dependency marker')
  let marker
  try {
    marker = JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    fail('Invalid dependency marker; preserve the directory and inspect it manually')
  }
  if (marker.schema !== SCHEMA || marker.environment !== 'android' ||
      !['installing', 'ready'].includes(marker.status) || typeof marker.fingerprint !== 'string') {
    fail('Unrecognized dependency marker; refusing to modify existing dependencies')
  }
  return marker
}

function writeMarker(file, marker) {
  const temporary = `${file}.${process.pid}.tmp`
  fs.writeFileSync(temporary, `${JSON.stringify(marker, null, 2)}\n`, { flag: 'wx', mode: 0o600 })
  fs.renameSync(temporary, file)
}

function dependenciesPresent(modules, manifest) {
  try {
    const installed = JSON.parse(fs.readFileSync(path.join(modules, 'react-native', 'package.json'), 'utf8'))
    return installed.version === manifest.dependencies['react-native'] &&
      fs.statSync(path.join(modules, '.yarn-integrity')).isFile()
  } catch {
    return false
  }
}

// Yarn 1 的 .bin 可能保存容器绝对路径。改成模块树内的相对链接，
// 让同一 Linux/架构/工具版本的宿主也能使用自己的仓库目录。
function makeDependencyLinksRelative(modules, workspaceModules) {
  const roots = [modules, workspaceModules]
  const walk = directory => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(file)
      else if (entry.isSymbolicLink()) {
        const destination = fs.readlinkSync(file)
        if (!path.isAbsolute(destination)) continue
        const root = roots.find(prefix => destination.startsWith(`${prefix}${path.sep}`))
        if (!root) continue
        const relative = path.relative(path.dirname(file), path.join(modules, path.relative(root, destination)))
        fs.unlinkSync(file)
        fs.symlinkSync(relative, file)
      }
    }
  }
  walk(modules)
}

function syncRuntimeInputs(repo, workspace) {
  // Copy only common entry/resolver inputs. Android package/app/Babel stay isolated.
  // Refreshing here also handles editor atomic saves without stale single-file binds.
  for (const name of ['index.js', 'index.android.js', 'tsconfig.json', 'metro.config.js']) {
    const source = path.join(repo, name)
    const target = path.join(workspace, name)
    if (!fs.statSync(source).isFile()) fail(`Missing repository runtime input: ${name}`)
    try {
      if (fs.lstatSync(target).isSymbolicLink()) fail(`Runtime input must not be a symbolic link: ${name}`)
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
    }
    fs.copyFileSync(source, target)
  }
}

function prepare({ repo, workspace, command = 'init', run = spawnSync, log = console.log }) {
  if (!['init', 'check', 'sync'].includes(command)) fail('Usage: prepare-workspace.cjs [init | check | sync]')
  if (command === 'sync') {
    syncRuntimeInputs(repo, workspace)
    return { installed: false }
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(workspace, 'package.json'), 'utf8'))
  if (manifest.name !== 'android') fail('Expected the isolated Android manifest, not the host root manifest')
  realDirectory(repo, 'Repository')
  const modules = path.join(repo, 'node_modules')
  const workspaceModules = path.join(workspace, 'node_modules')
  if (command === 'check' && !fs.existsSync(modules)) fail('Dependencies are not ready; run bangumi init')
  const stat = realDirectory(modules, 'Repository node_modules', command === 'init')
  const runtimeStat = fs.statSync(workspaceModules)
  if (stat.dev !== runtimeStat.dev || stat.ino !== runtimeStat.ino) {
    fail('Runtime node_modules must refer to the same repository directory; use docker/compose.yml')
  }
  const stateDirectory = path.join(modules, STATE_DIRECTORY)
  try {
    const state = fs.lstatSync(stateDirectory)
    if (!state.isDirectory() || state.isSymbolicLink()) fail('Dependency state must be a real directory')
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
  }
  const markerFile = path.join(modules, MARKER)
  const marker = readMarker(markerFile)
  if (!marker && fs.readdirSync(modules).length !== 0) {
    fail('Existing node_modules is not managed by this Android container; back it up or move it aside yourself. Nothing was overwritten')
  }
  const fingerprint = dependencyFingerprint(workspace)
  if (marker?.status === 'ready' && marker.fingerprint === fingerprint && dependenciesPresent(modules, manifest)) {
    if (command === 'init') syncRuntimeInputs(repo, workspace)
    log('[bangumi-init] Android dependencies are ready; reusing repository node_modules')
    return { installed: false, fingerprint }
  }
  if (command === 'check') fail('Android dependencies are missing or changed; run bangumi init')
  const nextMarker = { schema: SCHEMA, environment: 'android', status: 'installing', fingerprint }
  if (!fs.existsSync(stateDirectory)) fs.mkdirSync(stateDirectory)
  writeMarker(markerFile, nextMarker)
  const result = run('yarn', ['install', '--no-lockfile', '--non-interactive'], {
    cwd: workspace,
    stdio: 'inherit',
    env: { ...process.env, CI: '1', YARN_CACHE_FOLDER: process.env.YARN_CACHE_FOLDER || '/home/dev/.cache/yarn' }
  })
  if (result.error || result.status !== 0) fail('Dependency installation failed; bangumi init can retry this managed directory')
  const patched = run(path.join(workspaceModules, '.bin', 'patch-package'), ['--error-on-fail'], {
    cwd: workspace, stdio: 'inherit', env: { ...process.env, CI: '1' }
  })
  if (patched.error || patched.status !== 0) fail('Android patches failed; do not start the app until bangumi init succeeds')
  if (!dependenciesPresent(modules, manifest)) fail('The installed dependencies do not match the Android manifest')
  makeDependencyLinksRelative(modules, workspaceModules)
  writeMarker(markerFile, { ...nextMarker, status: 'ready' })
  syncRuntimeInputs(repo, workspace)
  log('[bangumi-init] Android dependencies are ready in the real repository directory')
  return { installed: true, fingerprint }
}

if (require.main === module) {
  try {
    if (process.env.BANGUMI_CONTAINER !== '1' || process.getuid() === 0) fail('Run as the non-root Dev Container user')
    if (process.argv.length > 3) fail('Usage: prepare-workspace.cjs [init | check | sync]')
    prepare({ repo: '/repo', workspace: '/workspace', command: process.argv[2] || 'init' })
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}

module.exports = { prepare, dependencyFingerprint, makeDependencyLinksRelative, syncRuntimeInputs, MARKER }
