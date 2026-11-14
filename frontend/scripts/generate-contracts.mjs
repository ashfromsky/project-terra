import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(scriptDir, '..')
const backendCoreDir = path.resolve(frontendDir, '..', 'backend', 'core')
const generatedDir = path.join(frontendDir, 'src', 'shared', 'api', 'generated')
const openapiPath = path.join(generatedDir, 'openapi.json')
const schemaTypesPath = path.join(generatedDir, 'schema.d.ts')

const previousOpenApi = existsSync(openapiPath) ? readFileSync(openapiPath, 'utf8') : null

execFileSync(
  'uv',
  ['run', 'python', '-m', 'terra.openapi_export', '--output', openapiPath],
  { cwd: backendCoreDir, stdio: 'inherit' },
)

const nextOpenApi = readFileSync(openapiPath, 'utf8')
const schemaMissing = !existsSync(schemaTypesPath)
const schemaStale = previousOpenApi !== nextOpenApi

if (schemaMissing || schemaStale) {
  const renderedTypes = execFileSync(
    'pnpm',
    ['exec', 'openapi-typescript', openapiPath],
    { cwd: frontendDir, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 },
  )
  writeFileSync(schemaTypesPath, renderedTypes, 'utf8')
}
