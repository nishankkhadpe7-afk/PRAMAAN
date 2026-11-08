import {useEffect,useId,useRef,useState,type ReactNode} from 'react'
import {Link} from 'react-router-dom'
import {ArrowRight,CircleHelp,Sparkles,X} from 'lucide-react'

// Plain-language meanings for the audit vocabulary used across the app. One definition per word,
// reused by every hint, so the same term never gets two different explanations.
export const GLOSSARY={
  observation:{term:'Observation',meaning:'An automated signal that something may need a look. It is not a conclusion; a person decides what it means.'},
  finding:{term:'Finding',meaning:'An observation linked to a specific record and the rule that raised it, waiting for a human decision.'},
  signal:{term:'Signal types',meaning:'Inconsistent: two records disagree. Evidence gap: a document is missing or cannot be checked. Needs review: a pattern worth a human look. Context: background, not a problem by itself.'},
  inconsistent:{term:'Inconsistent',meaning:'Two records disagree, for example the register amount differs from the invoice.'},
  evidence_gap:{term:'Evidence gap',meaning:'An expected supporting document is missing, or it cannot be checked yet.'},
  human_review:{term:'Human review',meaning:'Only a person with the human-review credential can record the final decision on a finding. The AI and the auditor credential can only propose.'},
  assertion:{term:'Assertion',meaning:'The claim a check tests about the accounts: the sale really happened (occurrence), nothing is left out (completeness), it is in the right year (cut-off), it is recorded under the right head (classification) and for the right amount (accuracy).'},
  tod:{term:'Test of details (TOD)',meaning:'Checking individual transactions against their documents, such as the invoice, e-way bill and proof of delivery.'},
  cutoff:{term:'Cut-off',meaning:'Whether a sale is recorded in the correct financial year, which matters most for sales just before or after year-end.'},
  population:{term:'Population',meaning:'All the invoices the test could pick from.'},
  certainty:{term:'Certainty item',meaning:'Always tested because it is high-risk, for example a large amount, a related party or a sale near year-end.'},
  random:{term:'Random (seeded) item',meaning:'Picked at random using a recorded seed, so anyone can repeat exactly the same selection later.'},
  snapshot:{term:'Snapshot',meaning:'A frozen copy of the data taken when the audit run started. Later edits to the books do not change it.'},
  ruleset:{term:'Ruleset',meaning:'The version of the checking rules used for this run.'},
  sampler:{term:'Sampler',meaning:'The version of the method that decides which items get tested.'},
  seed:{term:'Seed',meaning:'The value that fixes the random selection, so the same items can be picked again to prove the sample was not cherry-picked.'},
  source_manifest:{term:'Source manifest',meaning:'A fingerprint of every source file the run used. If any file changed, this value would change.'},
  population_projection:{term:'Population projection',meaning:'Estimating the total error across all invoices from the sample. Not done here unless a qualified reviewer approves the method.'},
  misstatement:{term:'Potential misstatement',meaning:'The total of unconfirmed differences between sources. It becomes a confirmed error only after human review.'},
  reconciliation:{term:'Register reconciliation',meaning:'Matching the uploaded sales register line by line against the business records, before any audit run.'},
  register:{term:'Sales register',meaning:'The client\'s list of sales (CSV), kept exactly as uploaded so it can always be compared again.'},
  related_party:{term:'Related party',meaning:'A customer connected to the company, for example through common owners, so its prices and terms need extra scrutiny.'},
  workpaper:{term:'Workpaper',meaning:'The auditor\'s record of what was tested, how, and what was found.'},
  frozen_package:{term:'Frozen package',meaning:'A sealed export of the workpapers. Downloads are byte-identical, and any change produces a different fingerprint.'},
  fingerprint:{term:'Fingerprint (SHA-256)',meaning:'A code computed from a file\'s exact contents. Changing even one character gives a completely different code.'},
  hash_chain:{term:'Hash chain',meaning:'Each audit-trail entry includes the fingerprint of the entry before it, so deleting or editing a past entry breaks the chain and is detected.'},
  proposal:{term:'Proposal',meaning:'A suggested action, from the auditor or the AI agent, that does nothing until a human reviewer confirms it.'},
  lifecycle:{term:'Sale lifecycle',meaning:'One sale\'s full chain: order, dispatch, invoice and the journal entry in the books.'},
  journal:{term:'Journal entry',meaning:'The accounting entry that records the sale in the books. Posted entries are never edited; corrections add a reversing entry.'},
  mcp:{term:'MCP',meaning:'Model Context Protocol: the controlled way AI assistants call PRAMAAN\'s tools, with the same permission checks as people.'},
} as const
export type GlossaryKey=keyof typeof GLOSSARY

// Look up a hint by the visible label (e.g. a fact row "seed" or a metric "Population").
const BY_LABEL:Record<string,GlossaryKey>={population:'population',certainty:'certainty',random:'random',snapshot:'snapshot',ruleset:'ruleset',sampler:'sampler',seed:'seed',sampling_seed:'seed',
  source_manifest:'source_manifest',population_projection:'population_projection',snapshot_hash:'snapshot',ruleset_version:'ruleset',sampler_version:'sampler',
  potential_misstatement:'misstatement',automated_observations:'observation',export_packages:'frozen_package',audit_runs:'snapshot',register_reconciliation:'reconciliation',
  related_party_disclosures:'related_party',saved_packages:'frozen_package',original_registers:'register'}
export const termForLabel=(label:string):GlossaryKey|undefined=>BY_LABEL[label.trim().toLowerCase().replace(/[\s-]+/g,'_')]

// A label with a small "?" that explains the word. The button has no text of its own, so the
// label's accessible text and any test selectors stay exactly as before.
export function Term({k,children,bare}:{k:GlossaryKey;children?:ReactNode;bare?:boolean}){
  const entry=GLOSSARY[k],id=useId(),ref=useRef<HTMLSpanElement>(null)
  const [pinned,setPinned]=useState(false),[hover,setHover]=useState(false)
  const open=pinned||hover
  useEffect(()=>{if(!pinned)return
    const outside=(e:MouseEvent)=>{if(!ref.current?.contains(e.target as Node))setPinned(false)}
    document.addEventListener('mousedown',outside);return()=>document.removeEventListener('mousedown',outside)},[pinned])
  return <span className="term" ref={ref} onMouseLeave={()=>setHover(false)}>{bare?null:children??entry.term}<button type="button" className="term-help" aria-label={`What does “${entry.term}” mean?`} aria-expanded={open} aria-controls={open?id:undefined}
    onMouseEnter={()=>setHover(true)} onClick={e=>{e.preventDefault();e.stopPropagation();setPinned(p=>!p)}}
    onKeyDown={e=>{if(e.key==='Escape'&&open){e.stopPropagation();e.nativeEvent.stopImmediatePropagation();setPinned(false);setHover(false)}}}><CircleHelp size={13} aria-hidden="true"/></button>
    {open&&<span id={id} role="note" className="term-tip"><strong>{entry.term}</strong>{entry.meaning}</span>}</span>
}

// Activity-trail event codes in plain words; unknown codes fall back to a readable sentence.
const EVENTS:Record<string,string>={sale_lifecycle_created:'Sale recorded (order, dispatch, invoice, journal)',register_imported:'Sales register uploaded',customer_created:'Customer added',
  journal_reversed:'Journal entry reversed',related_parties_imported:'Related-party list uploaded',evidence_uploaded:'Document uploaded',evidence_request_fulfilled:'Document request answered',
  bank_statement_imported:'Bank statement uploaded',credit_note_created:'Credit note recorded'}
export const sentence=(code:string)=>{const text=String(code??'').replace(/[_-]+/g,' ').trim().toLowerCase();return text?text[0].toUpperCase()+text.slice(1):''}
export const eventLabel=(code:string)=>EVENTS[code]||sentence(code)

// First-visit guide: a short, dismissable list of next steps per role. It is a normal card, not a
// modal, so it never blocks the page; the Help button can always bring it back.
type Role='client'|'auditor'
const STEPS:Record<Role,{title:string;text:string;to:string}[]>={
  client:[
    {title:'Record your sales',text:'Each sale links its order, dispatch, invoice and journal entry.',to:'/client/business'},
    {title:'Upload your original sales register',text:'The CSV is fingerprinted and kept unchanged, so the auditor compares against exactly what you sent.',to:'/client/registers'},
    {title:'Answer document requests',text:'The evidence inbox lists what the auditor still needs. One upload covers every audit.',to:'/client/evidence-requests'},
  ],
  auditor:[
    {title:'Reconcile the client\'s register',text:'Match the uploaded register against the books, in the “Register reconciliation” panel below.',to:'/auditor'},
    {title:'Start an audit run',text:'A run freezes a snapshot of the data and applies the checks and sample selection.',to:'/auditor/runs/new'},
    {title:'Review findings, inconsistent ones first',text:'Open the run, read each finding\'s evidence, and propose a decision. Only a human reviewer records the final one.',to:'/auditor'},
    {title:'Freeze and export workpapers',text:'The Workpapers tab creates a sealed package with a PDF memo and an Excel file.',to:'/auditor'},
  ],
}
const guideKey=(role:Role)=>'pramaan.guide.dismissed.'+role
const readDismissed=(role:Role)=>{try{return localStorage.getItem(guideKey(role))==='1'}catch{return false}}
const writeDismissed=(role:Role,value:boolean)=>{try{if(value)localStorage.setItem(guideKey(role),'1');else localStorage.removeItem(guideKey(role))}catch{/* storage unavailable: guide simply reappears */}}
const GUIDE_EVENT='pramaan:guide'

export function GettingStarted({role}:{role:Role}){
  const [hidden,setHidden]=useState(()=>readDismissed(role))
  useEffect(()=>{const show=()=>setHidden(false);window.addEventListener(GUIDE_EVENT,show);return()=>window.removeEventListener(GUIDE_EVENT,show)},[])
  if(hidden)return null
  return <section className="guide" aria-labelledby="guide-title">
    <div className="guide-head"><Sparkles size={18} aria-hidden="true"/><div><h2 id="guide-title">Getting started</h2><p>{role==='client'?'Three steps to get your records ready for the audit.':'The usual route from the client\'s records to a reviewed, exported audit.'}</p></div>
      <button type="button" className="icon-button" aria-label="Hide the getting-started guide" onClick={()=>{writeDismissed(role,true);setHidden(true)}}><X size={16}/></button></div>
    <ol className="guide-steps">{STEPS[role].map((s,i)=><li key={s.title}><span className="guide-num" aria-hidden="true">{i+1}</span><div><Link to={s.to}>{s.title} <ArrowRight size={14} aria-hidden="true"/></Link><p>{s.text}</p></div></li>)}</ol>
    <p className="guide-foot">Words marked with <CircleHelp size={13} aria-hidden="true"/><span className="sr-only">a question-mark button</span> have a plain-language explanation. You can reopen this guide from <strong>Help</strong> at the top of the page.</p>
  </section>
}

export function HelpContent({role,onShowGuide}:{role:Role;onShowGuide:()=>void}){
  return <div className="help">
    <h3>What to do next</h3>
    <ol className="guide-steps">{STEPS[role].map((s,i)=><li key={s.title}><span className="guide-num" aria-hidden="true">{i+1}</span><div><strong>{s.title}</strong><p>{s.text}</p></div></li>)}</ol>
    <button type="button" onClick={()=>{writeDismissed(role,false);window.dispatchEvent(new Event(GUIDE_EVENT));onShowGuide()}}>Show the guide on the overview page</button>
    <h3>Audit words in plain language</h3>
    <dl className="glossary-list">{Object.values(GLOSSARY).map(g=><div key={g.term}><dt>{g.term}</dt><dd>{g.meaning}</dd></div>)}</dl>
  </div>
}
