/* Prepare the real /repo project using the repository's Android environment switch. */
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const PENDING_SWITCH = 'docker/.generated/android-switch.pending'

function fail(message) {
  throw new Error(`[bangumi-init] ${message}`)
}

function switchAndroid(repo, run) {
  const modules = path.join(repo, 'node_modules')
  const { name } = JSON.parse(fs.readFileSync(path.join(repo, 'package.json'), 'utf8'))
  const currentEnv = name === 'bangumi-pro' ? 'ios' : name
  if (!['ios', 'web', 'android'].includes(currentEnv)) fail('Unknown root environment')
  const installed = fs.lstatSync(modules, { throwIfNoEntry: false })
  if (installed && !installed.isDirectory()) fail('node_modules must be a real directory')
  const backup = `packages/${currentEnv}/node_modules`
  if ((installed || currentEnv === 'android') && fs.lstatSync(path.join(repo, backup), { throwIfNoEntry: false })) {
    fail(`Resolve the dependency cache in ${backup} before continuing`)
  }
  if (currentEnv === 'android') return

  // env.js is not transactional. Do not replay its backup step against a root
  // whose manifest changed but whose Babel/app/patch restoration was interrupted.
  const pending = path.join(repo, PENDING_SWITCH)
  fs.mkdirSync(path.dirname(pending), { recursive: true })
  fs.writeFileSync(pending, `${currentEnv} -> android\n`, { flag: 'wx', mode: 0o600 })
  run(process.execPath, ['packages/env.js', 'android'], { cwd: repo, stdio: 'inherit' })
  fs.unlinkSync(pending)
}

function prepareGradle(repo) {
  const gradle = path.join(repo, 'android/gradle.properties')
  if (fs.lstatSync(gradle, { throwIfNoEntry: false })) return
  const template = fs.readFileSync(path.join(repo, 'android/gradle_yours.properties'), 'utf8')
  // JDK 17 rejects MaxPermSize; debug builds do not need release signing.
  const config = template
    .replace(/^(org\.gradle\.jvmargs=.*) -XX:MaxPermSize=\S+(.*)$/m, '#$&\n$1$2')
    .replace(/^MYAPP_RELEASE_/gm, '#$&')
  fs.writeFileSync(gradle, config, { flag: 'wx', mode: 0o600 })
}

function prepare({ repo, command, run = execFileSync, log = console.log, environment = process.env }) {
  if (!['init', 'check'].includes(command)) fail('Usage: prepare-project.cjs <init | check>')
  if (fs.existsSync(path.join(repo, PENDING_SWITCH))) fail('Previous environment switch was interrupted; inspect root configuration and platform caches before clearing docker/.generated/android-switch.pending')
  if (command === 'init') switchAndroid(repo, run)
  const manifest = JSON.parse(fs.readFileSync(path.join(repo, 'package.json'), 'utf8'))
  if (manifest.name !== 'android') fail('Project root is not Android; run bangumi init')
  const modules = path.join(repo, 'node_modules')
  if (command === 'check') {
    if (!fs.statSync(modules, { throwIfNoEntry: false })?.isDirectory()) fail('node_modules is missing; run bangumi init')
    return
  }
  // Yarn's native postinstall applies patch-package; do not run it a second time.
  run('yarn', ['install', '--no-lockfile', '--non-interactive'], {
    cwd: repo, stdio: 'inherit', env: { ...environment, CI: '1', YARN_CACHE_FOLDER: '/home/dev/.cache/yarn' }
  })
  prepareGradle(repo)
  log('[bangumi-init] Android project initialized in /repo')
}

if (require.main === module) {
  try {
    prepare({ repo: '/repo', command: process.argv[2] })
  } catch (error) {
    console.error(error.message)
    process.exitCode = error.status || 1
  }
}

module.exports = { prepare }
