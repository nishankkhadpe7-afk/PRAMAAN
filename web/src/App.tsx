import {Suspense,lazy,useEffect,useState} from 'react'
import {Link,NavLink,Navigate,Outlet,Route,Routes,useLocation,useNavigate} from 'react-router-dom'
import {ArrowRight,ArrowUpRight,BookOpen,Building2,ClipboardCheck,Eye,EyeOff,FileSearch,Files,LayoutDashboard,LogOut,Menu,MessageSquare,ShieldCheck,Workflow,X} from 'lucide-react'
import {useSession} from './session'
import {Header,Mutation} from './components'
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
    <div className="login-brand"><Brand/><Link className="login-back" to="/">← Back to home</Link></div>
    <div className="login-layout">
      <section className="login-intro">
        <div className="eyebrow">FORENSIC ASSURANCE PLATFORM</div>
        <h1>Every sale.<br/>A traceable story.</h1>
        <p>Trace every recorded sale from the client's original register to a frozen, reproducible workpaper. The system flags what does not reconcile; a qualified reviewer decides what it means.</p>
        <div className="login-principles">
          <div><Workflow/><span>One Unified Lifecycle<small>Order, dispatch, invoice and journal linked for each sale.</small></span></div>
          <div><FileSearch/><span>Evidence with Full Provenance<small>Every file is fingerprinted (SHA-256) when it arrives, so later changes are detectable.</small></span></div>
          <div><ShieldCheck/><span>Cryptographic Chain of Custody<small>An append-only trail where each entry is linked to the one before it.</small></span></div>
        </div>
      </section>
      <section className="login-card">
        <div className="eyebrow">SECURE WORKSPACE AUTHENTICATION</div>
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
        <div className="scope">
          <span>Client Enterprise</span>
          <span>Lead Forensic Auditor</span>
          <span>Human Review Authority</span>
        </div>
      </section>
    </div>
    <footer>
      <span>प्रमाण · PRAMAAN Trust Architecture</span>
      <span>Single-company SQLite forensic engine · SHA-256 hash-linked provenance</span>
    </footer>
  </div>
}
function Brand(){return <Link className="brand" to="/" aria-label="Pramaan home"><span className="brand-mark"><i/><i/><i/></span><span>Pramaan<small>REVENUE AUDIT</small></span></Link>}
export function Guard({role}:{role:'client_employee'|'auditor'}){const {identity,restoring}=useSession();return restoring?<div className="skeleton-loader" role="status" aria-label="Restoring session"/>:!identity?<Navigate to="/login" replace/>:identity.role!==role?<Navigate to="/unauthorized" replace/>:<Outlet/>}
function Shell(){
  const {identity,signOut}=useSession();
  const [open,setOpen]=useState(false);
  const {pathname}=useLocation();
  const auditor=identity!.role==='auditor';
  const root=auditor?'/auditor':'/client';
  const links=auditor
    ?[[root,'Overview',LayoutDashboard],[root+'/runs/new','New audit run',ClipboardCheck],[root+'/assistant','MCP assistant',MessageSquare]]
    :[[root,'Overview',LayoutDashboard],[root+'/business','Business records',Building2],[root+'/registers','Registers & disclosures',Files],[root+'/evidence-requests','Evidence inbox',FileSearch]];
  useEffect(()=>setOpen(false),[pathname]);
  const section=pathname.includes('/assistant')?'MCP assistant':pathname.includes('/runs/')?'Audit engagement':auditor?'Revenue audit':'Business operations';
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    <aside id="workspace-navigation" className={'sidebar '+(open?'open':'')} aria-label="Workspace navigation">
      <Brand/>
      <div className="workspace-label">
        <span className="workspace-icon">{auditor?<FileSearch size={16}/>:<Building2 size={16}/>}</span>
        <div>{auditor?'Auditor workspace':'Client workspace'}<small>Local demonstration</small></div>
        <button type="button" className="icon-button mobile" aria-label="Close navigation" onClick={()=>setOpen(false)}><X size={18}/></button>
      </div>
      <div className="nav-caption">WORKSPACE</div>
      <nav>{links.map(([to,title,Icon])=><NavLink end key={String(to)} to={String(to)} className={({isActive})=>'nav-item '+(isActive?'active':'')}><Icon size={17}/>{String(title)}</NavLink>)}</nav>
      <div className="sidebar-bottom">
        <div className="scope-card"><ShieldCheck size={18}/><strong>Evidence, not certainty.</strong><p>Unverified sources stay unverified. Final conclusions require human review.</p></div>
        <div className="profile"><span className="avatar">{identity!.subject.slice(0,2).toUpperCase()}</span><div><strong>{identity!.subject}</strong><small>{identity!.human?'Human review enabled':auditor?'Auditor · proposals only':'Client employee'}</small></div><button type="button" className="icon-button" aria-label="Sign out" onClick={signOut}><LogOut size={16}/></button></div>
      </div>
    </aside>
    {open&&<button type="button" className="nav-scrim" aria-label="Close navigation" onClick={()=>setOpen(false)}/>}
    <div className="workspace">
      <div className="topbar">
        <div className="topbar-context"><button type="button" className="icon-button mobile" aria-label="Open navigation" aria-controls="workspace-navigation" aria-expanded={open} onClick={()=>setOpen(true)}><Menu size={19}/></button><span>Workspace</span><span className="slash">/</span><strong>{section}</strong></div>
        <div className="topbar-user" title={identity!.subject}><span className="avatar topbar-avatar">{identity!.subject.slice(0,2).toUpperCase()}</span><span className="topbar-user-name">{identity!.subject}</span></div>
      </div>
      <main id="main" tabIndex={-1} key={identity!.subject+pathname}><Suspense fallback={<div className="skeleton-loader" role="status" aria-label="Loading"><div className="skeleton-row" style={{width:'70%'}}/><div className="skeleton-row" style={{width:'50%'}}/></div>}><Outlet/></Suspense></main>
      <footer className="workspace-footer"><span className="workspace-footer-message"><BookOpen size={14}/>Traceable records. Qualified human judgment.</span><span>Prototype · one company per instance</span></footer>
    </div>
  </div>
}
function Unauthorized(){const {identity}=useSession();return <div className="unauthorized"><Header eyebrow="ACCESS BOUNDARY" title="This workspace belongs to another role." description="Your credential does not grant access to these records."/><Link className="primary" to={identity?.role==='auditor'?'/auditor':'/client'}>Return to your workspace <ArrowUpRight size={16}/></Link></div>}
function Home(){const {identity}=useSession();const to=!identity?'/login':identity.role==='auditor'?'/auditor':'/client';return <Landing to={to}/>}
export function App(){return <Routes><Route path="/" element={<Home/>}/><Route path="/login" element={<Login/>}/><Route path="/unauthorized" element={<Unauthorized/>}/><Route element={<Guard role="client_employee"/>}><Route element={<Shell/>}><Route path="/client" element={<ClientDashboard/>}/><Route path="/client/business" element={<Business/>}/><Route path="/client/registers" element={<Registers/>}/><Route path="/client/evidence-requests" element={<Inbox/>}/><Route path="/client/evidence-requests/:requestId" element={<Inbox/>}/></Route></Route><Route element={<Guard role="auditor"/>}><Route element={<Shell/>}><Route path="/auditor" element={<AuditDashboard/>}/><Route path="/auditor/assistant" element={<AuditAssistant/>}/><Route path="/auditor/runs/new" element={<NewRun/>}/><Route path="/auditor/runs/:runId/*" element={<RunWorkspace/>}/><Route path="/auditor/findings/:findingId" element={<FindingDetail/>}/><Route path="/auditor/sales/:saleId" element={<SaleDetail/>}/></Route></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes>}
