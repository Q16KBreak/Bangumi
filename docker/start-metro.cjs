/*
 * @Author: Q16KBreak
 *
 * Docker 专用 Expo 启动器：固定回环广告与绑定，保留上游服务器和文件监听。
 */
'use strict'

const assert = require('node:assert/strict')

// 手机通过 adb reverse 访问自身的 127.0.0.1:8081。
process.env.REACT_NATIVE_PACKAGER_HOSTNAME = '127.0.0.1'

// Expo 49's CI mode disables file watching, not just terminal interaction. Compose
// uses non-TTY input, so CI is neither necessary nor appropriate for Metro.
delete process.env.CI

const projectRoot = '/repo'
const resolveFromProject = request => require.resolve(request, { paths: [projectRoot] })
const cliEntry = resolveFromProject('@expo/cli')
const serverModule = require(resolveFromProject('@expo/cli/build/src/start/server/metro/runServer-fork'))
const originalRunServer = serverModule.runServer

// Patch only this process's one Expo export before the CLI loads instantiateMetro.
// Reuse the upstream server, middleware, sockets and watchers without touching
// node_modules on disk, host Metro config, or NODE_OPTIONS in Metro workers.
serverModule.runServer = function (metroBundler, config, options) {
  assert.equal(metroBundler?.projectRoot, projectRoot, 'Unexpected Metro project root.')
  assert.equal(config?.server?.port, 8081, 'This launcher only serves Metro on port 8081.')
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
