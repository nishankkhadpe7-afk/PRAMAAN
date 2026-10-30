import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
export default defineConfig(({mode})=>({plugins:[react()],server:{port:5173,strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:'+(Number(loadEnv(mode,'.','PRAMAAN_E2E_').PRAMAAN_E2E_API_PORT)||8000),changeOrigin:false,rewrite:path=>path.replace(/^\/api/,'')}}},preview:{port:4173,strictPort:true},test:{include:['src/**/*.test.ts','src/**/*.test.tsx'],environment:'jsdom',setupFiles:['./src/test-setup.ts'],restoreMocks:true}}))
