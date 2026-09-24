const { chromium } = require('playwright');
const fs=require('fs');
(async()=>{
  const dir=__dirname; const mode=process.argv[2]||'preview';
  const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1920,height:1080}});
  p.on('console',m=>console.log('console:',m.text())); p.on('pageerror',e=>console.log('ERR',e.message));
  await p.goto('file://'+dir+'/index.html'); await p.evaluate(()=>window.ready);
  if(mode==='preview'){
    const ts=process.argv.slice(3).map(Number);
    for(const t of ts){await p.evaluate(t=>render(t),t);await p.screenshot({path:`${dir}/prev/p_${t}.jpg`,type:'jpeg',quality:80});}
  } else {
    const fps=30,D=await p.evaluate(()=>DURATION),N=Math.round(D*fps);
    fs.mkdirSync(dir+'/frames',{recursive:true});
    for(let i=0;i<N;i++){await p.evaluate(t=>render(t),i/fps);await p.screenshot({path:`${dir}/frames/f${String(i).padStart(5,'0')}.jpg`,type:'jpeg',quality:94});if(i%150==0)console.log(i,'/',N);}
  }
  await b.close();
})();
