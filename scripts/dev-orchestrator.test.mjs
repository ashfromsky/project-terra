import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import net from 'node:net'
import { PassThrough } from 'node:stream'
import test from 'node:test'

import {
  buildPresets,
  checkPortAvailable,
  createLinePrefixer,
  runOrchestrator,
  validateEnvironment,
} from './dev-orchestrator.mjs'

function createFakeChild(pid = 10001) {
  const child = new EventEmitter()
  child.pid = pid
  child.stdout = new PassThrough()
  child.stderr = new PassThrough()
  child.exitCode = null
  child.signalCode = null
  child.killedSignals = []
  child.once('exit', () => {
    child.stdout.end()
    child.stderr.end()
  })
  child.kill = (sig = 'SIGTERM') => {
    child.killedSignals.push(sig)
    return true
  }
  return child
}

test('buildPresets defines expected services, working dirs, and contract hooks', () => {
  const presets = buildPresets('/repo', {})

  assert.deepEqual(Object.keys(presets), ['dev', 'dev-ghs', 'dev-full'])

  assert.equal(presets.dev.runContracts, true)
  assert.deepEqual(
    presets.dev.services.map((s) => s.name),
    ['CORE', 'FRONTEND'],
  )

  assert.equal(presets['dev-ghs'].runContracts, false)
  assert.deepEqual(
    presets['dev-ghs'].services.map((s) => s.name),
    ['GHS', 'GHS-WORKER'],
  )

  assert.equal(presets['dev-full'].runContracts, true)
  assert.deepEqual(
    presets['dev-full'].services.map((s) => s.name),
    ['CORE', 'FRONTEND', 'GHS', 'GHS-WORKER'],
  )

  for (const preset of Object.values(presets)) {
    const names = preset.services.map((s) => s.name)
    assert.equal(new Set(names).size, names.length, 'duplicate service in preset')
  }

  const [core, frontend, ghs, ghsWorker] = presets['dev-full'].services
  assert.equal(core.cwd, '/repo/backend/core')
  assert.equal(core.command, 'uv')
  assert.equal(core.healthUrl, 'http://127.0.0.1:8000/health/ready')

  assert.equal(frontend.cwd, '/repo/frontend')
  assert.equal(frontend.command, 'pnpm')
  assert.equal(frontend.healthUrl, 'http://localhost:5173/')

  assert.equal(ghs.cwd, '/repo/backend/services/geospatial_harmonization')
  assert.equal(ghs.command, 'uv')
  assert.equal(ghs.healthUrl, 'http://127.0.0.1:8080/ready')

  assert.equal(ghsWorker.cwd, ghs.cwd)
  assert.equal(ghsWorker.command, 'uv')
  assert.deepEqual(ghsWorker.args, ['run', 'python', '-m', 'geospatial_harmonization.worker'])
})

test('createLinePrefixer prefixes multiline chunks and flushes trailing partial line', () => {
  const output = []
  const stream = new PassThrough()
  const done = createLinePrefixer(stream, 'CORE', (line) => output.push(line))

  stream.write('first line\nsecond ')
  stream.write('line\nlast partial')
  stream.end()

  return done.then(() => {
    assert.deepEqual(output, [
      '[CORE] first line',
      '[CORE] second line',
      '[CORE] last partial',
    ])
  })
})

test('checkPortAvailable detects an occupied TCP port with actionable message', async () => {
  const server = net.createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  assert.ok(address && typeof address === 'object')

  try {
    await assert.rejects(
      () => checkPortAvailable('127.0.0.1', address.port, 'CORE'),
      (err) => {
        assert.match(err.message, /CORE/)
        assert.match(err.message, new RegExp(String(address.port)))
        return true
      },
    )
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
})

test('validateEnvironment reports missing required executables', async () => {
  const presets = buildPresets('/repo', {})
  await assert.rejects(
    () =>
      validateEnvironment(presets.dev, {
        hasCommand: (cmd) => cmd !== 'uv',
        existsSync: () => true,
        checkPort: async () => {},
      }),
    (err) => {
      assert.match(err.message, /uv/)
      return true
    },
  )
})

test('runOrchestrator runs contracts before spawning frontend and starts each service once', async () => {
  const events = []
  const children = new Map()
  let nextPid = 2000

  const result = await runOrchestrator('dev', {
    rootDir: '/repo',
    env: {},
    hasCommand: () => true,
    existsSync: () => true,
    checkPort: async () => {},
    runContracts: async () => {
      events.push('contracts')
    },
    spawnChild: (service) => {
      events.push(`spawn:${service.name}`)
      const child = createFakeChild(nextPid++)
      children.set(service.name, child)
      return child
    },
    waitForReady: async (service) => {
      events.push(`ready:${service.name}`)
    },
    killProcessGroup: (child, signal) => {
      events.push(`kill:${child.pid}:${signal}`)
      child.emit('exit', 0, signal)
    },
    log: () => {},
    error: () => {},
    registerSignals: (handler) => {
      queueMicrotask(() => handler('SIGINT'))
      return () => {}
    },
  })

  assert.equal(result.exitCode, 0)
  assert.equal(events[0], 'contracts')
  assert.equal(events.filter((e) => e.startsWith('spawn:')).length, 2)
  assert.ok(events.includes('spawn:CORE'))
  assert.ok(events.includes('spawn:FRONTEND'))
})

test('runOrchestrator terminates remaining processes on unexpected child exit', async () => {
  const killed = []
  const children = new Map()
  let nextPid = 3000

  const result = await runOrchestrator('dev-ghs', {
    rootDir: '/repo',
    env: {},
    hasCommand: () => true,
    existsSync: () => true,
    checkPort: async () => {},
    runContracts: async () => {},
    spawnChild: (service) => {
      const child = createFakeChild(nextPid++)
      children.set(service.name, child)
      return child
    },
    waitForReady: async () => {},
    killProcessGroup: (child, signal) => {
      killed.push({ pid: child.pid, signal })
      child.emit('exit', 0, signal)
    },
    log: () => {},
    error: () => {},
    registerSignals: () => {
      queueMicrotask(() => {
        children.get('GHS-WORKER').emit('exit', 1, null)
      })
      return () => {}
    },
  })

  assert.notEqual(result.exitCode, 0)
  assert.equal(killed.length, 1)
  assert.equal(killed[0].pid, children.get('GHS').pid)
  assert.equal(killed[0].signal, 'SIGTERM')
})

test('runOrchestrator handles child spawn error and repeated SIGINT idempotently', async () => {
  const killCalls = []
  const children = new Map()
  let nextPid = 4000
  let triggerSignal = null

  const runPromise = runOrchestrator('dev-full', {
    rootDir: '/repo',
    env: {},
    hasCommand: () => true,
    existsSync: () => true,
    checkPort: async () => {},
    runContracts: async () => {},
    spawnChild: (service) => {
      const child = createFakeChild(nextPid++)
      children.set(service.name, child)
      return child
    },
    waitForReady: async () => {},
    killProcessGroup: (child, signal) => {
      killCalls.push({ pid: child.pid, signal })
      child.emit('exit', 0, signal)
    },
    log: () => {},
    error: () => {},
    registerSignals: (handler) => {
      triggerSignal = handler
      return () => {}
    },
  })

  await new Promise((resolve) => setTimeout(resolve, 10))
  triggerSignal('SIGINT')
  triggerSignal('SIGINT')
  triggerSignal('SIGTERM')

  const result = await runPromise
  assert.equal(result.exitCode, 0)
  assert.equal(killCalls.length, 4)

  const failResult = await runOrchestrator('dev', {
    rootDir: '/repo',
    env: {},
    hasCommand: () => true,
    existsSync: () => true,
    checkPort: async () => {},
    runContracts: async () => {},
    spawnChild: (service) => {
      const child = createFakeChild(nextPid++)
      children.set(service.name, child)
      if (service.name === 'CORE') {
        queueMicrotask(() => child.emit('error', new Error('ENOENT')))
      }
      return child
    },
    waitForReady: async () => {},
    killProcessGroup: (child, signal) => {
      child.emit('exit', 0, signal)
    },
    log: () => {},
    error: () => {},
    registerSignals: () => () => {},
  })

  assert.notEqual(failResult.exitCode, 0)
})

test('runOrchestrator aborts before spawning services if contract generation fails', async () => {
  let spawned = 0
  await assert.rejects(
    () =>
      runOrchestrator('dev', {
        rootDir: '/repo',
        env: {},
        hasCommand: () => true,
        existsSync: () => true,
        checkPort: async () => {},
        runContracts: async () => {
          throw new Error('Contract generation failed (exit code 1).')
        },
        spawnChild: () => {
          spawned++
          return createFakeChild(5000)
        },
      }),
    /Contract generation failed/,
  )
  assert.equal(spawned, 0)
})

test('GHS API and Worker share identical cwd and env overrides while respecting custom ports', () => {
  const presets = buildPresets('/repo', {
    CORE_HOST: '127.0.0.1',
    CORE_PORT: '8010',
    GHS_HOST: '127.0.0.1',
    GHS_PORT: '8090',
    FRONTEND_PORT: '5175',
  })

  const [core, frontend, ghs, ghsWorker] = presets['dev-full'].services
  assert.equal(core.healthUrl, 'http://127.0.0.1:8010/health/ready')
  assert.equal(frontend.env.VITE_API_PROXY_TARGET, 'http://127.0.0.1:8010')
  assert.deepEqual(frontend.args, ['exec', 'vite', '--port', '5175'])
  assert.equal(ghs.healthUrl, 'http://127.0.0.1:8090/ready')
  assert.equal(ghs.cwd, ghsWorker.cwd)
  assert.deepEqual(ghs.env, ghsWorker.env)
})
