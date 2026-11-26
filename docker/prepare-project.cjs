/* Prepare the real /repo project using the repository's Android environment switch. */
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

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

function prepare({ repo, run = execFileSync }) {
  const options = { cwd: repo, stdio: 'inherit' }
  const { name } = JSON.parse(fs.readFileSync(path.join(repo, 'package.json'), 'utf8'))
  if (name !== 'android') {
    run(process.execPath, ['packages/env.js', 'android'], options)
  }
  run('yarn', ['install', '--no-lockfile', '--non-interactive'], options)
  prepareGradle(repo)
}

if (require.main === module) {
  try {
    prepare({ repo: '/repo' })
  } catch (error) {
    console.error(error.message)
    process.exitCode = error.status || 1
  }
}

module.exports = { prepare }
