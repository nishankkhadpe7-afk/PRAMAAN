import {Suspense,lazy,useEffect,useState,useRef} from 'react'
import {Link,NavLink,Navigate,Outlet,Route,Routes,useLocation,useNavigate} from 'react-router-dom'
import {ArrowLeft,ArrowRight,Check,ChevronDown,ArrowUpRight,BookOpen,Building2,CircleHelp,ClipboardCheck,Eye,EyeOff,FileSearch,Files,LayoutDashboard,LogOut,Menu,MessageSquare,ShieldCheck,Workflow,X} from 'lucide-react'
import {useSession} from './session'
import {Drawer,Header,Mutation} from './components'
import {HelpContent} from './glossary'
// F8: each workspace is a separate chunk, so the landing and sign-in pages stay light.
const client=()=>import('./client'),auditor=()=>import('./auditor')
const ClientDashboard=lazy(()=>client().then(m=>({default:m.ClientDashboard}))),Business=lazy(()=>client().then(m=>({default:m.Business}))),Registers=lazy(()=>client().then(m=>({default:m.Registers}))),Inbox=lazy(()=>client().then(m=>({default:m.Inbox})))
const AuditDashboard=lazy(()=>auditor().then(m=>({default:m.AuditDashboard}))),AuditAssistant=lazy(()=>auditor().then(m=>({default:m.AuditAssistant}))),NewRun=lazy(()=>auditor().then(m=>({default:m.NewRun}))),RunWorkspace=lazy(()=>auditor().then(m=>({default:m.RunWorkspace}))),FindingDetail=lazy(()=>auditor().then(m=>({default:m.FindingDetail}))),SaleDetail=lazy(()=>auditor().then(m=>({default:m.SaleDetail})))

import {Landing} from './Landing'
export function Login(){
  const {signIn,expired}=useSession();
  const [token,setToken]=useState('');
  const [showToken,setShowToken]=useState(false);
  const navigate=useNavigate();

  return <div className="login">
    <div className="login-brand"><Brand/><Link className="login-back" to="/"><span className="back-arrow" aria-hidden="true"><ArrowLeft size={14}/></span><span>Back to home</span></Link></div>
    <div className="login-layout">
      <section className="login-intro">
        <p className="login-kicker">Revenue audit, end to end</p>
        <h1>Every sale.<br/><span className="login-accent">A traceable story.</span></h1>
        <p className="login-lede">From the client's original register to a frozen, reproducible workpaper. The system flags what doesn't reconcile; a qualified reviewer decides what it means.</p>
        <figure className="trail" aria-label="Example: how one sale is traced">
          <figcaption><span>One sale, traced</span><small>example</small></figcaption>
          <ol>
            {([['Register row 14','Client upload, fingerprinted','9f2c'],['Sales order SO-1042','Who ordered, what, when','41ab'],['Dispatch DN-0877','Goods actually left','c07e'],['Invoice MH/25-26/0042','₹1,18,000.00 incl. GST','5d19'],['Journal JV-311','Revenue booked in the ledger','e8a4']] as const).map(([what,why,hash],i)=>
              <li key={what} style={{['--i' as string]:i}}><i className="trail-node"/><div><strong>{what}</strong><small>{why}</small></div><code title="Each step's fingerprint is chained to the one before it">{hash}…</code></li>)}
            <li className="trail-end" style={{['--i' as string]:5}}><i className="trail-node"><ShieldCheck size={12}/></i><div><strong>Frozen workpaper</strong><small>Re-run any time; the result must match</small></div><span className="trail-seal">sealed</span></li>
          </ol>
        </figure>
      </section>
      <section className="login-card">
        <span className="login-lock" aria-hidden="true"><ShieldCheck size={18}/></span>
        <h2>Sign in to Pramaan</h2>
        <p>Paste the access credential issued for your role by the local launcher.</p>
        {expired&&<div role="alert" className="notice notice-error">Your session ended. Use a valid credential to continue.</div>}
        <Mutation>{(run,busy)=><form onSubmit={e=>{e.preventDefault();void run(async()=>{const caller=await signIn(token.trim());setToken('');navigate(caller.role==='auditor'?'/auditor':'/client',{replace:true})})}}>
          <div className="field">
            <label htmlFor="credential-input"><span>Access credential</span></label>
            <div className="input-wrapper">
              <input id="credential-input" type={showToken?'text':'password'} name="credential" autoComplete="off" autoCapitalize="none" spellCheck={false} value={token} onChange={e=>setToken(e.target.value)} required placeholder="Paste your provisioned token"/>
              <button type="button" className="toggle-pw" aria-label={showToken?'Hide credential':'Show credential'} onClick={()=>setShowToken(v=>!v)}>
                {showToken?<EyeOff size={16}/>:<Eye size={16}/>}
              </button>
            </div>
          </div>
          <button className="primary wide" disabled={busy}>
            {busy?'Validating identity…':'Enter workspace'}
            <ArrowRight size={16}/>
          </button>
        </form>}</Mutation>
        <div className="credential-help" role="note">
          <ShieldCheck size={17}/>
          <div>
            <strong>Need a local demo credential?</strong>
            <p>Generate a fresh client, auditor, or human credential with the project launcher, then paste it above. Credentials are never embedded in the web bundle.</p>
          </div>
        </div>
        <div className="login-note">
          <ShieldCheck size={16}/>
          <p>Your credential is kept only for this browser tab. It is cleared when you sign out, when it expires, or when the tab closes.</p>
        </div>
        <dl className="role-guide">
          <div><dt><i className="dot client"/>Client</dt><dd>Records sales, uploads registers, answers document requests.</dd></div>
          <div><dt><i className="dot limited"/>Auditor</dt><dd>Runs the checks and proposes conclusions.</dd></div>
          <div><dt><i className="dot on"/>Human reviewer</dt><dd>Records the final decision on each finding.</dd></div>
        </dl>
      </section>
    </div>
    <footer>
      <span>प्रमाण · PRAMAAN Trust Architecture</span>
      <span>Single-company SQLite forensic engine · SHA-256 hash-linked provenance</span>
    </footer>
  </div>
}
// One logo everywhere (landing, login, workspace sidebar).
function Brand(){return <Link to="/" className="landing-brand"><img className="brand-logo" src="/pramaan-logo.png" alt="Pramaan" width={121} height={24}/></Link>}
export function Guard({role}:{role:'client_employee'|'auditor'}){const {identity,restoring}=useSession();return restoring?<div className="skeleton-loader" role="status" aria-label="Restoring session"/>:!identity?<Navigate to="/login" replace/>:identity.role!==role?<Navigate to="/unauthorized" replace/>:<Outlet/>}
// "demo-human-reviewer" -> "Human Reviewer"; "launcher-client" -> "Client". Technical prefixes are dropped.
export function displayName(subject:string){const words=subject.replace(/^(demo|launcher|local|test)[-_.]/i,'').split(/[-_.\s@]+/).filter(Boolean);return (words.length?words:[subject]).map(w=>w[0].toUpperCase()+w.slice(1)).join(' ')}
function initialsOf(name:string){const w=name.split(' ');return (w.length>1?w[0][0]+w[1][0]:name.slice(0,2)).toUpperCase()}
function hueOf(s:string){let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))%360;return h}
function UserChip({subject,role,onHelp,onSignOut}:{subject:string;role:'human'|'auditor'|'client';onHelp:()=>void;onSignOut:()=>void}){
  const name=displayName(subject);const status={human:['Auditor','Human review on','on'],auditor:['Auditor','Proposals only','limited'],client:['Client','Records & evidence','client']}[role]
  const line=name===status[0]?status[1]:`${status[0]} · ${status[1]}`
  const [open,setOpen]=useState(false);const ref=useRef<HTMLDivElement>(null)
  useEffect(()=>{if(!open)return;const away=(e:MouseEvent)=>{if(!ref.current?.contains(e.target as Node))setOpen(false)};const esc=(e:KeyboardEvent)=>{if(e.key==='Escape')setOpen(false)};document.addEventListener('mousedown',away);document.addEventListener('keydown',esc);return()=>{document.removeEventListener('mousedown',away);document.removeEventListener('keydown',esc)}},[open])
  const h=hueOf(subject)
  const orb=(big=false)=><span className={'user-mark'+(big?' big':'')} style={{['--hue' as string]:h,['--hue2' as string]:(h+70)%360}} aria-hidden="true"><i className={'user-dot '+status[2]}/></span>
  return <div className="user-menu-wrap" ref={ref}>
    <button type="button" className={'user-chip'+(open?' open':'')} title={`Signed in as ${subject}`} aria-haspopup="menu" aria-expanded={open} aria-label={`Account: ${name}`} onClick={()=>setOpen(o=>!o)}>
      {orb()}<span className="user-text"><strong>{name}</strong><small>{line}</small></span><ChevronDown size={14} className="user-caret" aria-hidden="true"/>
    </button>
    {open&&<div className="user-menu" role="menu" aria-label="Account">
      <div className="user-menu-head">{orb(true)}<span><strong>{name}</strong><small>{line}</small><code>{subject}</code></span></div>
      <div className="user-menu-sep"/>
      <button type="button" role="menuitem" className="user-menu-item" onClick={()=>{setOpen(false);onHelp()}}><CircleHelp size={16} aria-hidden="true"/>Help &amp; guide</button>
      <button type="button" role="menuitem" className="user-menu-item exit" aria-label="Sign out" onClick={()=>{setOpen(false);onSignOut()}}><LogOut size={16} aria-hidden="true"/>Sign out</button>
      <p className="user-menu-foot"><ShieldCheck size={13} aria-hidden="true"/>Credential kept for this tab only</p>
    </div>}
  </div>}
function Shell(){
  const {identity,signOut}=useSession();
  const [open,setOpen]=useState(false);
  const [help,setHelp]=useState(false);
  const navigate=useNavigate();
  const {pathname}=useLocation();
  const auditor=identity!.role==='auditor';
  const root=auditor?'/auditor':'/client';
  const links=auditor
    ?[[root,'Overview',LayoutDashboard],[root+'/runs/new','New audit run',ClipboardCheck],[root+'/assistant','MCP assistant',MessageSquare]]
    :[[root,'Overview',LayoutDashboard],[root+'/business','Business records',Building2],[root+'/registers','Registers & disclosures',Files],[root+'/evidence-requests','Evidence inbox',FileSearch]];
  useEffect(()=>setOpen(false),[pathname]);
  const section=pathname.includes('/assistant')?'MCP assistant':pathname.includes('/runs/')?'Audit engagement':auditor?'Revenue audit':'Business operations';
  return <div className="app-shell top-nav-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="floating-bar">
      <div className="bar-side bar-left"><Brand/><span className="bar-role">{auditor?'Auditor':'Client'}</span></div>
      <nav id="workspace-navigation" className={'pill-nav '+(open?'open':'')} aria-label="Workspace navigation">
        {links.map(([to,title,Icon])=><NavLink end key={String(to)} to={String(to)} className={({isActive})=>'nav-item '+(isActive?'active':'')}><Icon size={15} aria-hidden="true"/><span>{String(title)}</span></NavLink>)}
      </nav>
      <div className="bar-side bar-right">
        <button type="button" className="icon-button nav-toggle" aria-label={open?'Close navigation':'Open navigation'} aria-controls="workspace-navigation" aria-expanded={open} onClick={()=>setOpen(o=>!o)}>{open?<X size={18}/>:<Menu size={18}/>}</button>
        <UserChip subject={identity!.subject} role={auditor?(identity!.human?'human':'auditor'):'client'} onHelp={()=>setHelp(true)} onSignOut={signOut}/>
      </div>
    </header>
    {open&&<button type="button" className="nav-scrim" aria-label="Close navigation" onClick={()=>setOpen(false)}/>}
    <div className="workspace">
      <div className="context-line" aria-label="Location"><span>{auditor?'Auditor workspace':'Client workspace'}</span><span className="slash">/</span><strong>{section}</strong></div>
      {help&&<Drawer title="Help" onClose={()=>setHelp(false)}><HelpContent role={auditor?'auditor':'client'} onShowGuide={()=>{setHelp(false);navigate(root)}}/></Drawer>}
      <main id="main" tabIndex={-1} key={identity!.subject+pathname}><Suspense fallback={<div className="skeleton-loader" role="status" aria-label="Loading"><div className="skeleton-row" style={{width:'70%'}}/><div className="skeleton-row" style={{width:'50%'}}/></div>}><Outlet/></Suspense></main>
      <footer className="workspace-footer"><span className="workspace-footer-message"><ShieldCheck size={14} aria-hidden="true"/>Evidence, not certainty. Unverified sources stay unverified; final conclusions need human review.</span><span>Local prototype · one company per instance</span></footer>
    </div>
  </div>
}
function Unauthorized(){const {identity}=useSession();return <div className="unauthorized"><Header eyebrow="ACCESS BOUNDARY" title="This workspace belongs to another role." description="Your credential does not grant access to these records."/><Link className="primary" to={identity?.role==='auditor'?'/auditor':'/client'}>Return to your workspace <ArrowUpRight size={16}/></Link></div>}
function Home(){const {identity}=useSession();const to=!identity?'/login':identity.role==='auditor'?'/auditor':'/client';return <Landing to={to}/>}
export function App(){return <Routes><Route path="/" element={<Home/>}/><Route path="/login" element={<Login/>}/><Route path="/unauthorized" element={<Unauthorized/>}/><Route element={<Guard role="client_employee"/>}><Route element={<Shell/>}><Route path="/client" element={<ClientDashboard/>}/><Route path="/client/business" element={<Business/>}/><Route path="/client/registers" element={<Registers/>}/><Route path="/client/evidence-requests" element={<Inbox/>}/><Route path="/client/evidence-requests/:requestId" element={<Inbox/>}/></Route></Route><Route element={<Guard role="auditor"/>}><Route element={<Shell/>}><Route path="/auditor" element={<AuditDashboard/>}/><Route path="/auditor/assistant" element={<AuditAssistant/>}/><Route path="/auditor/runs/new" element={<NewRun/>}/><Route path="/auditor/runs/:runId/*" element={<RunWorkspace/>}/><Route path="/auditor/findings/:findingId" element={<FindingDetail/>}/><Route path="/auditor/sales/:saleId" element={<SaleDetail/>}/></Route></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes>}
