import {createContext,useContext,useMemo,useState,ReactNode} from 'react'
import {API,makeApi} from './api'
export type Identity={subject:string;role:'client_employee'|'auditor';human:boolean}
type Session={identity:Identity|null;api:API|null;expired:boolean;signIn:(token:string)=>Promise<Identity>;signOut:()=>void}
const Context=createContext<Session>(null!)
export function SessionProvider({children}:{children:ReactNode}){
 const [token,setToken]=useState(''); const [identity,setIdentity]=useState<Identity|null>(null);const [expired,setExpired]=useState(false)
 const signOut=()=>{setToken('');setIdentity(null)}
 const api=useMemo(()=>token?makeApi(token,()=>{signOut();setExpired(true)}):null,[token])
 async function signIn(value:string){const verified=await makeApi(value).json<Identity>('/p4/identity');setExpired(false);setToken(value);setIdentity(verified);return verified}
 return <Context.Provider value={{identity,api,expired,signIn,signOut}}>{children}</Context.Provider>
}
export const useSession=()=>useContext(Context)
