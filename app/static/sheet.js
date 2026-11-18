'use strict';
const sheet={pending:false};const message=document.getElementById('message');
async function recount(input){if(sheet.pending)return;sheet.pending=true;message.textContent='工时重算中…';try{const response=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});const data=await response.json();if(!response.ok)throw new Error(data.message);location.reload();}catch(error){message.textContent=error.message+'，请修正打卡';}finally{sheet.pending=false;}}
const recountButton=document.getElementById('recount');
recountButton.addEventListener('click',async()=>{
  const id=recountButton.dataset.id;
  if(!id)return recount({sample:'dirty.csv'});
  if(sheet.pending)return;sheet.pending=true;message.textContent='按当前批次重算…';
  try{const response=await fetch('/api/runs/'+id+'/rerun',{method:'POST'});const data=await response.json();
    if(!response.ok)throw Error(data.message);
    message.textContent='重算与封存一致 / 版本 '+data.review_version;}
  catch(error){message.textContent=error.message+'，已保留当前版本';}
  finally{sheet.pending=false;}
});
const file=document.getElementById('clock-file');if(file)file.addEventListener('submit',event=>{event.preventDefault();const values=new FormData(file);const csv=values.get('csv');recount(csv?{csv}:{sample:values.get('sample')});});
const check=document.getElementById('check');if(check)check.addEventListener('click',async()=>{try{const response=await fetch('/api/runs/'+check.dataset.id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:Number(check.dataset.version),decision:'通过'})});const data=await response.json();if(!response.ok)throw Error(data.message);check.dataset.version=data.review_version;message.textContent='工资复核通过 / '+data.review_version;}catch(error){message.textContent=error.message;}});
const paper=document.getElementById('paper');if(paper)paper.addEventListener('click',()=>window.print());
const correction=document.getElementById('correction');if(correction)correction.addEventListener('submit',async event=>{
  event.preventDefault();const button=correction.querySelector('button');const values=new FormData(correction);
  const offset=Number(values.get('offset_minutes'));
  const ticket={id:values.get('id'),device:values.get('device'),offset_minutes:offset,
    window_start:values.get('window_start'),window_end:values.get('window_end'),reason:values.get('reason'),
    appeals:String(values.get('appeals')||'').split(',').map(s=>s.trim()).filter(Boolean)};
  button.disabled=true;message.textContent='重算工资并封存…';
  try{const response=await fetch('/api/runs/'+button.dataset.id+'/corrections',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({version:Number(button.dataset.version),correction_policy:values.get('policy'),clock_tickets:[ticket]})});
    const data=await response.json();
    if(!response.ok)throw Error(data.message);
    message.textContent='已切换修正版 / 版本 '+data.review_version;location.reload();
  }catch(error){message.textContent=error.message+'（已保留旧版）';}
  finally{button.disabled=false;}
});
document.querySelectorAll('td[tabindex]').forEach(cell=>cell.addEventListener('focus',()=>message.textContent=cell.textContent.trim()));
