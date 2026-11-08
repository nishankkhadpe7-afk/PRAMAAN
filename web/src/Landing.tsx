import {useEffect,useMemo,useRef,useState} from 'react'
import {Link} from 'react-router-dom'
import {ArrowRight,CheckCircle2,FileLock2,GitCompareArrows,ScanSearch,Scale,ShieldCheck,Shuffle} from 'lucide-react'
import {Guilloche,Microtext,ShiftInk,Thread} from './print'
const chapters=[
 [FileLock2,'Preserve','The client’s sales register is stored byte for byte with its SHA-256. Nothing is edited in place; every change is a new, linked version.'],
 [GitCompareArrows,'Reconcile','Register rows are compared with recorded sales on exact dates, cents and GSTINs. Every difference keeps both original values.'],
 [ScanSearch,'Detect','Deterministic checks for document mismatch, related parties, impossible routes, forged e-invoices and revenue without a sale.'],
 [Shuffle,'Sample','Reproducible, risk-weighted sampling from a sealed seed. Re-run it and the same sales come back, every time.'],
 [Scale,'Evidence','Missing papers become requests to the client. Documents are hashed on arrival and tied to the sale they support.'],
 [ShieldCheck,'Conclude','AI proposes, a human decides. Every explanation cites evidence or is rejected, then ships as a defensibility pack.'],
] as const
// U4: results from the project's own synthetic benchmark (docs/EVALUATION.md), labelled as such; not a claim about real-world accuracy.
const stats=[['8 / 8','planted irregularities flagged in the synthetic benchmark'],['3 / 8','flagged by document matching alone'],['0','false alarms on the benchmark\'s clean sales'],['16','deterministic audit checks (T00–T15)']]
function useReveal(){const ref=useRef<HTMLDivElement>(null);useEffect(()=>{const el=ref.current;if(!el)return;if(typeof IntersectionObserver==='undefined'){el.querySelectorAll('.reveal').forEach(n=>n.classList.add('in'));return};const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.15});el.querySelectorAll('.reveal').forEach(n=>io.observe(n));return()=>io.disconnect()},[]);return ref}
export function Landing({to}:{to:string}){
  const reveal=useReveal(),[tilt,setTilt]=useState({x:0,y:0})
  const bits=useMemo(()=>Array.from({length:44},(_,i)=>{const r=(n:number)=>{const v=Math.sin(i*12.9898+n*78.233)*43758.5453;return v-Math.floor(v)};return{left:r(1)*100,delay:-r(2)*18,dur:14+r(3)*14,size:5+r(4)*9,rot:r(5)*360}}),[])
  return <div className="landing" ref={reveal}>
    <div className="landing-bits" aria-hidden="true">{bits.map((b,i)=><i key={i} style={{left:b.left+'%',width:b.size,height:b.size*.55,animationDelay:b.delay+'s',animationDuration:b.dur+'s',['--r' as string]:b.rot+'deg'}}/>)}</div>
    <header className="landing-nav"><Link to="/" className="landing-brand"><span className="brand-mark"><i/><i/><i/></span>Pramaan</Link><Link className="pill-cta ghost" to={to}>Open the workspace</Link></header>
    <section className="hero">
      <div className="hero-copy">
        <p className="hero-eyebrow">Verifiable financial audit infrastructure</p>
        <h1>Did this sale <ShiftInk>really</ShiftInk> happen?</h1>
        <p className="hero-lede">An invoice shows a sale was recorded, not that it occurred. Pramaan checks every sale against its source, its papers and its counterparties, then shows you the ones that would not pass.</p>
        <div className="hero-actions"><Link className="pill-cta" to={to}><CheckCircle2 size={18}/>Open the workspace</Link><a className="pill-cta ghost" href="#how">See how it works</a></div>
        <p className="hero-foot"><i/>Prototype evaluated on synthetic data only. Benchmark figures come from the project’s own test set (docs/EVALUATION.md).</p>
      </div>
      <div className="note-wrap" onMouseMove={e=>{const r=e.currentTarget.getBoundingClientRect();setTilt({x:((e.clientX-r.left)/r.width-.5)*10,y:((e.clientY-r.top)/r.height-.5)*-8})}} onMouseLeave={()=>setTilt({x:0,y:0})}>
        <div className="note" style={{transform:`perspective(900px) rotateY(${tilt.x}deg) rotateX(${tilt.y}deg)`}}>
          <div className="note-body"><small>TAX INVOICE · SYNTHETIC DEMO EVIDENCE</small><p>Demo case INV-009, dated 2025-06-20. Flagged by six checks: T01, T02, T06, T11, T13, T15.</p><strong><ShiftInk>₹ 47,20,000</ShiftInk></strong><code>PRA/25-26/009</code><Microtext/></div>
          <Thread/><div className="note-seal"><Guilloche size={170}/></div>
        </div>
      </div>
    </section>
    <section className="land-stats">{stats.map(([n,l])=><div key={l} className="reveal"><strong>{n}</strong><span>{l}</span></div>)}</section>
    <section id="how" className="land-chapters"><h2 className="reveal">Six steps from register to conclusion</h2><div className="chapter-grid">{chapters.map(([Icon,t,b],i)=><article key={t} className="chapter reveal" style={{transitionDelay:i*70+'ms'}}><span className="chapter-n">0{i+1}</span><Icon size={22}/><h3>{t}</h3><p>{b}</p></article>)}</div></section>
    <section className="land-cta reveal"><h2>Inspect a register now.</h2><Link className="pill-cta" to={to}>Open the workspace <ArrowRight size={18}/></Link></section>
    <footer className="land-foot"><Microtext/><span>Pramaan · prototype · all data fictional</span></footer>
  </div>
}
