/*
 * @Author: Q16KBreak
 *
 * 无依赖验证 Docker Metro 启动器：隔离模拟 Expo，覆盖固定回环、watch 与 API 漂移保护。
 */
'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const launcherPath = path.resolve(__dirname, '../start-metro.cjs')
const launcherSource = fs.readFileSync(launcherPath, 'utf8')
const cliRoot = '/fixture/node_modules/@expo/cli'
const cliEntry = `${cliRoot}/build/bin/cli`
const serverPath = `${cliRoot}/build/src/start/server/metro/runServer-fork.js`
const allowedBuiltins = ['node:assert/strict', 'node:path']

function createFixture(options = {}) {
  const calls = []
  const resolutions = []
  const requiredModules = []
  const result = { server: 'upstream-server' }
  const bundler = { projectRoot: '/workspace', ...options.bundler }
  const config = { server: { port: 8081 }, ...options.config }
  const serverOptions = Object.hasOwn(options, 'serverOptions')
    ? options.serverOptions
    : { host: '0.0.0.0', watch: false, websocketEndpoints: { hot: 'preserved' }, onReady() {} }
  const fakeProcess = {
    env: {
      CI: '1',
      NODE_OPTIONS: '--max-old-space-size=2048',
      EXPO_NO_TELEMETRY: '1',
      BANGUMI_METRO_HOST: '192.168.3.13',
      REACT_NATIVE_PACKAGER_HOSTNAME: 'host.docker.internal',
      ...options.env
    },
    execPath: '/fixture/bin/node',
    argv: ['old-node', 'old-bin']
  }
  const metadata = {
    name: '@expo/cli',
    main: 'build/bin/cli',
    bin: { 'expo-internal': 'build/bin/cli' },
    ...options.metadata
  }
  const originalRunServer = options.arity === 2
    ? function (metroBundler, metroConfig) {}
    : function (metroBundler, metroConfig, runOptions) {
        calls.push({ receiver: this, bundler: metroBundler, config: metroConfig, options: runOptions })
        return result
      }
  const serverModule = {}
  if (!options.omitExport) {
    Object.defineProperty(serverModule, 'runServer', {
      value: Object.hasOwn(options, 'exportValue') ? options.exportValue : originalRunServer,
      writable: options.writable !== false
    })
  }
  let cliLoaded = false
  let cliResult

  // 只提供白名单模块；旧 LAN 探测所需 net/os 等依赖一旦重新出现就立即失败。
  const fakeRequire = request => {
    requiredModules.push(request)
    if (allowedBuiltins.includes(request)) return require(request)
    if (request === `${cliRoot}/package.json`) return metadata
    if (request === serverPath) return serverModule
    if (request === cliEntry) {
      cliLoaded = true
      assert.equal(fakeProcess.env.CI, undefined, '必须在加载官方 CLI 前移除 CI')
      assert.equal(fakeProcess.env.REACT_NATIVE_PACKAGER_HOSTNAME, '127.0.0.1', '广告地址必须固定为回环')
      assert.equal(fakeProcess.env.BANGUMI_METRO_HOST, undefined, '旧 LAN 环境必须在 CLI 加载前移除')
      cliResult = serverModule.runServer.call(serverModule, bundler, config, serverOptions)
      return {}
    }
    throw new Error(`Unexpected require: ${request}`)
  }
  fakeRequire.resolve = (request, resolveOptions) => {
    // VM 内的数组原型不同，转换后只验证实际路径值。
    assert.deepEqual(Array.from(resolveOptions.paths), ['/workspace'])
    resolutions.push(request)
    if (request === '@expo/cli/package.json') return `${cliRoot}/package.json`
    if (request === '@expo/cli/build/src/start/server/metro/runServer-fork') return serverPath
    if (path.isAbsolute(request)) return request
    throw new Error(`Unexpected resolve: ${request}`)
  }

  return {
    calls,
    resolutions,
    requiredModules,
    bundler,
    config,
    serverOptions,
    fakeProcess,
    result,
    serverModule,
    get cliLoaded() { return cliLoaded },
    get cliResult() { return cliResult },
    start() {
      vm.runInNewContext(launcherSource, { require: fakeRequire, process: fakeProcess }, {
        filename: launcherPath,
        timeout: 1000
      })
    }
  }
}

test('强制回环绑定与 watch 且保留上游参数和返回值', () => {
  const fixture = createFixture()
  fixture.start()
  assert.equal(fixture.calls.length, 1)
  const call = fixture.calls[0]
  assert.equal(call.options.host, '127.0.0.1')
  assert.equal(call.options.watch, true)
  assert.equal(call.options.websocketEndpoints, fixture.serverOptions.websocketEndpoints)
  assert.equal(call.options.onReady, fixture.serverOptions.onReady)
  assert.equal(call.receiver, fixture.serverModule)
  assert.equal(call.bundler, fixture.bundler)
  assert.equal(call.config, fixture.config)
  assert.equal(fixture.cliResult, fixture.result)
  assert.notEqual(call.options, fixture.serverOptions)
  assert.equal(fixture.serverOptions.host, '0.0.0.0')
  assert.equal(fixture.serverOptions.watch, false)
})

test('从项目解析官方 JS 入口并固定 localhost 与 CLI 参数', () => {
  const fixture = createFixture()
  fixture.start()
  assert.equal(fixture.cliLoaded, true)
  const argv = Array.from(fixture.fakeProcess.argv)
  assert.deepEqual(argv, [
    '/fixture/bin/node', cliEntry, 'start', '--localhost', '--port', '8081', '--max-workers', '4'
  ])
  assert.equal(argv.includes('--lan'), false)
  assert.deepEqual(fixture.resolutions, [
    '@expo/cli/package.json', cliEntry, '@expo/cli/build/src/start/server/metro/runServer-fork'
  ])
})

test('仅调整 CI 和广告地址而不改写 NODE_OPTIONS 或宿主进程环境', () => {
  const hostEnv = { ...process.env }
  const fixture = createFixture()
  fixture.start()
  assert.deepEqual(fixture.fakeProcess.env, {
    NODE_OPTIONS: '--max-old-space-size=2048', EXPO_NO_TELEMETRY: '1',
    REACT_NATIVE_PACKAGER_HOSTNAME: '127.0.0.1'
  })
  assert.deepEqual({ ...process.env }, hostEnv)
})

test('外部旧广告环境被覆盖为回环且完全不读取网卡', () => {
  const fixture = createFixture({
    env: { BANGUMI_METRO_HOST: '10.20.30.40', REACT_NATIVE_PACKAGER_HOSTNAME: '192.168.4.13' }
  })
  fixture.start()
  assert.equal(fixture.fakeProcess.env.REACT_NATIVE_PACKAGER_HOSTNAME, '127.0.0.1')
  assert.equal(Object.hasOwn(fixture.fakeProcess.env, 'BANGUMI_METRO_HOST'), false)
  assert.deepEqual(fixture.requiredModules.filter(request => request.startsWith('node:')), allowedBuiltins)
  assert.doesNotMatch(launcherSource, /node:(?:os|net)|networkInterfaces|0\.0\.0\.0|--lan\b/)
})

const loadFailures = [
  ['CLI 包名不匹配', { metadata: { name: 'expo' } }, /official Expo CLI package/],
  ['CLI main 形态漂移', { metadata: { main: null } }, /JavaScript entry/],
  ['CLI main 路径越界', { metadata: { main: '../outside/cli' } }, /escaped its own package/],
  ['runServer 导出消失', { omitExport: true }, /no longer writable/],
  ['runServer 导出只读', { writable: false }, /no longer writable/],
  ['runServer 类型漂移', { exportValue: 42 }, /not a function/],
  ['runServer 参数数量漂移', { arity: 2 }, /API changed/]
]
for (const [description, options, expected] of loadFailures) {
  test(`${description}时拒绝加载 CLI`, () => {
    const fixture = createFixture(options)
    assert.throws(() => fixture.start(), expected)
    assert.equal(fixture.cliLoaded, false)
    assert.equal(fixture.calls.length, 0)
  })
}

const callFailures = [
  ['项目路径漂移', { bundler: { projectRoot: '/other-project' } }, /project root/],
  ['端口漂移', { config: { server: { port: 8090 } } }, /port 8081/],
  ['options 形态漂移', { serverOptions: null }, /options API changed/],
  ['watch 字段消失', { serverOptions: {} }, /watch option/],
  ['watch 类型漂移', { serverOptions: { watch: 'false' } }, /watch option/]
]
for (const [description, options, expected] of callFailures) {
  test(`${description}时拒绝启动上游服务器`, () => {
    const fixture = createFixture(options)
    assert.throws(() => fixture.start(), expected)
    assert.equal(fixture.calls.length, 0)
  })
}
