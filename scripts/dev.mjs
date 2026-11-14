import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { runOrchestrator } from './dev-orchestrator.mjs'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(scriptDir, '..')
const preset = process.argv[2]

if (!preset) {
  console.error('Usage: node scripts/dev.mjs <dev|dev-ghs|dev-full>')
  process.exit(2)
}

try {
  const { exitCode } = await runOrchestrator(preset, { rootDir })
  process.exit(exitCode)
} catch (err) {
  const message = err instanceof Error ? err.message : String(err)
  console.error(`[ORCHESTRATOR] ${message}`)
  process.exit(1)
}
