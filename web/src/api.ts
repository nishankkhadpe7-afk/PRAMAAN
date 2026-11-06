export type FieldError={field:string;message:string}
const STATUS_MESSAGES:Record<number,string>={401:'Your credential has expired or been revoked. Sign in again.',403:'This identity is not permitted to perform this action.',409:'The operation conflicts with current state. Refresh and try again.',413:'The upload is larger than the configured limit.',422:'Check the input format and required fields.',402:'The AI provider account has no credits left. Add billing credit with the provider (or switch provider in .env), then retry.',429:'The AI provider is rate-limited. Wait briefly, then retry.',503:'The AI provider is temporarily unavailable. Retry shortly.'}
const EXPLAINED=new Set([400,404,409,413,422])
// The backend returns {code, detail, fields?}; 4xx details are authored, client-safe explanations (H4/F4).
export class ApiError extends Error {
  constructor(public status:number, public retryAfter?:number, public detail?:string, public code?:string, public fields:FieldError[]=[]) {
    super(EXPLAINED.has(status)&&detail?detail:STATUS_MESSAGES[status]??'The service could not complete this request.')
  }
  fieldMessage(name:string){return this.fields.find(f=>f.field===name||f.field.endsWith('.'+name))?.message}
}
async function errorFrom(res:Response){let body:any={};try{body=await res.json()}catch{/* non-JSON error body */}return new ApiError(res.status,Number(res.headers.get('Retry-After'))||undefined,typeof body.detail==='string'?body.detail:undefined,typeof body.code==='string'?body.code:undefined,Array.isArray(body.fields)?body.fields:[])}
export function makeApi(token:string, onExpired:()=>void = ()=>{}) {
  async function response(path:string, method='GET', body?:unknown, signal?:AbortSignal) {
    if(!path.startsWith('/') || path.startsWith('//')) throw new Error('Invalid API path')
    const res=await fetch('/api'+path,{method,headers:{Authorization:'Bearer '+token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),signal,cache:'no-store',credentials:'omit'})
    if(!res.ok){if(res.status===401)onExpired();throw await errorFrom(res)} return res
  }
  return {json:async<T=any>(path:string,method='GET',body?:unknown,signal?:AbortSignal):Promise<T> => (await response(path,method,body,signal)).json(),
    download:async(path:string,name:string)=>{const blob=await(await response(path)).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}
}
export type API=ReturnType<typeof makeApi>
export async function fileBase64(file:File){const bytes=new Uint8Array(await file.arrayBuffer());let value='';for(let start=0;start<bytes.length;start+=8192)value+=String.fromCharCode(...bytes.subarray(start,start+8192));return btoa(value)}
export const id=(value:string)=>encodeURIComponent(value)

export function localToday(){const now=new Date();return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10)}
export function currentFiscalPeriod(){const now=new Date();return 'FY'+String(now.getFullYear()+(now.getMonth()>=3?1:0)).slice(-2)}
