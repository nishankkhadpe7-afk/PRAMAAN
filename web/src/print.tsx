// Security-print ornaments: guilloche rosette, thread, colour-shift ink, microtext, stamp.
import {ReactNode,useMemo} from 'react'
export function Guilloche({size=180,lines=28,className=''}:{size?:number;lines?:number;className?:string}){
  const items=useMemo(()=>Array.from({length:lines},(_,i)=>i*180/lines),[lines])
  return <svg className={'guilloche '+className} width={size} height={size} viewBox="-100 -100 200 200" aria-hidden="true">
    {items.map(a=><ellipse key={a} rx="92" ry="30" transform={`rotate(${a})`} fill="none" stroke="currentColor" strokeWidth=".6"/>)}
    {[18,34,52].map(r=><circle key={r} r={r} fill="none" stroke="currentColor" strokeWidth=".5"/>)}
  </svg>
}
export const Microtext=({text='PRAMAAN GENUINE SALE VERIFIED AGAINST ITS RECORD',className=''}:{text?:string;className?:string})=>
  <div className={'microtext '+className} aria-hidden="true">{Array.from({length:14},()=>text).join(' · ')}</div>
export const Thread=({className=''}:{className?:string})=><i className={'thread '+className} aria-hidden="true"/>
export const ShiftInk=({children}:{children:ReactNode})=><span className="shift-ink">{children}</span>
export const Stamp=({children,tone='pass'}:{children:ReactNode;tone?:'pass'|'fail'|'wait'})=><span className={'stamp stamp-'+tone}>{children}</span>
