// Design-system primitives added in the UI/UX audit (see docs/ui-audit/design-system.md).
import {ReactNode} from 'react'
import {Bot,Cpu,FileText,UserCheck,Inbox as InboxIcon} from 'lucide-react'

export type Provenance='automated'|'proposal'|'human'|'ai'
const PROVENANCE:Record<Provenance,{label:string;Icon:typeof Bot}>={
  automated:{label:'Automated check',Icon:Cpu},
  proposal:{label:'Proposal, not a decision',Icon:FileText},
  human:{label:'Human decision',Icon:UserCheck},
  ai:{label:'AI-generated guidance',Icon:Bot},
}
export function formatWhen(iso?:string){if(!iso)return '';const d=new Date(iso);return Number.isNaN(d.getTime())?iso:d.toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})}
/** Who or what produced a statement. Always icon + words; colour is secondary. */
export function ProvenanceTag({kind,actor,at,detail}:{kind:Provenance;actor?:string;at?:string;detail?:string}){
  const {label,Icon}=PROVENANCE[kind]
  return <span className={'prov prov-'+kind}><Icon size={13} aria-hidden="true"/><span className="prov-label">{label}</span>{detail&&<span className="prov-detail">{detail}</span>}{actor&&<span className="prov-actor">by {actor}</span>}{at&&<time className="prov-time" dateTime={at}>{formatWhen(at)}</time>}</span>
}
export function EmptyState({title,children,action}:{title:string;children?:ReactNode;action?:ReactNode}){
  return <div className="empty-state" role="status"><InboxIcon size={22} aria-hidden="true"/><strong>{title}</strong>{children&&<p>{children}</p>}{action}</div>
}
/** Progress bar with an accessible value; text carries the meaning, the bar is secondary. */
export function ProgressBar({value,max,label}:{value:number;max:number;label:string}){
  const pct=max?Math.round(value/max*100):0
  return <div className="progress"><div className="progress-text"><span>{label}</span><b>{value} of {max}</b></div><div className="progress-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}><i style={{width:pct+'%'}}/></div></div>
}
