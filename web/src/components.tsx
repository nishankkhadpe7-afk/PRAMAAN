import {ReactNode,ReactElement,cloneElement,useEffect,useId,useState} from 'react'
import {ArrowUpRight,CheckCircle,Inbox,X,XCircle} from 'lucide-react'
import {useSession} from './session'
export type Row=Record<string,any>

// Step 1: toTitleLabel helper
export function toTitleLabel(key:string):string{return key.split('_').join(' ').replace(/^./,c=>c.toUpperCase())}

export function useData<T=any>(path:string|null,refresh=0){const {api}=useSession();const [state,setState]=useState<{data:T|null;error:string;loading:boolean;path:string|null}>({data:null,error:'',loading:true,path:null});useEffect(()=>{if(!path){setState({data:null,error:'',loading:false,path});return}const controller=new AbortController();setState(previous=>({data:previous.path===path?previous.data:null,error:'',loading:previous.path!==path||previous.data===null,path}));api!.json<T>(path,'GET',undefined,controller.signal).then(data=>{if(!controller.signal.aborted)setState({data,error:'',loading:false,path})}).catch(e=>{if(!controller.signal.aborted)setState({data:null,error:e.message,loading:false,path})});return()=>controller.abort()},[api,path,refresh]);return state.path===path?state:{data:null,error:'',loading:!!path,path}}


// Step 3: skeleton State loading
export function State({loading,error,children}:{loading?:boolean;error?:string;children:ReactNode}){return loading?<div className="skeleton-loader" role="status" aria-label="Loading"><div className="skeleton-row" style={{width:'80%'}}/><div className="skeleton-row" style={{width:'60%'}}/><div className="skeleton-row" style={{width:'70%'}}/></div>:error?<div className="notice" role="alert">{error}</div>:<>{children}</>}

// Step 2: Badge with tone auto-detection
const TONE_MAP:Record<string,string>={
  'OPEN_REVIEW':'warning','EXCEPTION_CONFIRMED':'error','EXPLAINED':'success','DATA_ERROR':'error',
  'Awaiting client upload':'warning','Fulfilled':'success','Recorded':'success',
  'MCP response':'info','Guidance only':'neutral',
  'Valid':'success','Broken':'error','Detected':'warning','None detected':'success',
  'Review, with context':'info',
}
function resolveTone(text:string,tone:string):string{if(tone!=='neutral')return tone;return TONE_MAP[text]??'neutral'}
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}){const resolved=resolveTone(String(children),tone);return <span className={'badge badge-'+resolved}>{children}</span>}

export function Header({eyebrow,title,description,action}:{eyebrow:string;title:string;description:string;action?:ReactNode}){return <header className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</header>}
export function Table({columns,rows,onRow,empty='No records yet.'}:{columns:{label:string;key?:string;render?:(row:Row)=>ReactNode}[];rows:Row[];onRow?:(row:Row)=>void;empty?:string}){return rows.length?<div className="table-scroll"><table><thead><tr>{columns.map(c=><th key={c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={r.invoice_id||r.finding_id||r.request_id||r.run_id||r.upload_id||r.customer_id||r.credit_note_id||r.package_id||r.seq||r.edge_id||i}>{columns.map((c,j)=><td key={c.label}>{j===0&&onRow?<button className="row-link" onClick={()=>onRow(r)}>{c.render?c.render(r):String(r[c.key!]??'Unavailable')} <ArrowUpRight size={13}/></button>:c.render?c.render(r):String(r[c.key!]??'Unavailable')}</td>)}</tr>)}</tbody></table></div>:<div className="empty"><Inbox size={32}/><p>{empty}</p></div>}
export function Panel({title,subtitle,children,action}:{title:string;subtitle?:string;children:ReactNode;action?:ReactNode}){return <section className="panel"><div className="panel-heading"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>{children}</section>}

// Step 2: Metrics with tone support
export function Metrics({items}:{items:{label:string;value:ReactNode;note:string;tone?:string}[]}){return <div className="metrics">{items.map(item=><section key={item.label} className="metric" style={{borderTop:item.tone==='warning'?'3px solid #d97706':item.tone==='success'?'3px solid var(--success)':item.tone==='error'?'3px solid #ef4444':'3px solid transparent'}}><span>{item.label}</span><strong>{item.value}</strong><small>{item.note}</small></section>)}</div>}

// Step 1: Facts with toTitleLabel
export function Facts({values}:{values:Row}){return <dl className="facts">{Object.entries(values).map(([k,v])=><div key={k}><dt>{toTitleLabel(k)}</dt><dd>{typeof v==='object'?JSON.stringify(v):String(v??'Unavailable')}</dd></div>)}</dl>}
function friendly(value:any):ReactNode{if(value===null||value===undefined)return 'Unavailable';if(Array.isArray(value))return value.length?value.map(v=>typeof v==='object'?JSON.stringify(v):String(v)).join(', '):'None';if(typeof value==='object'){const pairs=Object.entries(value).filter(([,v])=>v!==null&&v!==undefined).slice(0,6);return pairs.length?pairs.map(([k,v])=>`${toTitleLabel(k)}: ${Array.isArray(v)?v.join(', '):typeof v==='object'?'available':String(v)}`).join(' · '):'No details';}return String(value)}

// Step 1: ReadableData with toTitleLabel
export function ReadableData({value,empty='No details are available.'}:{value:Row;empty?:string}){const entries=Object.entries(value).filter(([,v])=>v!==null&&v!==undefined);return entries.length?<dl className="readable-data">{entries.map(([key,item])=><div key={key}><dt>{toTitleLabel(key)}</dt><dd>{friendly(item)}</dd></div>)}</dl>:<p>{empty}</p>}
export function Json({value}:{value:unknown}){return <pre className="json">{JSON.stringify(value,null,2)??'Unavailable'}</pre>}

export function Field({label,children}:{label:string;children:ReactElement<{id?:string}>}){const fieldId=useId();return <div className="field"><label htmlFor={fieldId}><span>{label}</span></label>{cloneElement(children,{id:fieldId})}</div>}

// Step 2: Mutation with improved feedback
export function Mutation({children}:{children:(run:(job:()=>Promise<unknown>,success?:string)=>Promise<void>,busy:boolean)=>ReactNode}){
  const [busy,setBusy]=useState(false)
  const [message,setMessage]=useState('')
  const [error,setError]=useState('')
  useEffect(()=>{if(!message)return;const t=setTimeout(()=>setMessage(''),4000);return()=>clearTimeout(t)},[message])
  async function run(job:()=>Promise<unknown>,success='Saved by the backend.'){setBusy(true);setMessage('');setError('');try{await job();setMessage(success)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <>
    <div style={{pointerEvents:busy?'none':'auto',opacity:busy?0.7:1,transition:'opacity 0.15s'}}>
      {children(run,busy)}
    </div>
    {error&&<div className="notice notice-error" role="alert"><div className="notice-inner"><XCircle size={15} color="#ef4444"/><span className="notice-inner-body">{error}</span><button className="notice-dismiss icon-button" onClick={()=>setError('')}><X size={14}/></button></div></div>}
    {message&&<div className="notice notice-success" role="status"><div className="notice-inner"><CheckCircle size={15} color="var(--success)"/><span className="notice-inner-body">{message}</span><button className="notice-dismiss icon-button" onClick={()=>setMessage('')}><X size={14}/></button></div></div>}
  </>
}
export const money=(cents:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(cents/100)
