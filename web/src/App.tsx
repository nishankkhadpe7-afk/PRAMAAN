import {useState} from 'react'
import {Link,NavLink,Navigate,Outlet,Route,Routes,useLocation,useNavigate} from 'react-router-dom'
import {ArrowRight,ArrowUpRight,BookOpen,Building2,ClipboardCheck,Eye,EyeOff,FileSearch,Files,LayoutDashboard,LogOut,Menu,MessageSquare,ShieldCheck,Workflow,X} from 'lucide-react'
import {useSession} from './session'
import {Badge,Field,Header,Mutation} from './components'
import {ClientDashboard,Business,Registers,Inbox} from './client'
import {AuditDashboard,AuditAssistant,NewRun,RunWorkspace,FindingDetail,SaleDetail} from './auditor'

export function Login(){
  const {signIn,expired}=useSession();
  const [token,setToken]=useState('');
  const [showToken,setShowToken]=useState(false);
  const navigate=useNavigate();

  const handleQuickLogin = (role: 'auditor' | 'client' | 'human') => {
    const cred = role === 'auditor' 
      ? 'Vs7pzyh3hif_MR3w2dZsI1tSrbsrWZ6k9vF2kcbAdao'
      : role === 'human'
      ? 'NimleqgQ-KV-18NNQqN_R0xF3iEYxuCNnrTKh1BdPB8'
      : 'sMEwOWpcRuSLrsrAK_FYtfUnHkpoCMhjW03s5MbY39I';
    setToken(cred);
  };

  return <div className="login">
    <div className="login-brand"><Brand/></div>
    <div className="login-layout">
      <section className="login-intro">
        <div className="eyebrow">FORENSIC ASSURANCE PLATFORM</div>
        <h1>Every sale.<br/>A traceable story.</h1>
        <p>From the original sales register to the immutable workpaper package. Investigate the cryptographic evidence, preserve its mathematical limits, and anchor conclusions in qualified human judgment.</p>
        <div className="login-principles">
          <div><Workflow/><span>One Unified Lifecycle<small>Order, dispatch, invoice and balanced journal connected deterministically.</small></span></div>
          <div><FileSearch/><span>Evidence with Full Provenance<small>Cryptographic SHA-256 hash digests before subjective assurance.</small></span></div>
          <div><ShieldCheck/><span>Cryptographic Chain of Custody<small>Append-only audit trail and tamper-evident back-pointer verification.</small></span></div>
        </div>
      </section>
      <section className="login-card">
        <div className="eyebrow">SECURE WORKSPACE AUTHENTICATION</div>
        <h2>Sign in to Pramaan</h2>
        <p>Enter a provisioned credential or launch directly with role-governed demo identities.</p>
        {expired&&<div role="alert" className="notice notice-error">Your session ended. Use a valid credential to continue.</div>}
        <Mutation>{(run,busy)=><form onSubmit={e=>{e.preventDefault();void run(async()=>{const caller=await signIn(token.trim());setToken('');navigate(caller.role==='auditor'?'/auditor':'/client',{replace:true})})}}>
          <div className="field">
            <label htmlFor="credential-input"><span>Access credential</span></label>
            <div className="input-wrapper">
              <input id="credential-input" type={showToken?'text':'password'} name="credential" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)} required placeholder="Paste your provisioned token"/>
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
        <div className="quick-login-pills">
          <span style={{fontSize:'12px',color:'var(--subtle)',alignSelf:'center'}}>Demo:</span>
          <button type="button" onClick={()=>handleQuickLogin('auditor')}>Auditor (P1-P5 Full)</button>
          <button type="button" onClick={()=>handleQuickLogin('human')}>Human Review Authority</button>
          <button type="button" onClick={()=>handleQuickLogin('client')}>Client (Registers/Sales)</button>
        </div>
        <div className="login-note">
          <ShieldCheck size={16}/>
          <p>Zero-trust MCP security layer active. Credentials held in volatile client memory and cleared immediately on sign-out.</p>
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
      <span>Single-company SQLite forensic engine · SHA-256 Merkle Provenance</span>
    </footer>
  </div>
}
function Brand(){return <Link className="brand" to="/"><span className="brand-mark"><i/><i/><i/></span><span>Pramaan<small>REVENUE AUDIT</small></span></Link>}
export function Guard({role}:{role:'client_employee'|'auditor'}){const {identity}=useSession();return !identity?<Navigate to="/login" replace/>:identity.role!==role?<Navigate to="/unauthorized" replace/>:<Outlet/>}
function Shell(){const {identity,signOut}=useSession();const [open,setOpen]=useState(false);const {pathname}=useLocation();const auditor=identity!.role==='auditor';const root=auditor?'/auditor':'/client';const links=auditor?[[root,'Overview',LayoutDashboard],[root+'/runs/new','New audit run',ClipboardCheck],[root+'/assistant','MCP assistant',MessageSquare]]:[[root,'Overview',LayoutDashboard],[root+'/business','Business records',Building2],[root+'/registers','Registers & disclosures',Files],[root+'/evidence-requests','Evidence inbox',FileSearch]];return <div className="app-shell"><a className="skip-link" href="#main">Skip to content</a><aside className={'sidebar '+(open?'open':'')}><Brand/><div className="workspace-label"><span className="workspace-icon">{auditor?<FileSearch size={16}/>:<Building2 size={16}/>}</span><div>{auditor?'Auditor workspace':'Client workspace'}<small>Local demonstration</small></div><button className="icon-button mobile" aria-label="Close navigation" onClick={()=>setOpen(false)}><X size={18}/></button></div><div className="nav-caption">WORKSPACE</div><nav>{links.map(([to,title,Icon])=><NavLink end key={String(to)} to={String(to)} onClick={()=>setOpen(false)} className={({isActive})=>'nav-item '+(isActive?'active':'')}><Icon size={17}/>{String(title)}</NavLink>)}</nav><div className="sidebar-bottom"><div className="scope-card"><ShieldCheck size={18}/><strong>Evidence, not certainty.</strong><p>Unverified sources stay unverified. Final conclusions require human review.</p></div><div className="profile"><span className="avatar">{identity!.subject.slice(0,2).toUpperCase()}</span><div><strong>{identity!.subject}</strong><small>{identity!.human?'Human review enabled':auditor?'Auditor · proposals only':'Client employee'}</small></div><button className="icon-button" aria-label="Sign out" onClick={signOut}><LogOut size={16}/></button></div></div></aside>{open&&<button className="nav-scrim" aria-label="Close navigation" onClick={()=>setOpen(false)}/>}<div className="workspace"><div className="topbar"><div><button className="icon-button mobile" aria-label="Open navigation" onClick={()=>setOpen(true)}><Menu size={19}/></button><span>Workspace</span><span className="slash">/</span><strong>{pathname.includes('/assistant')?'MCP assistant':pathname.includes('/runs/')?'Audit engagement':auditor?'Revenue audit':'Business operations'}</strong></div><span className="topbar-user"><span className="avatar" style={{width:'24px',height:'24px',fontSize:'12px'}}>{identity!.subject.slice(0,2).toUpperCase()}</span>{identity!.subject}</span></div><main id="main" key={identity!.subject+pathname}><Outlet/></main><footer className="workspace-footer"><BookOpen size={14}/> Traceable records. Qualified human judgment. <span>Prototype · one company per instance</span></footer></div></div>}
function Unauthorized(){const {identity}=useSession();return <div className="unauthorized"><Header eyebrow="ACCESS BOUNDARY" title="This workspace belongs to another role." description="Your credential does not grant access to these records."/><Link className="primary" to={identity?.role==='auditor'?'/auditor':'/client'}>Return to your workspace <ArrowUpRight size={16}/></Link></div>}
function Home(){const {identity}=useSession();return <Navigate replace to={!identity?'/login':identity.role==='auditor'?'/auditor':'/client'}/>}
export function App(){return <Routes><Route path="/" element={<Home/>}/><Route path="/login" element={<Login/>}/><Route path="/unauthorized" element={<Unauthorized/>}/><Route element={<Guard role="client_employee"/>}><Route element={<Shell/>}><Route path="/client" element={<ClientDashboard/>}/><Route path="/client/business" element={<Business/>}/><Route path="/client/registers" element={<Registers/>}/><Route path="/client/evidence-requests" element={<Inbox/>}/><Route path="/client/evidence-requests/:requestId" element={<Inbox/>}/></Route></Route><Route element={<Guard role="auditor"/>}><Route element={<Shell/>}><Route path="/auditor" element={<AuditDashboard/>}/><Route path="/auditor/assistant" element={<AuditAssistant/>}/><Route path="/auditor/runs/new" element={<NewRun/>}/><Route path="/auditor/runs/:runId/*" element={<RunWorkspace/>}/><Route path="/auditor/findings/:findingId" element={<FindingDetail/>}/><Route path="/auditor/sales/:saleId" element={<SaleDetail/>}/></Route></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes>}
