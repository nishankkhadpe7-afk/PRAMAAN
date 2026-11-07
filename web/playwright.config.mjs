import {defineConfig} from '@playwright/test'
import path from 'node:path'
import {existsSync} from 'node:fs'
const project=path.resolve('..'),parent=path.resolve('../..')
const python=process.env.PRAMAAN_E2E_PYTHON||[path.join(project,'.venv-p4','Scripts','python.exe'),path.resolve(project,'../../.venv-p4/Scripts/python.exe')].find(existsSync)
if(!python)throw new Error('Set PRAMAAN_E2E_PYTHON to the project Python executable.')
const apiPort=Number(process.env.PRAMAAN_E2E_API_PORT)||8000,webPort=Number(process.env.PRAMAAN_E2E_WEB_PORT)||5173
export default defineConfig({testDir:'./e2e',timeout:120000,expect:{timeout:15000},workers:1,fullyParallel:false,retries:0,reporter:[['list'],['json',{outputFile:'test-results/results.json'}]],use:{baseURL:`http://127.0.0.1:${webPort}`,channel:'chrome',headless:true,viewport:{width:1440,height:1000},video:{mode:'on',size:{width:1440,height:1000}},trace:'off',screenshot:'only-on-failure'},webServer:[{command:`"${python}" -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port ${apiPort} --no-access-log`,env:{PYTHONPATH:parent,PRAMAAN_DATA:path.join(project,'.demo',process.env.PRAMAAN_E2E_INSTANCE||'browser')},url:`http://127.0.0.1:${apiPort}/health`,reuseExistingServer:false,timeout:30000},{command:`npm run dev -- --port ${webPort}`,env:{PRAMAAN_E2E_API_PORT:String(apiPort)},url:`http://127.0.0.1:${webPort}`,reuseExistingServer:false,timeout:30000}]})
