import {useEffect,useState} from 'react'
import {AlertTriangle,ArrowRight,CheckCircle,FileSearch,Send,XCircle} from 'lucide-react'
import {ApiError,id} from './api'
import {Drawer,Field,Panel,Row,toTitleLabel,useData} from './components'
import {useSession} from './session'
import {ProvenanceTag,formatWhen} from './ui'

const STATUS:Record<string,{label:string;tone:string;note:string}>={
  explained:{label:'Traced to a matching payment',tone:'ok',note:'The sale is traced to source records. The auditor still records the decision.'},
  unexplained:{label:'Unexplained',tone:'warn',note:'A difference remains after tracing. This is a review lead, not a conclusion.'},
  needs_confirmation:{label:'Needs your confirmation',tone:'warn',note:'The agent proposed an action. Nothing is sent until a human confirms it.'},
  conflict:{label:'Conflicting sources: escalated',tone:'bad',note:'Sources disagree. The agent stopped and did not choose between them.'},
  budget_exhausted:{label:'Stopped before finishing',tone:'warn',note:'The agent used its step budget before tracing the key sources.'},
}

function SourceRef({r}:{r:Row}){
  const text=r.type==='bank_row'?`Bank ${r.statement_id} row ${r.row_no}`:r.type==='register_row'?`Register ${r.upload_id} row ${r.row_no}`:r.type==='bank_statement'?`Bank statement ${r.statement_id} (searched)`:r.type==='agent_action'?`Proposal ${r.id}`:`${toTitleLabel(r.type)} ${r.id??''}`
  return <li><span>{text}</span>{(r.row_hash||r.sha256||r.snapshot_hash||r.payload_hash)&&<code className="muted-id">{String(r.row_hash||r.sha256||r.snapshot_hash||r.payload_hash).slice(0,12)}…</code>}</li>
}

function Records({records}:{records:Row[]}){
  return <div className="conflict-records">{records.map((rec,i)=><dl key={i} className="conflict-record"><dt>{toTitleLabel(rec.source||'record')}</dt>{Object.entries(rec).filter(([k])=>k!=='source').map(([k,v])=><div key={k}><span>{toTitleLabel(k)}</span><b>{String(v??'—')}</b></div>)}</dl>)}</div>
}

export function ConfirmDrawer({action,onClose,onDone}:{action:Row;onClose:()=>void;onDone:()=>void}){
  const {api}=useSession();const [reason,setReason]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const decide=async(kind:'confirm'|'reject')=>{setBusy(true);setError('');try{await api!.json(`/p6/actions/${id(action.action_id)}/${kind}`,'POST',{payload_hash:action.payload_hash,reason});onDone()}catch(e){setError(e instanceof Error?e.message:'The decision could not be recorded.')}finally{setBusy(false)}}
  const p=action.payload
  return <Drawer title="Confirm the proposed evidence request" onClose={onClose}>
    <p>This request is a proposal. It is sent only if you confirm.</p>
    <dl className="facts"><div><dt>Sent to</dt><dd>The client's evidence inbox (company workspace)</dd></div><div><dt>Invoice</dt><dd>{p.invoice_id}</dd></div><div><dt>Documents requested</dt><dd>{p.documents.map(toTitleLabel).join(', ')}</dd></div><div><dt>Reason shown to the client</dt><dd>{p.reason}</dd></div><div><dt>Proposed by</dt><dd>{action.proposed_by} · {formatWhen(action.proposed_at)}</dd></div><div><dt>Payload fingerprint</dt><dd><code className="muted-id">{action.payload_hash}</code></dd></div></dl>
    <Field label="Your note (required to reject)"><textarea maxLength={500} value={reason} onChange={e=>setReason(e.target.value)}/></Field>
    {error&&<div className="notice error" role="alert">{error}</div>}
    <div className="bulk-actions"><button type="button" className="primary" disabled={busy} onClick={()=>void decide('confirm')}><Send size={16}/>Confirm and send</button><button type="button" disabled={busy||!reason.trim()} onClick={()=>void decide('reject')}><XCircle size={16}/>Reject</button></div>
  </Drawer>
}

export function InvestigationPanel({runId,findingId}:{runId:string;findingId:string}){
  const {api,identity}=useSession();const [refresh,setRefresh]=useState(0)
  const list=useData<Row>(`/p6/runs/${id(runId)}/investigations?finding_id=${id(findingId)}`,refresh)
  const actions=useData<Row>(`/p6/runs/${id(runId)}/actions`,refresh)
  const [report,setReport]=useState<Row|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<{message:string;noKey:boolean}|null>(null),[confirming,setConfirming]=useState<Row|null>(null)
  const latest=list.data?.investigations?.[0]
  useEffect(()=>{if(!latest){setReport(null);return}let live=true;void api!.json(`/p6/investigations/${id(latest.investigation_id)}`).then(r=>{if(live)setReport(r)}).catch(()=>{});return()=>{live=false}},[latest?.investigation_id])
  const start=async(planner:'llm'|'baseline')=>{setBusy(true);setError(null);try{const r=await api!.json(`/p6/runs/${id(runId)}/investigations`,'POST',{finding_id:findingId,planner});setReport(r);setRefresh(n=>n+1)}catch(e){setError({message:e instanceof Error?e.message:'Investigation failed.',noKey:e instanceof ApiError&&e.status===409})}finally{setBusy(false)}}
  const status=report?STATUS[report.status]:null
  const mine=(actions.data?.actions||[]).filter((a:Row)=>report&&(report.pending_actions||[]).includes(a.action_id))
  return <Panel title="Agent investigation" subtitle="The agent plans each check; tools compute every amount; conflicts stop the run; you make the decision." action={<div className="bulk-actions"><button type="button" className="primary" disabled={busy} onClick={()=>void start('llm')}><FileSearch size={16}/>{busy?'Investigating…':report?'Investigate again':'Investigate with AI'}</button><button type="button" disabled={busy} onClick={()=>void start('baseline')}>Run without AI</button></div>}>
    {error&&<div className={'notice'+(error.noKey?'':' error')} role="alert"><p>{error.message}</p>{error.noKey&&<button type="button" onClick={()=>void start('baseline')}>Run the deterministic baseline instead <ArrowRight size={14}/></button>}</div>}
    {!report&&!error&&<p className="field-help">Not investigated yet. Start an investigation to trace this exception through the invoice, sales register, bank statement and evidence.</p>}
    {report&&status&&<>
      <div className={'investigation-status tone-'+status.tone} role="status">{status.tone==='ok'?<CheckCircle size={18}/>:<AlertTriangle size={18}/>}<div><strong>{status.label}{report.unexplained_amount?` · INR ${report.unexplained_amount} unexplained`:''}</strong><p>{status.note}</p></div></div>
      <div className="investigation-summary"><ProvenanceTag kind={report.summary_source==='model'?'ai':'automated'} detail={report.summary_source==='model'?`summary by ${report.model}; amounts checked against tool results`:report.planner==='llm'?'AI summary rejected by the amount check; system summary shown':'deterministic baseline planner, no AI'} at={report.created_at}/><p>{report.summary}</p></div>
      <ol className="investigation-steps">{report.steps.map((s:Row,i:number)=><li key={i} className={'inv-step inv-'+s.kind}>
        {s.kind==='plan'&&<ProvenanceTag kind="ai" detail="plan"/>}
        {s.kind==='tool'&&<ProvenanceTag kind="automated" detail={toTitleLabel(s.tool)}/>}
        {s.kind==='check'&&<ProvenanceTag kind="automated" detail="check before finishing"/>}
        {s.kind==="escalation"&&<ProvenanceTag kind="automated" detail="system stopped the agent; your decision needed"/>}
        <p>{s.summary}</p>
        {s.kind==='escalation'&&(s.conflicts||[]).map((c:Row,j:number)=><div key={j} className="conflict-card"><strong>{c.detail}</strong><Records records={c.records}/></div>)}
        {s.source_refs?.length>0&&<details><summary>{s.source_refs.length} source link{s.source_refs.length===1?'':'s'}</summary><ul className="source-refs">{s.source_refs.map((r:Row,k:number)=><SourceRef key={k} r={r}/>)}</ul></details>}
      </li>)}</ol>
      {mine.length>0&&<div className="investigation-actions"><h3>Proposed actions</h3>{mine.map((a:Row)=><div key={a.action_id} className="proposal-card"><div className="proposal-head"><ProvenanceTag kind="proposal" detail={a.status==='pending'?'awaiting human confirmation':a.status} actor={a.decided_by||a.proposed_by} at={a.decided_at||a.proposed_at}/></div><p>Request {a.payload.documents.map(toTitleLabel).join(', ')} for {a.payload.invoice_id}. {a.payload.reason}</p>{a.status==='pending'&&(identity!.human?<button type="button" className="primary" onClick={()=>setConfirming(a)}>Review and confirm</button>:<p className="field-help">Only a human reviewer credential can confirm or reject this.</p>)}{a.result?.request_id&&<p className="field-help">Sent as {a.result.request_id}.</p>}</div>)}</div>}
      {(report.open_questions?.length>0||report.recommended_next_action)&&<dl className="facts"><div><dt>Recommended next step</dt><dd>{report.recommended_next_action}</dd></div>{report.no_request_reason&&<div><dt>Why no evidence request</dt><dd>{report.no_request_reason}</dd></div>}{report.open_questions?.length>0&&<div><dt>Open questions</dt><dd>{report.open_questions.join(' · ')}</dd></div>}<div><dt>Planner</dt><dd>{report.planner==='llm'?`AI (${report.model}), prompt ${report.prompt_version}`:report.ai_fallback?'No-AI planner (every AI provider was unavailable, so it ran instead)':'Deterministic baseline (no AI)'} · {report.tool_calls} tool call{report.tool_calls===1?'':'s'}</dd></div><div><dt>Report fingerprint</dt><dd><code className="muted-id">{report.report_hash}</code></dd></div></dl>}
    </>}
    {confirming&&<ConfirmDrawer action={confirming} onClose={()=>setConfirming(null)} onDone={()=>{setConfirming(null);setRefresh(n=>n+1)}}/>}
  </Panel>
}
