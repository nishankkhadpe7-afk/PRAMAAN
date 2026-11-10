import {Calculator,Route,CheckCircle2,XCircle,AlertTriangle,MinusCircle,Circle,FileText} from 'lucide-react'
import {Panel,useData} from './components'
import './proof.css'

type Link={stage:string;status:'match'|'differs'|'missing'|'not_applicable'|'recorded'|'info';title:string;detail:string;source:null|string|{file:string;sha256:string|null}}
type Chain={invoice_id:string;bill_no:string;customer:string;links:Link[];summary:string}
type Proof={how:{rule:string;calculation:string[];sources:{file:string;sha256:string|null}[];still_needed:string[];computed_by:string};chains:Chain[]}

const LABEL:Record<Link['status'],string>={match:'Agrees',differs:'Differs',missing:'Missing',not_applicable:'Not applicable',recorded:'Books',info:'Note'}
const ICON={match:CheckCircle2,differs:AlertTriangle,missing:XCircle,not_applicable:MinusCircle,recorded:FileText,info:Circle}

function Source({source}:{source:Link['source']}){
  if(!source)return null
  if(typeof source==='string')return <span className="proof-source">{source}</span>
  return <span className="proof-source">{source.file}{source.sha256&&<code title={'SHA-256 '+source.sha256}>{source.sha256.slice(0,12)}…</code>}</span>
}

function ChainView({chain,open}:{chain:Chain;open:boolean}){
  const bad=chain.links.filter(l=>l.status==='differs'||l.status==='missing').length
  return <details className="proof-chain" open={open}>
    <summary><strong>{chain.bill_no}</strong><span>{chain.customer}</span><span className={'proof-tally '+(bad?'bad':'good')}>{chain.summary}</span></summary>
    <ol>{chain.links.map((l,i)=>{const Icon=ICON[l.status];return <li key={i} className={'proof-link s-'+l.status}>
      <span className="proof-dot" aria-hidden><Icon size={16}/></span>
      <div className="proof-body"><div className="proof-head"><span className="proof-stage">{l.stage}</span>{l.status!=='recorded'&&<span className={'proof-status s-'+l.status}>{LABEL[l.status]}</span>}</div>
        <p className="proof-title">{l.title}</p>{l.detail&&<p className="proof-detail">{l.detail}</p>}<Source source={l.source}/></div></li>})}</ol>
  </details>
}

/** "How we know" and the proof chain for one finding. Computed by the rule engine from the frozen run; no AI. */
export function ProofPanels({runId,findingId}:{runId:string;findingId:string}){
  const data=useData<Proof>(runId&&findingId?`/ui/runs/${encodeURIComponent(runId)}/proof?finding_id=${encodeURIComponent(findingId)}`:null)
  if(data.error)return null
  if(!data.data)return <Panel title="How we know" icon={Calculator}><p className="muted">Working out the proof…</p></Panel>
  const {how,chains}=data.data
  return <>
    <Panel title="How we know" icon={Calculator} subtitle={how.computed_by}>
      <div className="proof-how">
        <p className="proof-rule"><b>Rule</b> {how.rule}</p>
        <ol className="proof-calc">{how.calculation.map((c,i)=><li key={i}>{c}</li>)}</ol>
        <div className="proof-grid">
          {how.sources.length>0&&<div><h3>Taken from</h3><ul>{how.sources.map(s=><li key={s.file}><Source source={s}/></li>)}</ul></div>}
          {how.still_needed.length>0&&<div><h3>Still needed to close it</h3><ul>{how.still_needed.map((s,i)=><li key={i}>{s}</li>)}</ul></div>}
        </div>
      </div>
    </Panel>
    {chains.length>0&&<Panel title="Proof chain" icon={Route} subtitle="Every record that holds this sale, compared with the books">
      {chains.map((c,i)=><ChainView key={c.invoice_id} chain={c} open={i===0}/>)}
    </Panel>}
  </>
}
