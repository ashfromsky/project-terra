import { spawnSync } from 'node:child_process'
import { accessSync, constants, existsSync, mkdirSync } from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  buildPresets,
  checkPortAvailable,
  defaultHasCommand,
  loadEffectiveEnv,
} from './dev-orchestrator.mjs'

async function probeHttp(url) {
  try {
    const resp = await fetch(url, { signal: AbortSignal.timeout(1500) })
    return { reachable: true, ok: resp.ok, status: resp.status }
  } catch {
    return { reachable: false, ok: false, status: null }
  }
}

function checkDirectoryWritable(dirPath) {
  try {
    mkdirSync(dirPath, { recursive: true })
    accessSync(dirPath, constants.W_OK | constants.R_OK)
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}

function extractSqlitePath(url) {
  if (!url || !url.startsWith('sqlite')) {
    return null
  }
  const idx = url.indexOf(':///')
  if (idx === -1) {
    return null
  }
  const rawPath = url.slice(idx + 4)
  if (!rawPath || rawPath === ':memory:') {
    return null
  }
  return rawPath.startsWith('/') ? rawPath : `/${rawPath}`
}

function parseExternalDatabaseEndpoint(url) {
  try {
    const parsed = new URL(url)
    return {
      host: parsed.hostname.replace(/^\[|\]$/g, ''),
      port: parsed.port ? Number(parsed.port) : 5432,
    }
  } catch {
    return null
  }
}

function probeTcpEndpoint(host, port, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port })
    let settled = false
    const finish = (result) => {
      if (settled) {
        return
      }
      settled = true
      socket.destroy()
      resolve(result)
    }
    socket.setTimeout(timeoutMs)
    socket.once('connect', () => finish({ reachable: true }))
    socket.once('timeout', () => finish({ reachable: false, error: `timed out after ${timeoutMs} ms` }))
    socket.once('error', (err) => finish({ reachable: false, error: err.code ?? err.message }))
  })
}

function checkWorkerImport(cwd, moduleName) {
  const result = spawnSync('uv', ['run', 'python', '-c', `import ${moduleName}`], {
    cwd,
    encoding: 'utf8',
    timeout: 15_000,
  })
  return {
    ok: result.status === 0,
    error: result.status === 0 ? null : (result.stderr || result.stdout || `exit ${result.status}`).trim(),
  }
}

function validateS3EndpointUrl(endpointUrl, bucketName) {
  if (!endpointUrl || !endpointUrl.trim()) {
    return { valid: true, warning: 'S3_ENDPOINT_URL omitted (defaulting to standard AWS endpoint)' }
  }
  let parsed
  try {
    parsed = new URL(endpointUrl.trim())
  } catch {
    return { valid: false, error: 'S3_ENDPOINT_URL is not a valid URL' }
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    return { valid: false, error: `unsupported scheme '${parsed.protocol}' in S3_ENDPOINT_URL` }
  }
  const cleanPath = parsed.pathname.replace(/^\/+|\/+$/g, '')
  if (cleanPath && bucketName && cleanPath.toLowerCase() === bucketName.trim().toLowerCase()) {
    return {
      valid: false,
      error: `S3_ENDPOINT_URL must not include '/${bucketName.trim()}' bucket path suffix (use account-level endpoint)`,
    }
  }
  return { valid: true, endpoint: `${parsed.origin}${cleanPath ? `/${cleanPath}` : ''}` }
}

function defaultProbeS3Storage(coreDir, env) {
  const pyCode = [
    'import asyncio, sys',
    'from terra.config import Settings',
    'from terra.infrastructure.object_storage import build_core_object_storage',
    's = Settings(_env_file=None)',
    'store = build_core_object_storage(s)',
    'ok = asyncio.run(store.check_health())',
    'sys.exit(0 if ok else 1)',
  ].join('; ')
  const res = spawnSync('uv', ['run', 'python', '-c', pyCode], {
    cwd: coreDir,
    env: { ...process.env, ...env },
    encoding: 'utf8',
    timeout: 15_000,
  })
  return {
    ok: res.status === 0,
    error: res.status === 0 ? null : (res.stderr || res.stdout || `exit ${res.status}`).trim().slice(0, 160),
  }
}

export async function runDoctor({ rootDir, env: overrideEnv, hasCommand = defaultHasCommand, checkPort = checkPortAvailable, probeDb = probeTcpEndpoint, probeStorage } = {}) {
  const resolvedRoot = rootDir ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const env = overrideEnv ?? loadEffectiveEnv(resolvedRoot, process.env)
  const presets = buildPresets(resolvedRoot, env)
  const checks = []
  let hasFailures = false

  const record = (name, status, detail) => {
    checks.push({ name, status, detail })
    if (status === 'fail') {
      hasFailures = true
    }
  }

  for (const cmd of ['node', 'pnpm', 'uv', 'python3']) {
    if (hasCommand(cmd)) {
      record(`dep:${cmd}`, 'pass', 'installed')
    } else {
      record(`dep:${cmd}`, 'fail', 'missing from PATH')
    }
  }

  const envExists = existsSync(path.join(resolvedRoot, '.env'))
  const exampleExists = existsSync(path.join(resolvedRoot, '.env.example'))
  record('config:env', envExists ? 'pass' : 'warn', envExists ? '.env present' : '.env missing (run cp .env.example .env)')
  record('config:env.example', exampleExists ? 'pass' : 'warn', exampleExists ? '.env.example present' : '.env.example missing')

  const coreService = presets['dev-full'].services.find((s) => s.name === 'CORE')
  const ghsService = presets['dev-full'].services.find((s) => s.name === 'GHS')
  const frontendService = presets['dev-full'].services.find((s) => s.name === 'FRONTEND')
  const coreWorkerService = presets['dev-full'].services.find((s) => s.name === 'CORE-WORKER')
  const ghsWorkerService = presets['dev-full'].services.find((s) => s.name === 'GHS-WORKER')

  const coreDb = coreService?.env.DATABASE_URL ?? ''
  const ghsDb = ghsService?.env.GHS_DATABASE_URL ?? ''
  if (!coreDb || !ghsDb) {
    record('db:config', 'fail', 'DATABASE_URL or GHS_DATABASE_URL missing')
  } else if (coreDb === ghsDb) {
    record('db:isolation', 'fail', 'Core DATABASE_URL and GHS_DATABASE_URL must be distinct')
  } else {
    record('db:isolation', 'pass', 'Core DB and GHS DB are independently configured')
  }

  for (const [label, dbUrl] of [
    ['db:core', coreDb],
    ['db:ghs', ghsDb],
  ]) {
    const sqlitePath = extractSqlitePath(dbUrl)
    if (sqlitePath) {
      const writable = checkDirectoryWritable(path.dirname(sqlitePath))
      record(label, writable.ok ? 'pass' : 'fail', writable.ok ? `SQLite parent writable (${path.dirname(sqlitePath)})` : writable.error)
    } else if (dbUrl) {
      const endpoint = parseExternalDatabaseEndpoint(dbUrl)
      if (!endpoint) {
        record(label, 'fail', 'external database URL is not parseable')
      } else {
        const probe = await probeDb(endpoint.host, endpoint.port)
        record(
          label,
          probe.reachable ? 'pass' : 'fail',
          probe.reachable
            ? `TCP reachable (${endpoint.host}:${endpoint.port})`
            : `TCP unreachable (${endpoint.host}:${endpoint.port}): ${probe.error}`,
        )
      }
    }
  }

  const ghsBase = env.GHS_BASE_URL || ghsService?.url || 'http://127.0.0.1:8080'
  record('addressing:ghs', ghsBase === ghsService?.url ? 'pass' : 'warn', `GHS_BASE_URL=${ghsBase}, GHS listen=${ghsService?.url}`)

  const artifactDir = env.SCIENTIFIC_ARTIFACT_DIR || path.join(resolvedRoot, '.data', 'artifacts')
  const storageDir = env.LOCAL_STORAGE_DIR || path.join(resolvedRoot, '.data', 'ghs_storage')
  for (const [label, dir] of [
    ['storage:artifacts', artifactDir],
    ['storage:ghs', storageDir],
  ]) {
    const writable = checkDirectoryWritable(dir)
    record(label, writable.ok ? 'pass' : 'fail', writable.ok ? `writable (${dir})` : writable.error)
  }

  for (const service of [coreService, ghsService, frontendService].filter(Boolean)) {
    try {
      await checkPort(service.host, service.port, service.name)
      record(`port:${service.name}`, 'pass', `${service.host}:${service.port} available`)
    } catch {
      const probe = await probeHttp(service.healthUrl)
      if (probe.reachable) {
        record(
          `port:${service.name}`,
          probe.ok ? 'pass' : 'warn',
          `${service.url} already active (status=${probe.status})`,
        )
      } else {
        record(`port:${service.name}`, 'fail', `Port ${service.port} occupied by non-TERRA process`)
      }
    }
  }

  if (coreWorkerService && existsSync(coreWorkerService.cwd)) {
    const res = checkWorkerImport(coreWorkerService.cwd, 'terra_worker')
    record('worker:core', res.ok ? 'pass' : 'fail', res.ok ? 'terra_worker importable' : res.error)
  }
  if (ghsWorkerService && existsSync(ghsWorkerService.cwd)) {
    const res = checkWorkerImport(ghsWorkerService.cwd, 'geospatial_harmonization.worker')
    record('worker:ghs', res.ok ? 'pass' : 'fail', res.ok ? 'geospatial_harmonization.worker importable' : res.error)
  }

  const hasEarthdata = Boolean(env.EARTHDATA_TOKEN && env.EARTHDATA_TOKEN.trim().length > 0)
  const hasGithubOauth = Boolean(
    env.GITHUB_CLIENT_ID && env.GITHUB_CLIENT_ID.trim().length > 0 && env.GITHUB_CLIENT_SECRET && env.GITHUB_CLIENT_SECRET.trim().length > 0,
  )
  record(
    'creds:earthdata',
    hasEarthdata ? 'pass' : 'warn',
    hasEarthdata ? 'configured' : 'not configured (required for live MODIS/GPM/SMAP downloads; NASA POWER works without it)',
  )
  record(
    'creds:github_oauth',
    hasGithubOauth ? 'pass' : 'warn',
    hasGithubOauth ? 'configured' : 'not configured (dev session available in development environment)',
  )
  const storageBackend = (env.STORAGE_BACKEND || 'local').trim().toLowerCase()
  const hasS3Bucket = Boolean(env.S3_BUCKET && env.S3_BUCKET.trim().length > 0)
  const accessKey = env.S3_ACCESS_KEY_ID || env.AWS_ACCESS_KEY_ID || ''
  const secretKey = env.S3_SECRET_ACCESS_KEY || env.AWS_SECRET_ACCESS_KEY || ''
  const hasAwsKeys = Boolean(accessKey.trim() && secretKey.trim())
  const endpointCheck = validateS3EndpointUrl(env.S3_ENDPOINT_URL || '', env.S3_BUCKET || '')

  if (!endpointCheck.valid) {
    record('creds:s3_endpoint', 'fail', endpointCheck.error)
  } else if (storageBackend === 's3') {
    record(
      'creds:s3_endpoint',
      env.S3_ENDPOINT_URL ? 'pass' : 'warn',
      endpointCheck.endpoint ?? endpointCheck.warning,
    )
  }

  record(
    'creds:storage',
    storageBackend === 'local' || (hasS3Bucket && hasAwsKeys && endpointCheck.valid) ? 'pass' : 'fail',
    storageBackend === 'local'
      ? 'local filesystem backend'
      : `s3 backend (bucket=${hasS3Bucket ? 'set' : 'missing'}, keys=${hasAwsKeys ? 'configured' : 'missing'}, region=${env.S3_REGION || 'auto'})`,
  )

  if (storageBackend === 's3' && hasS3Bucket && hasAwsKeys && endpointCheck.valid) {
    const storageProbeFn =
      probeStorage ??
      (coreWorkerService && existsSync(path.join(resolvedRoot, 'backend/core'))
        ? (probeEnv) => defaultProbeS3Storage(path.join(resolvedRoot, 'backend/core'), probeEnv)
        : null)
    if (storageProbeFn) {
      const storageProbe = await storageProbeFn(env)
      record(
        'storage:s3_bucket',
        storageProbe.ok ? 'pass' : 'fail',
        storageProbe.ok
          ? `R2/S3 bucket reachable (${env.S3_BUCKET})`
          : `R2/S3 bucket check failed: ${storageProbe.error || 'HeadBucket error'}`,
      )
    }
  }

  return { ok: !hasFailures, checks }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const result = await runDoctor()
  for (const check of result.checks) {
    const tag = check.status === 'pass' ? 'PASS' : check.status === 'warn' ? 'WARN' : 'FAIL'
    console.log(`[${tag}] ${check.name}: ${check.detail}`)
  }
  process.exit(result.ok ? 0 : 1)
}
