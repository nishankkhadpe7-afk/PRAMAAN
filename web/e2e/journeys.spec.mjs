import {test,expect} from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
// UI/UX audit Phase 5: core journeys completed with the keyboard only, plus a 360 px overflow gate.
// Runs against the disposable `.demo/<instance>` reset by playwright.config.mjs before the API starts.
const demo=path.resolve('../.demo',process.env.PRAMAAN_E2E_INSTANCE||'browser')
let credentials,state
test.beforeAll(async()=>{credentials=JSON.parse(await fs.readFile(path.join(demo,'session-credentials.json'),'utf8'));state=JSON.parse(await fs.readFile(path.join(demo,'demo-state.json'),'utf8'))})

async function keyboardSignIn(page,role){
  await page.goto('/login');await page.getByLabel('Access credential').focus()
  await page.keyboard.type(credentials[role]);await page.keyboard.press('Enter')
  await expect(page).not.toHaveURL(/\/login/,{timeout:15000})
}
async function go(page,url){await page.evaluate(u=>{history.pushState(null,'',u);dispatchEvent(new PopStateEvent('popstate'))},url)}
async function tabTo(page,locator,max=400){
  // Tab forwards, or Shift+Tab when the control sits before the current focus in document order.
  const back=await locator.evaluate(el=>{const a=document.activeElement;return !!a&&a!==document.body&&!!(a.compareDocumentPosition(el)&Node.DOCUMENT_POSITION_PRECEDING)}).catch(()=>false)
  for(let i=0;i<max;i++){if(await locator.evaluate(el=>el===document.activeElement).catch(()=>false))return;await page.keyboard.press(back?'Shift+Tab':'Tab')}throw new Error('Could not reach control with Tab')}

test('keyboard-only findings triage and bulk review decision',async({page})=>{
  await keyboardSignIn(page,'human');await go(page,`/auditor/runs/${state.run_id}/findings`)
  const rows=page.locator('tbody .row-link');await expect(rows.first()).toBeVisible()
  await tabTo(page,rows.first())
  await page.keyboard.press('x');await page.keyboard.press('j');await page.keyboard.press('x')
  await expect(rows.nth(1)).toBeFocused()
  await expect(page.getByRole('toolbar',{name:'Bulk actions'})).toContainText('2 selected')
  await tabTo(page,page.getByRole('button',{name:'Review selected…'}),400);await page.keyboard.press('Enter')
  const drawer=page.getByRole('dialog',{name:'Record human decisions'});await expect(drawer).toBeVisible()
  await tabTo(page,drawer.getByLabel('Reason (recorded on each finding)'));await page.keyboard.type('Keyboard journey: reviewed synthetic source and limits.')
  await tabTo(page,drawer.getByRole('button',{name:'Continue'}));await page.keyboard.press('Enter')
  await expect(drawer.getByRole('alert')).toContainText('human decision')
  await tabTo(page,drawer.getByRole('button',{name:'Record 2 decisions'}));await page.keyboard.press('Enter')
  await expect(drawer.getByRole('status')).toContainText('2 saved, 0 failed')
  await page.keyboard.press('Escape');await expect(drawer).toHaveCount(0)
  // Decisions now show as human decisions with the signer, never as automated output.
  await expect(page.getByText('Human decision').first()).toBeVisible()
  await expect(page.getByText('by demo-human-reviewer').first()).toBeVisible()
})

test('keyboard-only report export from a frozen package',async({page})=>{
  await keyboardSignIn(page,'human');await go(page,`/auditor/runs/${state.run_id}/workpapers?upload=${encodeURIComponent(state.upload_id)}`)
  await expect(page.getByRole('heading',{name:'Each package contains'})).toBeVisible()
  const create=page.getByRole('button',{name:'Create export package'});await tabTo(page,create);await page.keyboard.press('Enter')
  const excel=page.getByRole('button',{name:'Excel workpapers'});await expect(excel).toBeVisible({timeout:60000})
  await tabTo(page,excel);const pending=page.waitForEvent('download');await page.keyboard.press('Enter')
  const download=await pending;expect(download.suggestedFilename()).toMatch(/\.xlsx$/)
})

test('AI, proposal and human statements are labelled differently',async({page})=>{
  await keyboardSignIn(page,'auditor');await go(page,`/auditor/assistant?run=${state.run_id}`)
  await page.getByRole('button',{name:'What did the engine find?'}).click()
  await expect(page.getByText('AI-generated guidance').first()).toBeVisible()
  await expect(page.getByText('computed from the run, no AI').first()).toBeVisible()
})

test('no horizontal overflow at 360 px on core screens',async({browser})=>{
  const screens=[['client','/client'],['client','/client/business'],['client','/client/evidence-requests'],['client','/client/registers'],
    ['human','/auditor'],['human','/auditor/runs/new'],['human',`/auditor/runs/${state.run_id}`],['human',`/auditor/runs/${state.run_id}/findings`],
    ['human',`/auditor/runs/${state.run_id}/samples`],['human',`/auditor/runs/${state.run_id}/workpapers`],['human',`/auditor/runs/${state.run_id}/integrity`],['human','/auditor/assistant']]
  const failures=[]
  for(const [role,url] of screens){
    const context=await browser.newContext({viewport:{width:360,height:800}});const page=await context.newPage()
    await page.addInitScript(token=>sessionStorage.setItem('pramaan.session',token),credentials[role])
    await page.goto(url);await page.waitForLoadState('networkidle');await page.waitForTimeout(400)
    const {scroll,client}=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}))
    if(scroll>client)failures.push(`${url}: ${scroll}>${client}`)
    await context.close()
  }
  expect(failures).toEqual([])
})
