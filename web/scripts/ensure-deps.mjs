// Runs before `npm run dev` / `npm run build`. If any dependency listed in
// package.json is missing from node_modules (for example after pulling a change
// that added a package), run `npm ci` once so the app starts instead of failing
// with "Failed to resolve import". Does nothing when everything is installed.
import { existsSync, readFileSync } from 'node:fs'
import { execSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const names = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies })
const missing = names.filter((n) => !existsSync(join(root, 'node_modules', n, 'package.json')))

if (missing.length) {
  console.log(`[pramaan] Missing packages: ${missing.join(', ')}`)
  console.log('[pramaan] Running npm ci to install them...')
  try {
    execSync('npm ci', { cwd: root, stdio: 'inherit' })
  } catch {
    console.error('[pramaan] npm ci failed. Close VS Code and any running Vite window, delete web/node_modules, then retry.')
    process.exit(1)
  }
}
