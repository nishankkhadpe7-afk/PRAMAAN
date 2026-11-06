import {test,expect,type Page} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'
import path from 'node:path'
// UI audit capture (TEST FIXTURE data from seed_large.py). PHASE=before|after selects the output folder.
const phase=process.env.UI_AUDIT_PHASE||'before'
const repo=path.resolve('..'),demo=path.join(repo,'.demo','uiaudit')
const out=path.join(repo,'docs','ui-audit','screenshots',phase)
const widths=[360,390,768,1024,1440,1920]
type Screen={name:string;role:'none'|'client'|'auditor'|'human';path:string;ready?:string}
let creds:Record<string,string>,state:Record<string,string>,findingId=''
const report:Record<string,unknown>={phase,captured_at:new Date().toISOString(),screens:{}}

async function signIn(page:Page,role:Screen['role']){if(role==='none')return;await page.addInitScript(token=>{sessionStorage.setItem('pramaan.session',token)},creds[role])}
async function settle(page:Page){await page.waitForLoadState('networkidle').catch(()=>{});await page.waitForTimeout(600)}

test.beforeAll(async({request})=>{
  creds=JSON.parse(fs.readFileSync(path.join(demo,'session-credentials.json'),'utf8'));state=JSON.parse(fs.readFileSync(path.join(demo,'demo-state.json'),'utf8'))
  const context=await(await request.get(`/api/ui/runs/${state.fixture_run_id}/context`,{headers:{Authorization:'Bearer '+creds.auditor}})).json()
  findingId=context.findings.find((f:{state:string})=>f.state==='INCONSISTENT')?.finding_id||context.findings[0].finding_id
  fs.mkdirSync(out,{recursive:true})
})

test('capture every key screen at every width',async({browser})=>{
  const run=state.fixture_run_id
  const screens:Screen[]=[
    {name:'landing',role:'none',path:'/'},{name:'login',role:'none',path:'/login'},
    {name:'client-dashboard',role:'client',path:'/client'},{name:'client-business',role:'client',path:'/client/business'},
    {name:'client-registers',role:'client',path:'/client/registers'},{name:'client-inbox',role:'client',path:'/client/evidence-requests'},
    {name:'auditor-overview',role:'auditor',path:'/auditor'},{name:'auditor-new-run',role:'auditor',path:'/auditor/runs/new'},
    {name:'run-summary',role:'human',path:`/auditor/runs/${run}`},{name:'run-findings',role:'human',path:`/auditor/runs/${run}/findings`},
    {name:'run-samples',role:'human',path:`/auditor/runs/${run}/samples`},{name:'run-workpapers',role:'human',path:`/auditor/runs/${run}/workpapers`},
    {name:'run-integrity',role:'human',path:`/auditor/runs/${run}/integrity`},{name:'finding-detail',role:'human',path:`/auditor/findings/${findingId}?run=${run}`},
    {name:'assistant',role:'auditor',path:`/auditor/assistant?run=${run}`}]
  for(const screen of screens){
    const entry:Record<string,unknown>={path:screen.path.replace(run,'<run>').replace(findingId,'<finding>'),widths:{}}
    for(const width of widths){
      const context=await browser.newContext({viewport:{width,height:width<768?800:900}});const page=await context.newPage()
      const consoleErrors:string[]=[],failed:string[]=[]
      page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text().slice(0,200))})
      page.on('pageerror',e=>consoleErrors.push('pageerror: '+e.message.slice(0,200)))
      page.on('response',r=>{if(r.status()>=400)failed.push(`${r.status()} ${new URL(r.url()).pathname}`)})
      page.on('requestfailed',r=>failed.push('failed '+new URL(r.url()).pathname))
      await signIn(page,screen.role);await page.goto(screen.path);await settle(page)
      await page.screenshot({path:path.join(out,`${screen.name}-${width}-populated.png`),fullPage:false})
      const overflow=await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth}))
      const small=await page.evaluate(()=>Array.from(document.querySelectorAll('a,button,input,select,summary,[role=button]')).filter(el=>{const r=(el as HTMLElement).getBoundingClientRect();return r.width>0&&r.height>0&&(r.width<24||r.height<24)}).length)
      const result:Record<string,unknown>={overflow:overflow.scrollWidth>overflow.clientWidth?overflow:null,small_targets:small,console_errors:consoleErrors,failed_requests:failed}
      if(width===1440||width===360){const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze()
        result.axe=axe.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length,help:v.help}))}
      ;(entry.widths as Record<string,unknown>)[width]=result
      await context.close()
    }
    ;(report.screens as Record<string,unknown>)[screen.name]=entry
  }
  fs.writeFileSync(path.join(repo,'docs','ui-audit',phase==='before'?'01-baseline.json':'05-after.json'),JSON.stringify(report,null,1))
  expect(Object.keys(report.screens as object).length).toBe(screens.length)
})

test('capture loading, error, empty and drawer states',async({browser})=>{
  const run=state.fixture_run_id,states:Record<string,string>={}
  const fresh=async()=>{const ctx=await browser.newContext({viewport:{width:1440,height:900}});const page=await ctx.newPage();await signIn(page,'human');return {ctx,page}}
  const attempt=async(name:string,fn:(page:Page)=>Promise<void>)=>{const {ctx,page}=await fresh();try{await fn(page);states[name]='captured'}catch(e){states[name]='not captured: '+String(e).split('\n')[0].slice(0,160)}finally{await ctx.close()}}
  await attempt('loading',async page=>{await page.route('**/api/ui/runs/*/context',async r=>{await new Promise(res=>setTimeout(res,2500));await r.continue().catch(()=>{})});await page.goto(`/auditor/runs/${run}/findings`);await page.waitForTimeout(700);await page.screenshot({path:path.join(out,'run-findings-1440-loading.png')})})
  await attempt('error',async page=>{await page.route('**/api/ui/runs/*/context',r=>r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({code:'conflict',detail:'snapshot or ruleset integrity failure'})}));await page.goto(`/auditor/runs/${run}/findings`);await settle(page);await page.screenshot({path:path.join(out,'run-findings-1440-error.png')})})
  await attempt('empty',async page=>{await page.goto(`/auditor/runs/${run}/findings`);await settle(page);await page.locator('input[type=search],input[placeholder*="earch"]').first().fill('zz-no-such-finding-zz',{timeout:5000});await page.waitForTimeout(400);await page.screenshot({path:path.join(out,'run-findings-1440-empty.png')})})
  await attempt('drawer',async page=>{await page.goto(`/auditor/runs/${run}/samples`);await settle(page);await page.locator('tbody tr').first().click({timeout:5000});await page.waitForTimeout(600);await page.screenshot({path:path.join(out,'run-samples-1440-drawer.png')})})
  const file=path.join(repo,'docs','ui-audit',phase==='before'?'01-baseline.json':'05-after.json')
  const saved=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{phase,screens:{}};saved.states=states;fs.writeFileSync(file,JSON.stringify(saved,null,1))
})
