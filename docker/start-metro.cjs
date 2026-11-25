/*
 * @Author: Q16KBreak
 *
 * Docker 专用 Expo 启动器：固定回环广告与绑定，保留上游服务器和文件监听。
 */
'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')

// 手机通过 adb reverse 访问自身的 127.0.0.1:8081。
process.env.REACT_NATIVE_PACKAGER_HOSTNAME = '127.0.0.1'

// Expo 49's CI mode disables file watching, not just terminal interaction. Compose
// uses non-TTY input, so CI is neither necessary nor appropriate for Metro.
delete process.env.CI

const projectRoot = '/repo'
const resolveFromProject = request => require.resolve(request, { paths: [projectRoot] })
const cliPackagePath = resolveFromProject('@expo/cli/package.json')
const cliPackage = require(cliPackagePath)
assert.equal(cliPackage.name, '@expo/cli', 'Expected the project-local official Expo CLI package.')
assert.equal(typeof cliPackage.main, 'string', 'Expo CLI no longer exposes its JavaScript entry.')
const cliRoot = path.dirname(cliPackagePath)
const cliEntry = resolveFromProject(path.resolve(cliRoot, cliPackage.main))
assert.ok(cliEntry.startsWith(`${cliRoot}${path.sep}`), 'Expo CLI entry escaped its own package.')

const serverPath = resolveFromProject('@expo/cli/build/src/start/server/metro/runServer-fork')
const serverModule = require(serverPath)
const descriptor = Object.getOwnPropertyDescriptor(serverModule, 'runServer')
assert.ok(descriptor?.writable, 'Expo runServer export is no longer writable; review this launcher.')
const originalRunServer = serverModule.runServer
assert.equal(typeof originalRunServer, 'function', 'Expo runServer export is not a function.')
assert.equal(originalRunServer.length, 3, 'Expo runServer API changed; review this launcher.')

// Patch only this process's one Expo export before the CLI loads instantiateMetro.
// Reuse the upstream server, middleware, sockets and watchers without touching
// node_modules on disk, host Metro config, or NODE_OPTIONS in Metro workers.
serverModule.runServer = function (metroBundler, config, options) {
  assert.equal(metroBundler?.projectRoot, projectRoot, 'Unexpected Metro project root.')
  assert.equal(config?.server?.port, 8081, 'This launcher only serves Metro on port 8081.')
  assert.ok(options && typeof options === 'object', 'Expo runServer options API changed.')
  assert.equal(typeof options.watch, 'boolean', 'Expo no longer supplies its watch option.')
  return originalRunServer.call(this, metroBundler, config, {
    ...options,
    host: '127.0.0.1',
    watch: true
  })
}

// The expo package's bin may be a shell wrapper in this old SDK. Load @expo/cli's
// own JavaScript entry in-process, preserving the runServer wrapper above.
process.argv = [process.execPath, cliEntry, 'start', '--localhost', '--port', '8081', '--max-workers', '4']
require(cliEntry)
