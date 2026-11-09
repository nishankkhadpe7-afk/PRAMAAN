import {createContext,useContext,useEffect,useMemo,useState,ReactNode} from 'react'
import {API,ApiError,makeApi,setUploadLimit} from './api'
export type Identity={subject:string;role:'client_employee'|'auditor';human:boolean;max_upload_bytes?:number}
type Session={identity:Identity|null;api:API|null;expired:boolean;restoring:boolean;signIn:(token:string)=>Promise<Identity>;signOut:()=>void}
const Context=createContext<Session>(null!)
// F5: the credential survives a page reload but stays scoped to this browser tab
// (sessionStorage): closing the tab, signing out or a 401 clears it. It is never put in a URL,
// cookie or localStorage, and it is re-validated with the backend before it is used.
const KEY='pramaan.session'
function stored(){try{return window.sessionStorage.getItem(KEY)||''}catch{return ''}}
function remember(token:string){try{token?window.sessionStorage.setItem(KEY,token):window.sessionStorage.removeItem(KEY)}catch{/* storage unavailable: session stays in memory */}}
export function SessionProvider({children}:{children:ReactNode}){
 const [token,setToken]=useState(''); const [identity,setIdentity]=useState<Identity|null>(null);const [expired,setExpired]=useState(false);const [restoring,setRestoring]=useState(()=>!!stored())
 const signOut=()=>{remember('');setToken('');setIdentity(null)}
 const api=useMemo(()=>token?makeApi(token,()=>{signOut();setExpired(true)}):null,[token])
 async function signIn(value:string){let verified:Identity;try{verified=await makeApi(value).json<Identity>('/p4/identity')}catch(error){if(error instanceof ApiError&&error.status===401)throw new Error('This credential was not accepted. It may be mistyped, expired or revoked; generate a new one with the launcher and paste it again.');throw error}setUploadLimit(verified.max_upload_bytes);remember(value);setExpired(false);setToken(value);setIdentity(verified);return verified}
 useEffect(()=>{const saved=stored();if(!saved){setRestoring(false);return}let active=true
  makeApi(saved).json<Identity>('/p4/identity').then(verified=>{if(active){setUploadLimit(verified.max_upload_bytes);setToken(saved);setIdentity(verified)}}).catch(error=>{if(active){remember('');if(error instanceof ApiError&&error.status===401)setExpired(true)}}).finally(()=>{if(active)setRestoring(false)})
  return()=>{active=false}},[])
 return <Context.Provider value={{identity,api,expired,restoring,signIn,signOut}}>{children}</Context.Provider>
}
export const useSession=()=>useContext(Context)
