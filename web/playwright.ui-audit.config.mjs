import {defineConfig} from '@playwright/test'
import path from 'node:path'
import {existsSync} from 'node:fs'
// UI audit capture: runs against the large TEST FIXTURE instance `.demo/uiaudit`
// (seed it first with e2e/ui-audit/seed_large.py). Separate ports so it never collides with dev servers.
const project=path.resolve('..'),launcher=path.join(project,'launcher')
const python=[process.env.PRAMAAN_E2E_PYTHON,path.join(project,'.venv-p4','Scripts','python.exe'),path.join(project,'.venv-p4','bin','python')].find(p=>p&&existsSync(p))||(process.platform==='win32'?'python':'python3')
const browser=process.env.PRAMAAN_E2E_CHANNEL===''?{}:{channel:process.env.PRAMAAN_E2E_CHANNEL||'chrome'}
export default defineConfig({testDir:'./e2e/ui-audit',testMatch:/.*\.spec\.ts/,timeout:600000,workers:1,reporter:[['list']],
 use:{baseURL:'http://127.0.0.1:5180',...browser,headless:true,video:'off',trace:'off'},
 webServer:[{command:`"${python}" -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port 8020 --no-access-log`,env:{PYTHONPATH:launcher,PRAMAAN_DATA:path.join(project,'.demo','uiaudit')},url:'http://127.0.0.1:8020/health',reuseExistingServer:false,timeout:60000},
  {command:'npm run dev -- --port 5180',env:{PRAMAAN_E2E_API_PORT:'8020'},url:'http://127.0.0.1:5180',reuseExistingServer:false,timeout:60000}]})
