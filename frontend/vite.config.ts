import { defineConfig, loadEnv } from 'vite';
export default defineConfig(({mode})=>{
  const {PAPERMIND_VITE_API_URL} = loadEnv(mode,'.','PAPERMIND_VITE_');
  return {server:{host:'127.0.0.1',port:5173,strictPort:true,proxy:{'/api':{
    target:PAPERMIND_VITE_API_URL||'http://127.0.0.1:8765',rewrite:p=>p.replace(/^\/api/,''),
  }}}};
});
