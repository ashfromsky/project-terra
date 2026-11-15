import { spawn, spawnSync } from 'node:child_process'
import { existsSync as fsExistsSync, mkdirSync, readFileSync } from 'node:fs'
import net from 'node:net'
import path from 'node:path'

const DEFAULT_CORE_HOST = '127.0.0.1'
const DEFAULT_CORE_PORT = 8000
const DEFAULT_GHS_HOST = '127.0.0.1'
const DEFAULT_GHS_PORT = 8080
const DEFAULT_FRONTEND_PORT = 5173
const DEFAULT_READY_TIMEOUT_MS = 30_000
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 3_000

export function parseDotEnvContent(content) {
  const parsed = {}
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) {
      continue
    }
    const eqIndex = line.indexOf('=')
    if (eqIndex <= 0) {
      continue
    }
    const key = line.slice(0, eqIndex).trim()
    if (!key) {
      continue
    }
    let value = line.slice(eqIndex + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    parsed[key] = value
  }
  return parsed
}

export function loadEffectiveEnv(rootDir, baseEnv = process.env) {
  const envPath = path.join(rootDir, '.env')
  let fileEnv = {}
  if (fsExistsSync(envPath)) {
    try {
      fileEnv = parseDotEnvContent(readFileSync(envPath, 'utf8'))
    } catch {
      fileEnv = {}
    }
  }
  return { ...fileEnv, ...baseEnv }
}

function parsePort(raw, fallback, varName) {
  if (raw === undefined || raw === '') {
    return fallback
  }
  const parsed = Number(raw)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`Invalid ${varName}="${raw}": expected an integer TCP port (1-65535).`)
  }
  return parsed
}

export function buildPresets(rootDir, env = process.env) {
  const coreHost = env.CORE_HOST || DEFAULT_CORE_HOST
  const corePort = parsePort(env.CORE_PORT, DEFAULT_CORE_PORT, 'CORE_PORT')
  const ghsHost = env.GHS_HOST || DEFAULT_GHS_HOST
  const ghsPort = parsePort(env.GHS_PORT, DEFAULT_GHS_PORT, 'GHS_PORT')
  const frontendPortExplicit = Boolean(env.FRONTEND_PORT)
  const frontendPort = parsePort(env.FRONTEND_PORT, DEFAULT_FRONTEND_PORT, 'FRONTEND_PORT')

  const dataDir = path.join(rootDir, '.data')
  const coreDatabaseUrl = env.DATABASE_URL || `sqlite+aiosqlite:///${path.join(dataDir, 'terra.db')}`
  const ghsDatabaseUrl = env.GHS_DATABASE_URL || `sqlite+aiosqlite:///${path.join(dataDir, 'ghs.db')}`
  const scientificArtifactDir = env.SCIENTIFIC_ARTIFACT_DIR || path.join(dataDir, 'artifacts')
  const localStorageDir = env.LOCAL_STORAGE_DIR || path.join(dataDir, 'ghs_storage')
  const ghsBaseUrl = env.GHS_BASE_URL || `http://${ghsHost}:${ghsPort}`

  const sharedCoreEnv = {
    DATABASE_URL: coreDatabaseUrl,
    GHS_BASE_URL: ghsBaseUrl,
    SCIENTIFIC_ARTIFACT_DIR: scientificArtifactDir,
  }
  const sharedGhsEnv = {
    GHS_DATABASE_URL: ghsDatabaseUrl,
    LOCAL_STORAGE_DIR: localStorageDir,
  }

  const coreDir = path.join(rootDir, 'backend', 'core')
  const workerDir = path.join(rootDir, 'backend', 'worker')
  const frontendDir = path.join(rootDir, 'frontend')
  const ghsDir = path.join(rootDir, 'backend', 'services', 'geospatial_harmonization')

  const services = {
    CORE: {
      name: 'CORE',
      description: 'Core Backend (FastAPI + Granian)',
      cwd: coreDir,
      command: 'uv',
      args: [
        'run',
        'granian',
        '--interface',
        'asgi',
        '--host',
        coreHost,
        '--port',
        String(corePort),
        'terra.main:app',
      ],
      host: coreHost,
      port: corePort,
      url: `http://${coreHost}:${corePort}`,
      healthUrl: `http://${coreHost}:${corePort}/health/ready`,
      livenessUrl: `http://${coreHost}:${corePort}/health`,
      dependsOn: [],
      env: sharedCoreEnv,
    },
    'CORE-WORKER': {
      name: 'CORE-WORKER',
      description: 'Core Assessment Worker (terra-worker)',
      cwd: workerDir,
      command: 'uv',
      args: ['run', 'python', '-m', 'terra_worker'],
      host: null,
      port: null,
      url: null,
      healthUrl: null,
      livenessUrl: null,
      dependsOn: ['CORE'],
      env: sharedCoreEnv,
    },
    FRONTEND: {
      name: 'FRONTEND',
      description: 'Frontend SPA (Vite)',
      cwd: frontendDir,
      command: 'pnpm',
      args: frontendPortExplicit ? ['exec', 'vite', '--port', String(frontendPort)] : ['exec', 'vite'],
      host: 'localhost',
      port: frontendPort,
      url: `http://localhost:${frontendPort}`,
      healthUrl: `http://localhost:${frontendPort}/`,
      livenessUrl: `http://localhost:${frontendPort}/`,
      dependsOn: [],
      env: {
        VITE_API_PROXY_TARGET: env.VITE_API_PROXY_TARGET || `http://${coreHost}:${corePort}`,
      },
    },
    GHS: {
      name: 'GHS',
      description: 'Geospatial Harmonization Service API (FastAPI + Granian)',
      cwd: ghsDir,
      command: 'uv',
      args: [
        'run',
        'granian',
        '--interface',
        'asgi',
        '--host',
        ghsHost,
        '--port',
        String(ghsPort),
        'geospatial_harmonization.main:app',
      ],
      host: ghsHost,
      port: ghsPort,
      url: `http://${ghsHost}:${ghsPort}`,
      healthUrl: `http://${ghsHost}:${ghsPort}/ready`,
      livenessUrl: `http://${ghsHost}:${ghsPort}/health`,
      dependsOn: [],
      env: sharedGhsEnv,
    },
    'GHS-WORKER': {
      name: 'GHS-WORKER',
      description: 'Geospatial Harmonization WorkerRunner',
      cwd: ghsDir,
      command: 'uv',
      args: ['run', 'python', '-m', 'geospatial_harmonization.worker'],
      host: null,
      port: null,
      url: null,
      healthUrl: null,
      livenessUrl: null,
      dependsOn: ['GHS'],
      env: sharedGhsEnv,
    },
  }

  return {
    dev: {
      name: 'dev',
      runContracts: true,
      services: [services.CORE, services['CORE-WORKER'], services.FRONTEND],
    },
    'dev-ghs': {
      name: 'dev-ghs',
      runContracts: false,
      services: [services.GHS, services['GHS-WORKER']],
    },
    'dev-full': {
      name: 'dev-full',
      runContracts: true,
      services: [
        services.CORE,
        services.GHS,
        services['CORE-WORKER'],
        services['GHS-WORKER'],
        services.FRONTEND,
      ],
    },
  }
}

export function createLinePrefixer(stream, label, writeLine) {
  let buffer = ''
  return new Promise((resolve) => {
    stream.setEncoding('utf8')
    stream.on('data', (chunk) => {
      buffer += chunk
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        writeLine(`[${label}] ${line}`)
      }
    })
    stream.on('end', () => {
      if (buffer.length > 0) {
        writeLine(`[${label}] ${buffer}`)
        buffer = ''
      }
      resolve()
    })
    stream.on('error', () => {
      resolve()
    })
  })
}

export function defaultHasCommand(command) {
  const probe = process.platform === 'win32' ? 'where' : 'which'
  const result = spawnSync(probe, [command], { stdio: 'ignore' })
  return result.status === 0
}

export function checkPortAvailable(host, port, serviceName) {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', (err) => {
      if (err && typeof err === 'object' && 'code' in err && err.code === 'EADDRINUSE') {
        reject(
          new Error(
            `Port ${port} on ${host} is already in use (required by ${serviceName}). ` +
              `Stop the conflicting process or override the port via environment variables.`,
          ),
        )
        return
      }
      reject(
        new Error(`Unable to bind ${host}:${port} for ${serviceName}: ${err.message}`),
      )
    })
    server.once('listening', () => {
      server.close(() => resolve())
    })
    server.listen(port, host)
  })
}

export async function validateEnvironment(preset, deps = {}) {
  const hasCommand = deps.hasCommand ?? defaultHasCommand
  const existsSync = deps.existsSync ?? fsExistsSync
  const checkPort = deps.checkPort ?? checkPortAvailable

  const seenNames = new Set()
  const requiredCommands = new Set(preset.runContracts ? ['pnpm', 'uv'] : [])

  for (const service of preset.services) {
    if (seenNames.has(service.name)) {
      throw new Error(`Duplicate service "${service.name}" in preset "${preset.name}".`)
    }
    seenNames.add(service.name)
    requiredCommands.add(service.command)

    if (!existsSync(service.cwd)) {
      throw new Error(`Missing service directory for ${service.name}: ${service.cwd}`)
    }
  }

  for (const command of requiredCommands) {
    if (!hasCommand(command)) {
      throw new Error(
        `Required executable "${command}" was not found on PATH. Install it before running "${preset.name}".`,
      )
    }
  }

  await Promise.all(
    preset.services
      .filter((service) => service.port !== null && service.host !== null)
      .map((service) => checkPort(service.host, service.port, service.name)),
  )
}

export async function defaultRunContracts(rootDir, env, writeLine) {
  const frontendDir = path.join(rootDir, 'frontend')
  writeLine('[CONTRACTS] Generating OpenAPI and TypeScript contracts...')
  await new Promise((resolve, reject) => {
    const child = spawn('pnpm', ['contracts:generate'], {
      cwd: frontendDir,
      env: { ...process.env, ...env },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const streams = [
      createLinePrefixer(child.stdout, 'CONTRACTS', writeLine),
      createLinePrefixer(child.stderr, 'CONTRACTS', writeLine),
    ]
    child.once('error', (err) => {
      reject(new Error(`Failed to run contract generation: ${err.message}`))
    })
    child.once('exit', async (code, signal) => {
      await Promise.all(streams)
      if (code === 0) {
        resolve()
        return
      }
      reject(
        new Error(
          `Contract generation failed (${signal ? `signal ${signal}` : `exit code ${code}`}).`,
        ),
      )
    })
  })
}

export async function defaultWaitForReady(service, { timeoutMs = DEFAULT_READY_TIMEOUT_MS, signal } = {}) {
  if (!service.healthUrl) {
    return
  }
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (signal?.aborted) {
      return
    }
    try {
      const response = await fetch(service.healthUrl, {
        signal: signal ?? AbortSignal.timeout(1500),
      })
      if (response.ok) {
        return
      }
    } catch {
      // Service still starting up.
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`Timed out waiting for ${service.name} readiness at ${service.healthUrl}`)
}

export function defaultKillProcessGroup(child, signal) {
  if (!child.pid) {
    return
  }
  if (process.platform !== 'win32') {
    try {
      process.kill(-child.pid, signal)
      return
    } catch (err) {
      if (err && typeof err === 'object' && 'code' in err && err.code === 'ESRCH') {
        return
      }
    }
  }
  child.kill(signal)
}

function defaultSpawnChild(service, baseEnv) {
  return spawn(service.command, service.args, {
    cwd: service.cwd,
    env: { ...baseEnv, ...service.env },
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

function defaultRegisterSignals(handler) {
  const onSigInt = () => handler('SIGINT')
  const onSigTerm = () => handler('SIGTERM')
  process.on('SIGINT', onSigInt)
  process.on('SIGTERM', onSigTerm)
  return () => {
    process.off('SIGINT', onSigInt)
    process.off('SIGTERM', onSigTerm)
  }
}

export async function runOrchestrator(presetName, options = {}) {
  const rootDir = options.rootDir ?? process.cwd()
  const env = options.env ?? loadEffectiveEnv(rootDir, process.env)
  const log = options.log ?? ((line) => console.log(line))
  const error = options.error ?? ((line) => console.error(line))
  const shutdownTimeoutMs = options.shutdownTimeoutMs ?? DEFAULT_SHUTDOWN_TIMEOUT_MS

  if (!options.existsSync) {
    mkdirSync(path.join(rootDir, '.data'), { recursive: true })
  }

  const presets = buildPresets(rootDir, env)
  const preset = presets[presetName]
  if (!preset) {
    throw new Error(
      `Unknown preset "${presetName}". Expected one of: ${Object.keys(presets).join(', ')}.`,
    )
  }

  await validateEnvironment(preset, {
    hasCommand: options.hasCommand,
    existsSync: options.existsSync,
    checkPort: options.checkPort,
  })

  if (preset.runContracts) {
    const runContracts = options.runContracts ?? defaultRunContracts
    await runContracts(rootDir, env, log)
  }

  const spawnChild = options.spawnChild ?? ((service) => defaultSpawnChild(service, env))
  const waitForReady = options.waitForReady ?? defaultWaitForReady
  const killProcessGroup = options.killProcessGroup ?? defaultKillProcessGroup
  const registerSignals = options.registerSignals ?? defaultRegisterSignals

  const activeChildren = new Map()
  const readinessPromises = new Map()
  const streamPromises = []
  const readyAbort = new AbortController()
  let shutdownPromise = null
  let isShuttingDown = false
  let finalExitCode = 0
  let resolveRunDone
  const runDonePromise = new Promise((resolve) => {
    resolveRunDone = resolve
  })

  const shutdown = (reason, exitCode) => {
    if (isShuttingDown) {
      return shutdownPromise
    }
    isShuttingDown = true
    finalExitCode = exitCode
    readyAbort.abort()
    log(`[ORCHESTRATOR] Stopping ${preset.name} (${reason})...`)

    shutdownPromise = (async () => {
      const entries = [...activeChildren.entries()]
      if (entries.length === 0) {
        resolveRunDone(finalExitCode)
        return finalExitCode
      }

      const exitWaiters = entries.map(([, entry]) => entry.exitPromise)

      for (const [, entry] of entries) {
        if (!entry.exited) {
          killProcessGroup(entry.child, 'SIGTERM')
        }
      }

      const timer = setTimeout(() => {
        for (const [name, entry] of entries) {
          if (!entry.exited) {
            error(`[ORCHESTRATOR] ${name} did not exit in time; sending SIGKILL.`)
            killProcessGroup(entry.child, 'SIGKILL')
          }
        }
      }, shutdownTimeoutMs)
      timer.unref()

      await Promise.allSettled(exitWaiters)
      clearTimeout(timer)

      const flushTimer = new Promise((resolve) => setTimeout(resolve, 250))
      await Promise.race([Promise.allSettled(streamPromises), flushTimer])
      resolveRunDone(finalExitCode)
      return finalExitCode
    })()

    return shutdownPromise
  }

  const unregisterSignals = registerSignals((sig) => {
    void shutdown(`received ${sig}`, 0)
  })

  try {
    for (const service of preset.services) {
      if (activeChildren.has(service.name)) {
        throw new Error(`Attempted to start ${service.name} more than once.`)
      }

      if (service.dependsOn && service.dependsOn.length > 0) {
        const depWaits = service.dependsOn
          .map((dep) => readinessPromises.get(dep))
          .filter(Boolean)
        if (depWaits.length > 0) {
          await Promise.all(depWaits)
        }
      }

      if (isShuttingDown || readyAbort.signal.aborted) {
        break
      }

      const child = spawnChild(service)
      let resolveExit
      const exitPromise = new Promise((resolve) => {
        resolveExit = resolve
      })

      const entry = {
        service,
        child,
        exited: false,
        exitPromise,
      }
      activeChildren.set(service.name, entry)

      if (child.stdout) {
        streamPromises.push(createLinePrefixer(child.stdout, service.name, log))
      }
      if (child.stderr) {
        streamPromises.push(createLinePrefixer(child.stderr, service.name, error))
      }

      const endpointNote = service.url
        ? `${service.url} (health: ${service.livenessUrl})`
        : 'worker loop (no HTTP port)'
      log(`[ORCHESTRATOR] Starting ${service.name} -> ${endpointNote}`)

      child.once('error', (err) => {
        entry.exited = true
        resolveExit()
        if (!isShuttingDown) {
          error(`[ORCHESTRATOR] Failed to start ${service.name}: ${err.message}`)
          void shutdown(`${service.name} failed to start`, 1)
        }
      })

      child.once('exit', (code, signal) => {
        entry.exited = true
        resolveExit()
        if (!isShuttingDown) {
          const reason = signal
            ? `${service.name} terminated by signal ${signal}`
            : `${service.name} exited unexpectedly with code ${code ?? 1}`
          error(`[ORCHESTRATOR] ${reason}`)
          void shutdown(reason, typeof code === 'number' && code !== 0 ? code : 1)
        }
      })

      const readyPromise = waitForReady(service, { signal: readyAbort.signal })
        .then(() => {
          if (!readyAbort.signal.aborted && !entry.exited) {
            const readyMsg = service.healthUrl
              ? `ready at ${service.url} (probe: ${service.healthUrl})`
              : 'running'
            log(`[ORCHESTRATOR] ${service.name} is ${readyMsg}`)
          }
        })
        .catch((err) => {
          if (!readyAbort.signal.aborted && !isShuttingDown) {
            error(`[ORCHESTRATOR] ${err.message}`)
            void shutdown(`${service.name} failed readiness check`, 1)
          }
        })
      readinessPromises.set(service.name, readyPromise)
    }

    await runDonePromise

    return { exitCode: finalExitCode }
  } finally {
    unregisterSignals()
  }
}
