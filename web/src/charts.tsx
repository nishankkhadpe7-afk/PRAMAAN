import {ReactNode,useEffect,useRef,useState} from 'react'
import {AlertOctagon,AlertTriangle,CheckCircle2,FileQuestion,Radio,SearchCheck} from 'lucide-react'
import {Row} from './components'
import './charts.css'
import './workflow.css'

// ---- Live refresh ---------------------------------------------------------
// Ticks every `ms` while the tab is visible; feed the value into useData's refresh argument.
export function useLiveTick(ms=10000){
  const [tick,setTick]=useState(0)
  useEffect(()=>{const timer=setInterval(()=>{if(document.visibilityState!=='hidden')setTick(n=>n+1)},ms);return()=>clearInterval(timer)},[ms])
  return tick
}
// Records when data last changed, so the live pill can say "updated 4s ago".
export function useUpdatedAt(data:unknown){
  const [at,setAt]=useState(()=>Date.now()),[now,setNow]=useState(()=>Date.now())
  useEffect(()=>{if(data)setAt(Date.now())},[data])
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[])
  return Math.max(0,Math.round((now-at)/1000))
}
// U8: saved audit runs are immutable, so they say so instead of implying live data.
export function FrozenPill(){return <span className="live-pill frozen-pill" title="Saved audit runs never change; rerun to test current data"><span className="frozen-dot"/>Frozen snapshot</span>}
export function LivePill({data}:{data:unknown}){const ago=useUpdatedAt(data);return <span className="live-pill" title="Charts refresh automatically from the backend"><span className="live-dot"/><Radio size={13}/>Live<small>{ago<2?'just now':ago<60?`${ago}s ago`:`${Math.floor(ago/60)}m ago`}</small></span>}

// ---- Domain vocabulary ----------------------------------------------------
export const TEST_LABELS:Record<string,string>={
  T00:'Register reconciliation',T01:'Disclosed related party',T02:'Related-party network',T03:'Revenue cut-off timing',
  T04:'Missing movement documents',T05:'Unlinked revenue journals',T06:'Invoice vs dispatch mismatch',T07:'Reused evidence',
  T08:'Period-end concentration',T09:'Post-period credit notes',T10:'Transaction splitting',T11:'Movement plausibility',
  T12:'Requested evidence',T13:'E-invoice QR signature',T14:'Unapproved promotions',T15:'GSTR-1 vs books',
}
export const testLabel=(test:string)=>TEST_LABELS[test]||test

// Automated states fold into four severity tiers. Tiers describe the kind of signal,
// never a conclusion: every tier still requires human review.
export type Tier='critical'|'serious'|'warning'|'info'
export const TIERS:{key:Tier;label:string;hint:string;Icon:typeof AlertOctagon}[]=[
  {key:'critical',label:'Inconsistent',hint:'Records contradict each other',Icon:AlertOctagon},
  {key:'serious',label:'Evidence gap',hint:'Expected evidence is missing or unverifiable',Icon:FileQuestion},
  {key:'warning',label:'Needs review',hint:'Pattern worth a human look',Icon:AlertTriangle},
  {key:'info',label:'Context',hint:'Disclosed or classified for awareness',Icon:SearchCheck},
]
const STATE_TIER:Record<string,Tier>={IMPOSSIBLE:'critical',INCONSISTENT:'critical',GAP:'serious',UNAVAILABLE:'serious',UNVERIFIED:'serious',REVIEW:'warning',DISCLOSED_RELATED_PARTY:'info',GOVERNMENT_REGISTERED_DEMO:'info'}
export const tierOf=(state:string):Tier=>STATE_TIER[state]||'warning'
export const tierMeta=(tier:Tier)=>TIERS.find(t=>t.key===tier)!
export const humanState=(state:string)=>state.toLowerCase().replaceAll('_',' ').replace(/^./,c=>c.toUpperCase())

export function TierBadge({state}:{state:string}){const meta=tierMeta(tierOf(state));return <span className={'tier-badge tier-'+meta.key} title={meta.hint}><meta.Icon size={13}/>{humanState(state)}</span>}

export function countBy<T>(items:T[],key:(item:T)=>string){const out=new Map<string,number>();for(const item of items){const k=key(item);out.set(k,(out.get(k)||0)+1)}return out}

// Measures the rendered width so SVG charts keep a fixed height at any width.
function useWidth(fallback=520){
  const ref=useRef<HTMLDivElement>(null);const [width,setWidth]=useState(fallback)
  useEffect(()=>{const el=ref.current;if(!el||typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(([entry])=>{const w=Math.round(entry.contentRect.width);if(w>0)setWidth(w)});observer.observe(el);return()=>observer.disconnect()},[])
  return [ref,width] as const
}

// ---- Tooltip --------------------------------------------------------------
type Tip={x:number;y:number;title:string;body:string}|null
function useTip(){const [tip,setTip]=useState<Tip>(null);return {tip,hide:()=>setTip(null),show:(e:{clientX:number;clientY:number;currentTarget:Element},title:string,body:string)=>{const box=e.currentTarget.closest('.chart')!.getBoundingClientRect();setTip({x:e.clientX-box.left,y:e.clientY-box.top,title,body})}}}
function TipBox({tip}:{tip:Tip}){return tip?<div className="chart-tip" style={{left:tip.x,top:tip.y}}><strong>{tip.title}</strong><span>{tip.body}</span></div>:null}

// ---- Donut ----------------------------------------------------------------
export type Slice={key:string;label:string;value:number;color:string;icon?:ReactNode}
export function Donut({slices,center,caption,active,onSelect}:{slices:Slice[];center:ReactNode;caption:string;active?:string;onSelect?:(key:string)=>void}){
  const {tip,show,hide}=useTip();const total=slices.reduce((s,x)=>s+x.value,0);const r=70,stroke=20,c=2*Math.PI*r,gap=total>0&&slices.filter(s=>s.value).length>1?3:0
  let offset=0
  return <div className="chart donut-wrap"><div className="donut"><svg viewBox="0 0 180 180" role="img" aria-label={caption}><circle cx="90" cy="90" r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke}/>{total>0&&slices.map(s=>{const len=s.value/total*c;const el=s.value?<circle key={s.key} className={'donut-seg'+(active&&active!==s.key?' dim':'')} cx="90" cy="90" r={r} fill="none" stroke={s.color} strokeWidth={stroke} strokeDasharray={`${Math.max(len-gap,0.01)} ${c}`} strokeDashoffset={-offset} transform="rotate(-90 90 90)" onMouseMove={e=>show(e,s.label,`${s.value} · ${Math.round(s.value/total*100)}%`)} onMouseLeave={hide} onClick={()=>onSelect?.(s.key)} style={{cursor:onSelect?'pointer':undefined}}/>:null;offset+=len;return el})}</svg><div className="donut-center">{center}</div></div>
  <ul className="legend">{slices.map(s=><li key={s.key}><button type="button" className={'legend-item'+(active===s.key?' on':'')+(active&&active!==s.key?' dim':'')} onClick={()=>onSelect?.(s.key)} disabled={!onSelect}><i style={{background:s.color}}/>{s.icon}<span>{s.label}</span><b>{s.value}</b></button></li>)}</ul><TipBox tip={tip}/></div>
}

// ---- Horizontal bars ------------------------------------------------------
export function HBars({rows,active,onSelect,color='var(--viz-1)',unit='findings',format=(v:number)=>String(v)}:{rows:{key:string;label:string;sub?:string;value:number}[];active?:string;onSelect?:(key:string)=>void;color?:string;unit?:string;format?:(value:number)=>string}){
  const {tip,show,hide}=useTip();const max=Math.max(...rows.map(r=>r.value),1)
  return <div className="chart hbars">{rows.map(r=><button type="button" key={r.key} className={'hbar'+(active===r.key?' on':'')+(active&&active!==r.key?' dim':'')} onClick={()=>onSelect?.(r.key)} disabled={!onSelect} onMouseMove={e=>show(e,r.label,`${format(r.value)} ${unit}`.trim())} onMouseLeave={hide}><span className="hbar-label" title={r.label}>{r.label}{r.sub&&<small>{r.sub}</small>}</span><span className="hbar-track"><i style={{width:`${r.value/max*100}%`,background:color}}/></span><b>{format(r.value)}</b></button>)}<TipBox tip={tip}/></div>
}

// ---- Column chart (single series, time on x) ------------------------------
export function Columns({points,unit='findings',color='var(--viz-1)'}:{points:{label:string;value:number}[];unit?:string;color?:string}){
  const {tip,show,hide}=useTip();const [ref,W]=useWidth();const max=Math.max(...points.map(p=>p.value),1);const H=190,pad={l:28,r:8,t:12,b:26};const bw=(W-pad.l-pad.r)/Math.max(points.length,1)
  const ticks=[0,Math.ceil(max/2),max]
  return <div className="chart" ref={ref}><svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="columns" role="img" aria-label={`${unit} by month`}>
    {ticks.map(t=>{const y=pad.t+(H-pad.t-pad.b)*(1-t/max);return <g key={t}><line x1={pad.l} x2={W-pad.r} y1={y} y2={y} className="grid"/><text x={pad.l-6} y={y+4} textAnchor="end" className="axis">{t}</text></g>})}
    {points.map((p,i)=>{const h=(H-pad.t-pad.b)*p.value/max;const w=Math.max(Math.min(bw*0.6,44),6);const x=pad.l+i*bw+(bw-w)/2;const y=H-pad.b-h;return <g key={p.label}><rect className="col-hit" x={pad.l+i*bw} y={pad.t} width={bw} height={H-pad.t-pad.b} onMouseMove={e=>show(e,p.label,`${p.value} ${unit}`)} onMouseLeave={hide}/><path className="col" d={h>0?`M${x},${H-pad.b} V${y+Math.min(4,h)} q0,-4 4,-4 h${w-8} q4,0 4,4 V${H-pad.b} Z`:''} fill={color} pointerEvents="none"/><text x={pad.l+i*bw+bw/2} y={H-8} textAnchor="middle" className="axis">{p.label}</text></g>})}
    <line x1={pad.l} x2={W-pad.r} y1={H-pad.b} y2={H-pad.b} className="baseline"/>
  </svg><TipBox tip={tip}/></div>
}

// ---- Area trend (single series) -------------------------------------------
export function AreaTrend({points,unit='observations',color='var(--viz-1)'}:{points:{label:string;value:number;sub?:string}[];unit?:string;color?:string}){
  const {tip,show,hide}=useTip();const [ref,W]=useWidth();const [hover,setHover]=useState<number|null>(null);const H=200,pad={l:30,r:14,t:14,b:22};const max=Math.max(...points.map(p=>p.value),1)
  const x=(i:number)=>points.length<2?(W-pad.l-pad.r)/2+pad.l:pad.l+i*(W-pad.l-pad.r)/(points.length-1);const y=(v:number)=>pad.t+(H-pad.t-pad.b)*(1-v/max)
  const line=points.map((p,i)=>`${i?'L':'M'}${x(i)},${y(p.value)}`).join(' ');const area=points.length?`${line} L${x(points.length-1)},${H-pad.b} L${x(0)},${H-pad.b} Z`:''
  return <div className="chart" ref={ref}><svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="area" role="img" aria-label={`${unit} per audit run`} onMouseLeave={()=>{setHover(null);hide()}}>
    <defs><linearGradient id="area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity=".35"/><stop offset="100%" stopColor={color} stopOpacity="0"/></linearGradient></defs>
    {[0,max].map(t=><g key={t}><line x1={pad.l} x2={W-pad.r} y1={y(t)} y2={y(t)} className="grid"/><text x={pad.l-6} y={y(t)+4} textAnchor="end" className="axis">{t}</text></g>)}
    <path d={area} fill="url(#area-fill)"/><path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round"/>
    {hover!==null&&<line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={H-pad.b} className="crosshair"/>}
    {points.map((p,i)=><g key={i}><circle cx={x(i)} cy={y(p.value)} r={hover===i||points.length<8?4.5:0} fill={color} stroke="var(--surface)" strokeWidth="2"/><rect x={x(i)-(W/Math.max(points.length,1))/2} y={0} width={W/Math.max(points.length,1)} height={H} fill="transparent" onMouseMove={e=>{setHover(i);show(e,p.label,`${p.value} ${unit}${p.sub?' · '+p.sub:''}`)}}/></g>)}
  </svg><TipBox tip={tip}/></div>
}

// ---- Progress ring --------------------------------------------------------
export function Ring({value,total,label,color='var(--good)'}:{value:number;total:number;label:string;color?:string}){
  const r=34,c=2*Math.PI*r,pct=total?value/total:0
  return <div className="ring"><svg viewBox="0 0 84 84" role="img" aria-label={`${label}: ${value} of ${total}`}><circle cx="42" cy="42" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="8"/>{value>0&&<circle className="ring-arc" cx="42" cy="42" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={`${pct*c} ${c}`} transform="rotate(-90 42 42)"/>}</svg><strong>{Math.round(pct*100)}%</strong></div>
}

// ---- Stacked 100% bar ------------------------------------------------------
export function StackBar({parts,active,onSelect}:{parts:{key:string;label:string;value:number;color:string}[];active?:string;onSelect?:(key:string)=>void}){
  const {tip,show,hide}=useTip();const total=parts.reduce((s,p)=>s+p.value,0)||1
  return <div className="chart"><div className="stackbar">{parts.filter(p=>p.value).map(p=><button type="button" key={p.key} className={active&&active!==p.key?'dim':''} style={{flexGrow:p.value,background:p.color}} onClick={()=>onSelect?.(p.key)} disabled={!onSelect} aria-label={`${p.label}: ${p.value}`} onMouseMove={e=>show(e,p.label,`${p.value} · ${Math.round(p.value/total*100)}%`)} onMouseLeave={hide}/>)}</div>
  <ul className="legend inline">{parts.map(p=><li key={p.key}><button type="button" className={'legend-item'+(active===p.key?' on':'')+(active&&active!==p.key?' dim':'')} onClick={()=>onSelect?.(p.key)} disabled={!onSelect}><i style={{background:p.color}}/><span>{p.label}</span><b>{p.value}</b></button></li>)}</ul><TipBox tip={tip}/></div>
}

export const VIZ=['var(--viz-1)','var(--viz-2)','var(--viz-3)','var(--viz-4)','var(--viz-5)','var(--viz-6)','var(--viz-7)','var(--viz-8)']
const ASSERTION_ORDER=['occurrence','completeness','cutoff','accuracy','classification','existence','presentation']
export const assertionColor=(a:string)=>{const i=ASSERTION_ORDER.indexOf(a.toLowerCase());return VIZ[(i<0?ASSERTION_ORDER.length:i)%VIZ.length]}
export const TIER_COLOR:Record<Tier,string>={critical:'var(--critical)',serious:'var(--serious)',warning:'var(--warning)',info:'var(--viz-1)'}

// ---- Insight block: the shared visual summary of a run's findings ---------
export function FindingInsights({findings,invoices,filters,setFilter}:{findings:Row[];invoices:Row[];filters:{tier?:string;test?:string;assertion?:string};setFilter:(key:'tier'|'test'|'assertion',value:string)=>void}){
  const tiers=countBy(findings,f=>tierOf(f.state));const tests=[...countBy(findings,f=>f.test_id)].sort((a,b)=>b[1]-a[1]);const assertions=[...countBy(findings,f=>f.assertion||'unspecified')].sort((a,b)=>b[1]-a[1])
  const reviewed=findings.filter(f=>f.human_decision).length;const confirmed=findings.filter(f=>f.human_decision?.outcome==='EXCEPTION_CONFIRMED').length
  const dates:Record<string,string>={};for(const inv of invoices)dates[inv.invoice_id]=inv.invoice_date
  const months=[...countBy(findings.filter(f=>dates[f.object_ref]),f=>dates[f.object_ref].slice(0,7))].sort((a,b)=>a[0].localeCompare(b[0]))
  const monthLabel=(m:string)=>new Date(m+'-01T00:00:00').toLocaleDateString('en-IN',{month:'short',year:'2-digit'})
  const top=tests.slice(0,7)
  return <div className="insights">
    <div className="insight-kpis">
      <div className="kpi"><span>Automated observations</span><strong>{findings.length}</strong><small>Signals for review, not conclusions</small></div>
      <div className="kpi"><span>Inconsistencies</span><strong className="t-critical">{tiers.get('critical')||0}</strong><small>Records disagree with each other</small></div>
      <div className="kpi"><span>Evidence gaps</span><strong className="t-serious">{tiers.get('serious')||0}</strong><small>Missing or unverifiable support</small></div>
      <div className="kpi kpi-ring"><Ring value={reviewed} total={findings.length} label="Human review progress"/><div><span>Human review</span><strong>{reviewed}<em>/{findings.length}</em></strong><small>{confirmed} confirmed exception{confirmed===1?'':'s'}</small></div></div>
    </div>
    <div className="insight-grid">
      <section className="viz-card"><header><h3>Signal mix</h3><p>By kind of automated signal · click to filter</p></header><Donut caption="Findings by signal type" active={filters.tier} onSelect={k=>setFilter('tier',k)} center={<><strong>{findings.length}</strong><small>signals</small></>} slices={TIERS.map(t=>({key:t.key,label:t.label,value:tiers.get(t.key)||0,color:TIER_COLOR[t.key],icon:<t.Icon size={13}/>}))}/></section>
      <section className="viz-card"><header><h3>Where they come from</h3><p>Top audit tests by observation count</p></header><HBars active={filters.test} onSelect={k=>setFilter('test',k)} rows={top.map(([k,v])=>({key:k,label:testLabel(k),sub:k,value:v}))}/>{tests.length>top.length&&<small className="viz-foot">+{tests.length-top.length} more tests with {tests.slice(top.length).reduce((s,[,v])=>s+v,0)} observations</small>}</section>
    </div>
    <div className="insight-grid">
      <section className="viz-card"><header><h3>Assertions affected</h3><p>Which financial-statement assertion each signal tests</p></header><StackBar active={filters.assertion} onSelect={k=>setFilter('assertion',k)} parts={assertions.map(([k,v])=>({key:k,label:k.replace(/^./,c=>c.toUpperCase()),value:v,color:assertionColor(k)}))}/></section>
      <section className="viz-card"><header><h3>When it happened</h3><p>Invoice-linked observations by invoice month</p></header>{months.length?<Columns points={months.map(([m,v])=>({label:monthLabel(m),value:v}))}/>:<p className="viz-empty">No invoice-dated observations in this snapshot.</p>}</section>
    </div>
  </div>
}
