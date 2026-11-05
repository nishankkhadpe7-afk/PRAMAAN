import {ReactNode,ReactElement,cloneElement,useEffect,useId,useRef,useState} from 'react'
import {ArrowUpRight,CheckCircle,Inbox,X,XCircle} from 'lucide-react'
import {useSession} from './session'
export type Row=Record<string,any>

export function toTitleLabel(key:string):string{return key.split('_').join(' ').replace(/^./,c=>c.toUpperCase())}

export function useData<T=any>(path:string|null,refresh=0){const {api}=useSession();const [state,setState]=useState<{data:T|null;error:string;loading:boolean;path:string|null}>({data:null,error:'',loading:true,path:null});useEffect(()=>{if(!path){setState({data:null,error:'',loading:false,path});return}const controller=new AbortController();setState(previous=>({data:previous.path===path?previous.data:null,error:'',loading:previous.path!==path||previous.data===null,path}));api!.json<T>(path,'GET',undefined,controller.signal).then(data=>{if(!controller.signal.aborted)setState({data,error:'',loading:false,path})}).catch(e=>{if(!controller.signal.aborted)setState({data:null,error:e.message,loading:false,path})});return()=>controller.abort()},[api,path,refresh]);return state.path===path?state:{data:null,error:'',loading:!!path,path}}


export function State({loading,error,children}:{loading?:boolean;error?:string;children:ReactNode}){return loading?<div className="skeleton-loader" role="status" aria-label="Loading"><div className="skeleton-row" style={{width:'80%'}}/><div className="skeleton-row" style={{width:'60%'}}/><div className="skeleton-row" style={{width:'70%'}}/></div>:error?<div className="notice notice-error" role="alert"><div className="notice-inner"><XCircle size={17}/><span className="notice-inner-body">{error}</span></div></div>:<>{children}</>}

const TONE_MAP:Record<string,string>={
  'OPEN_REVIEW':'warning','EXCEPTION_CONFIRMED':'error','EXPLAINED':'success','DATA_ERROR':'error',
  'Awaiting client upload':'warning','Fulfilled':'success','Recorded':'success',
  'MCP response':'info','Guidance only':'neutral',
  'Valid':'success','Broken':'error','Detected':'warning','None detected':'success',
  'Review, with context':'info',
}
function resolveTone(text:string,tone:string):string{if(tone!=='neutral')return tone;return TONE_MAP[text]??'neutral'}
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}){const resolved=resolveTone(String(children),tone);return <span className={'badge badge-'+resolved}>{children}</span>}

export function Header({eyebrow,title,description,action}:{eyebrow:string;title:string;description:string;action?:ReactNode}){return <header className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action&&<div className="page-heading-action">{action}</div>}</header>}
export type Selection={selected:Set<string>;toggle:(key:string)=>void;keyOf:(row:Row)=>string;labelOf:(row:Row)=>string}
// UI-08: the scroll container is a labelled, focusable region so keyboard users can scroll wide tables.
// UI-05: optional row selection (checkbox column) for bulk actions.
export function Table({columns,rows,onRow,empty='No records yet.',selection,label='Table'}:{columns:{label:string;key?:string;render?:(row:Row)=>ReactNode;align?:'left'|'center'|'right'}[];rows:Row[];onRow?:(row:Row)=>void;empty?:string;selection?:Selection;label?:string}){
  if(!rows.length)return <div className="empty"><Inbox size={32}/><p>{empty}</p></div>
  const keyOf=(r:Row,i:number)=>selection?selection.keyOf(r):r.invoice_id||r.finding_id||r.request_id||r.run_id||r.upload_id||r.customer_id||r.credit_note_id||r.package_id||r.seq||r.edge_id||i
  return <div className="table-scroll" tabIndex={0} role="region" aria-label={label}><table><thead><tr>{selection&&<th scope="col" className="select-col"><span className="sr-only">Select</span></th>}{columns.map(c=><th key={c.label} scope="col" className={c.align?`align-${c.align}`:undefined}>{c.label}</th>)}</tr></thead><tbody>{rows.map((r,i)=>{const key=keyOf(r,i);const checked=!!selection?.selected.has(String(key));return <tr className={(onRow?'clickable':'')+(checked?' selected-row':'')} onClick={onRow?()=>onRow(r):undefined} key={key} data-row-key={String(key)}>{selection&&<td className="select-col" onClick={e=>e.stopPropagation()}><input type="checkbox" checked={checked} aria-label={'Select '+selection.labelOf(r)} onChange={()=>selection.toggle(String(key))}/></td>}{columns.map((c,j)=><td key={c.label} className={c.align?`align-${c.align}`:undefined}>{j===0&&onRow?<button type="button" className="row-link" onClick={e=>{e.stopPropagation();onRow(r)}}>{c.render?c.render(r):String(r[c.key!]??'Unavailable')} <ArrowUpRight size={13} aria-hidden="true"/></button>:c.render?c.render(r):String(r[c.key!]??'Unavailable')}</td>)}</tr>})}</tbody></table></div>
}
export function Panel({title,subtitle,children,action}:{title:string;subtitle?:string;children:ReactNode;action?:ReactNode}){return <section className="panel"><div className="panel-heading"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>{action&&<div className="panel-heading-action">{action}</div>}</div>{children}</section>}

export function Metrics({items}:{items:{label:string;value:ReactNode;note:string;tone?:string}[]}){return <div className="metrics">{items.map(item=><section key={item.label} className={'metric '+(item.tone?`metric-${item.tone}`:'')}><span>{item.label}</span><strong>{item.value}</strong><small>{item.note}</small></section>)}</div>}

export function Facts({values}:{values:Row}){return <dl className="facts">{Object.entries(values).map(([k,v])=><div key={k}><dt>{toTitleLabel(k)}</dt><dd>{v&&typeof v==='object'?<pre className="facts-json">{JSON.stringify(v,null,2)}</pre>:String(v??'Unavailable')}</dd></div>)}</dl>}
function friendly(value:any):ReactNode{if(value===null||value===undefined)return 'Unavailable';if(Array.isArray(value))return value.length?value.map(v=>typeof v==='object'?JSON.stringify(v):String(v)).join(', '):'None';if(typeof value==='object'){const pairs=Object.entries(value).filter(([,v])=>v!==null&&v!==undefined).slice(0,6);return pairs.length?pairs.map(([k,v])=>`${toTitleLabel(k)}: ${Array.isArray(v)?v.join(', '):typeof v==='object'?'available':String(v)}`).join(' · '):'No details';}return String(value)}

export function ReadableData({value,empty='No details are available.'}:{value:Row;empty?:string}){const entries=Object.entries(value).filter(([,v])=>v!==null&&v!==undefined);return entries.length?<dl className="readable-data">{entries.map(([key,item])=><div key={key}><dt>{toTitleLabel(key)}</dt><dd>{friendly(item)}</dd></div>)}</dl>:<p>{empty}</p>}
export function Json({value}:{value:unknown}){return <pre className="json">{JSON.stringify(value,null,2)??'Unavailable'}</pre>}

export function Field({label,children}:{label:string;children:ReactElement<{id?:string}>}){const fieldId=useId();return <div className="field"><label htmlFor={fieldId}><span>{label}</span></label>{cloneElement(children,{id:fieldId})}</div>}

export function Mutation({children}:{children:(run:(job:()=>Promise<unknown>,success?:string)=>Promise<void>,busy:boolean)=>ReactNode}){
  const [busy,setBusy]=useState(false)
  const [message,setMessage]=useState('')
  const [error,setError]=useState('')
  useEffect(()=>{if(!message)return;const t=setTimeout(()=>setMessage(''),4000);return()=>clearTimeout(t)},[message])
  async function run(job:()=>Promise<unknown>,success='Saved by the backend.'){setBusy(true);setMessage('');setError('');try{await job();setMessage(success)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <>
    <div className={'mutation-body '+(busy?'is-busy':'')} aria-busy={busy}>
      {children(run,busy)}
    </div>
    {error&&<div className="notice notice-error" role="alert"><div className="notice-inner"><XCircle size={17}/><span className="notice-inner-body">{error}</span><button type="button" className="notice-dismiss icon-button" aria-label="Dismiss error" onClick={()=>setError('')}><X size={14}/></button></div></div>}
    {message&&<div className="notice notice-success" role="status"><div className="notice-inner"><CheckCircle size={17}/><span className="notice-inner-body">{message}</span><button type="button" className="notice-dismiss icon-button" aria-label="Dismiss message" onClick={()=>setMessage('')}><X size={14}/></button></div></div>}
  </>
}
export const money=(cents:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(cents/100)

export function Drawer({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}){
  // F7: modal semantics: focus moves into the drawer, Tab cycles inside it, Escape closes it,
  // and focus returns to the control that opened it.
  const ref=useRef<HTMLElement>(null)
  // Captured during the first render, before autoFocus moves focus into the drawer.
  const openerRef=useRef<HTMLElement|null>(typeof document!=='undefined'?document.activeElement as HTMLElement|null:null)
  // UI-18: keep the latest onClose in a ref so a parent re-render (inline callback) does not re-run
  // the effect, whose cleanup would steal focus back to the opener mid-typing.
  const closeRef=useRef(onClose);closeRef.current=onClose
  useEffect(()=>{const opener=openerRef.current
    const focusable=()=>Array.from(ref.current?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')||[])
    const k=(e:KeyboardEvent)=>{if(e.key==='Escape'){closeRef.current();return}if(e.key!=='Tab')return;const items=focusable();if(!items.length)return;const first=items[0],last=items[items.length-1]
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
    window.addEventListener('keydown',k);const prev=document.body.style.overflow;document.body.style.overflow='hidden'
    return()=>{window.removeEventListener('keydown',k);document.body.style.overflow=prev;if(opener&&document.contains(opener))opener.focus()}},[])
  return <div className="drawer-backdrop" onClick={onClose}><aside ref={ref} className="drawer" role="dialog" aria-modal="true" aria-label={title} onClick={e=>e.stopPropagation()}><div className="drawer-head"><h2>{title}</h2><button type="button" className="drawer-close" aria-label="Close" onClick={onClose} autoFocus><X size={18}/></button></div><div className="drawer-body">{children}</div></aside></div>
}
