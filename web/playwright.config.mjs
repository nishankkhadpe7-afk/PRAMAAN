import {defineConfig} from '@playwright/test'
import path from 'node:path'
import {existsSync} from 'node:fs'
// T1/H8/T6: the dedicated `.demo/<instance>` data set is reset (fresh, short-lived credentials)
// immediately before the API starts, so tests never depend on expired tokens. Works on Windows,
// macOS and Linux; the `launcher` shim makes `Pramaan.backend` importable from any checkout name.
const project=path.resolve('..'),launcher=path.join(project,'launcher')
const candidates=[process.env.PRAMAAN_E2E_PYTHON,path.join(project,'.venv-p4','Scripts','python.exe'),path.join(project,'.venv-p4','bin','python'),path.join(project,'.venv','bin','python')]
const python=candidates.find(p=>p&&existsSync(p))||(process.platform==='win32'?'python':'python3')
const instance=process.env.PRAMAAN_E2E_INSTANCE||'browser'
const apiPort=Number(process.env.PRAMAAN_E2E_API_PORT)||8000,webPort=Number(process.env.PRAMAAN_E2E_WEB_PORT)||5173
const browser=process.env.PRAMAAN_E2E_CHANNEL===''?{}:{channel:process.env.PRAMAAN_E2E_CHANNEL||'chrome'}
export default defineConfig({testDir:'./e2e',testIgnore:'**/ui-audit/**',timeout:120000,expect:{timeout:15000},workers:1,fullyParallel:false,retries:0,
 reporter:[['list'],['json',{outputFile:'test-results/results.json'}]],
 use:{baseURL:`http://127.0.0.1:${webPort}`,...browser,headless:true,viewport:{width:1440,height:1000},video:process.env.PRAMAAN_E2E_VIDEO==='off'?'off':process.env.CI?'retain-on-failure':{mode:'on',size:{width:1440,height:1000}},trace:'off',screenshot:'only-on-failure'},
 webServer:[
  {command:`"${python}" -m Pramaan.backend.demo reset --name ${instance} && "${python}" -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port ${apiPort} --no-access-log`,
   env:{PYTHONPATH:launcher,PRAMAAN_DATA:path.join(project,'.demo',instance)},url:`http://127.0.0.1:${apiPort}/health`,reuseExistingServer:false,timeout:120000},
  {command:`npm run dev -- --port ${webPort}`,env:{PRAMAAN_E2E_API_PORT:String(apiPort)},url:`http://127.0.0.1:${webPort}`,reuseExistingServer:false,timeout:60000}]})
