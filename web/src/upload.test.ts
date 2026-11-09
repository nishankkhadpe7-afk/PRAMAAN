import {describe,it,expect,afterEach} from 'vitest'
import {checkUploadSize,fileBase64,setUploadLimit} from './api'

describe('upload size limit',()=>{
  afterEach(()=>setUploadLimit(undefined))
  it('refuses a file over the server limit before reading or sending it',async()=>{
    setUploadLimit(10*1024*1024)
    const big=new File([new Uint8Array(12_000_000)],'register.csv')
    expect(()=>checkUploadSize(big)).toThrow(/“register.csv” is 11\.4 MB, which is over the 10 MB upload limit/)
    await expect(fileBase64(big)).rejects.toThrow(/upload limit/)
  })
  it('accepts files within the limit, and any size when the limit is unknown',async()=>{
    setUploadLimit(1024)
    expect(()=>checkUploadSize(new File(['abc'],'a.csv'))).not.toThrow()
    setUploadLimit(undefined)
    expect(()=>checkUploadSize(new File([new Uint8Array(5000)],'b.csv'))).not.toThrow()
  })
})
