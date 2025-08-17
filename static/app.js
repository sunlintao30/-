let connData = [], connSortKey='proc', connSortAsc=true, stopFlag=false;

function human(n){
  if (n < 1024) return n + ' B';
  if (n < 1024*1024) return (n/1024).toFixed(2) + ' KB';
  if (n < 1024*1024*1024) return (n/1024/1024).toFixed(2) + ' MB';
  return (n/1024/1024/1024).toFixed(2) + ' GB';
}
function humanRate(n){
  if (n < 1024) return n.toFixed(0) + ' B/s';
  if (n < 1024*1024) return (n/1024).toFixed(2) + ' KB/s';
  if (n < 1024*1024*1024) return (n/1024/1024).toFixed(2) + ' MB/s';
  return (n/1024/1024/1024).toFixed(2) + ' GB/s';
}
function toast(msg){ const t=document.getElementById('toast'); if(!t) return; t.textContent=msg; t.style.display='block'; setTimeout(()=>t.style.display='none', 1500); }
function showErr(msg){ let e=document.getElementById('err'); if(!e) return; e.textContent=msg; e.style.display='block'; }
function hideErr(){ let e=document.getElementById('err'); if(!e) return; e.style.display='none'; }
function attachLabels(){ document.querySelectorAll('button').forEach(b=>{ if(!b.getAttribute('data-label')) b.setAttribute('data-label', b.textContent); }); }
function disable(btn, yes=true){ if(!btn) return; btn.disabled=yes; btn.textContent = yes ? (btn.getAttribute('data-label')+'…') : btn.getAttribute('data-label'); }

async function loadAll(){
  hideErr();
  try{
    let res = await fetch('/api/ports', {credentials:'include'}); if(!res.ok) throw 0;
    let data = await res.json();
    let pre = document.getElementById('ports'); if(pre) pre.innerText = data.rules.join('\n');
  }catch(e){ showErr('获取 UFW 规则失败'); }

  try{
    let wlres = await fetch('/api/whitelist', {credentials:'include'}); if(!wlres.ok) throw 0;
    let wldata = await wlres.json();
    let wl = document.getElementById('wl'); if(wl){ wl.innerHTML='';
      if(!wldata.whelist && (!wldata.whitelist || wldata.whitelist.length===0)){
        wl.innerHTML = '<li class="muted">（当前白名单为空）</li>';
      }else{
        (wldata.whitelist||[]).forEach(item=>{
          let li=document.createElement('li');
          li.innerHTML = `<div><span class="flag">${item.flag||''}</span><span class="mono">${item.ip}</span>
            <div class="muted">本地：${item.local}　在线：${item.online}</div></div>
            <div><button type="button" onclick="delWL('${item.ip}')">删除</button></div>`;
          wl.appendChild(li);
        });
      }
    }
  }catch(e){ showErr('加载白名单失败'); }

  try{
    let t = await (await fetch('/api/traffic', {credentials:'include'})).json();
    document.getElementById('acc').innerText = human(t.acc_rx) + " ↓ / " + human(t.acc_tx) + " ↑";
    document.getElementById('speed').innerText = humanRate(t.rx_rate) + " ↓ / " + humanRate(t.tx_rate) + " ↑";
    document.getElementById('ifstat').innerText = t.ifaces.map(x=>`${x.iface}: ${human(x.rx)} ↓ / ${human(x.tx)} ↑`).join('\n');
  }catch(e){ showErr('获取流量信息失败'); }

  try{
    let c = await (await fetch('/api/connections', {credentials:'include'})).json();
    connData = c.connections||[]; renderConn();
  }catch(e){ showErr('获取连接信息失败'); }
}
function sortBy(k){ if (connSortKey===k) connSortAsc=!connSortAsc; else {connSortKey=k; connSortAsc=true;} renderConn(); }
function renderConn(){
  let tbody=document.getElementById('connbody'); if(!tbody) return;
  let data=connData.slice();
  data.sort((a,b)=>{
    let A=a[connSortKey]||'', B=b[connSortKey]||'';
    if (typeof A === 'number' && typeof B === 'number') return (connSortAsc?A-B:B-A);
    return (connSortAsc? (''+A).localeCompare(''+B):( ''+B).localeCompare(''+A));
  });
  tbody.innerHTML=data.map(x=>`<tr>
    <td>${x.proc||''}</td><td>${x.pid||''}</td>
    <td class="mono">${x.laddr||''}</td><td class="mono">${x.raddr||''}</td>
    <td>${x.status||''}</td>
    <td>${x.flag?'<span class="flag">'+x.flag+'</span> ':''}<div>${x.local||''}</div><div class="muted">${x.online||''}</div></td>
  </tr>`).join('');
}

async function strictify(){
  const btn=document.getElementById('strictBtn'); disable(btn,true);
  try{
    let res = await fetch('/api/ufw/strictify', {method:'POST', credentials:'include'});
    let js = await res.json();
    toast(`已删除 Anywhere 放行 ${js.deleted_anywhere} 条，面板端口 ${js.panel_port} 始终开放`);
    await loadAll();
  }catch(e){ showErr('严格化失败'); }
  finally{ disable(btn,false); }
}

async function savePanelPort(){
  const p = parseInt(document.getElementById('panelPort').value||'0',10);
  if(!(p>=1 && p<=65535)){ toast('端口不合法'); return; }
  const form = new FormData(); form.append('port', String(p));
  try{
    const res = await fetch('/api/panel/set', {method:'POST', credentials:'include', body: form});
    const js = await res.json();
    if(js.status==='ok'){ toast('已保存端口，服务将自动重启到 '+p); }
    else{ showErr(js.error || '保存失败'); }
  }catch(e){ showErr('保存失败'); }
}

async function openPort(){ 
  const btn = document.getElementById('btnOpenPort'); disable(btn,true);
  try{
    let p=document.getElementById('port').value.trim(); if(!p) {toast('请输入端口'); return;}
    let r = await fetch('/api/open/'+p,{method:'POST',credentials:'include'});
    if(!r.ok) throw 0;
    toast('已对白名单放行端口 '+p); loadAll();
  }catch(e){ showErr('放行端口失败'); }
  finally{ disable(btn,false); }
}
async function allowIP(){ const btn=document.getElementById('btnAllowIP'); disable(btn,true);
  try{ let ip=document.getElementById('ip').value.trim(); if(!ip) {toast('请输入IP'); return;}
    let r=await fetch('/api/whitelist/'+ip,{method:'POST',credentials:'include'}); if(!r.ok) throw 0; toast('已加入白名单'); loadAll();
  }catch(e){ showErr('加入白名单失败'); } finally{ disable(btn,false); } }
async function blockIP(){ const btn=document.getElementById('btnBlockIP'); disable(btn,true);
  try{ let ip=document.getElementById('ip').value.trim(); if(!ip) {toast('请输入IP'); return;}
    let r=await fetch('/api/block_ip/'+ip,{method:'POST',credentials:'include'}); if(!r.ok) throw 0; toast('已封禁IP'); loadAll();
  }catch(e){ showErr('封禁失败'); } finally{ disable(btn,false); } }
async function addWL(){ const btn=document.getElementById('btnAddWL'); disable(btn,true);
  try{ let ip=document.getElementById('wlip').value.trim(); if(!ip) {toast('请输入IP'); return;}
    let r=await fetch('/api/whitelist/'+ip,{method:'POST',credentials:'include'}); if(!r.ok) throw 0; toast('加入白名单成功'); loadAll();
  }catch(e){ showErr('加入白名单失败'); } finally{ disable(btn,false); } }
async function delWL(ip){ let r=await fetch('/api/whitelist/delete/'+ip,{method:'POST',credentials:'include'}); if(!r.ok){ showErr('删除失败'); return;} toast('已删除'); loadAll(); }
async function setLogLimit(){ const btn=document.getElementById('btnLogLimit'); disable(btn,true);
  try{ let mb=parseInt(document.getElementById('logmb').value||'0',10);
    if(isNaN(mb)||mb<1){ toast('请输入正确的 MB 数值'); return; }
    let r=await fetch('/api/loglimit/'+mb,{method:'POST',credentials:'include'}); if(!r.ok) throw 0; toast('已保存日志上限并检查轮转');
  }catch(e){ showErr('设置失败'); } finally{ disable(btn,false); } }
async function portSearch(){
  const btn=document.getElementById('btnPortSearch'); disable(btn,true);
  try{
    let p = document.getElementById('searchport').value.trim();
    if(!p){ toast('请输入端口'); return; }
    let res = await fetch('/api/portsearch?port='+encodeURIComponent(p), {credentials:'include'});
    if(!res.ok){ showErr('查询端口失败'); return; }
    let d = await res.json();
    let lines = ['端口 '+d.port+' 的占用：'];
    if(!d.results || d.results.length===0){ lines.push('无占用'); }
    else{
      d.results.forEach(x=>{
        lines.push(`${x.proc||''} (PID ${x.pid||''})  ${x.laddr||''}  -> ${x.raddr||''}  [${x.status||''}]`);
        if(x.exe) lines.push('  '+x.exe);
      });
    }
    document.getElementById('portsearch').innerText = lines.join('\n');
  }catch(e){ showErr('查询端口失败'); }
  finally{ disable(btn,false); }
}

async function logout(){ await fetch('/logout', {credentials:'include'}); location.href="/login"; }

// ---- Speedtest ----
function now(){ return (performance && performance.now)? performance.now(): Date.now(); }
async function doDL(){
  stopFlag=false;
  const btn=document.getElementById('btnDL'); disable(btn,true);
  const mode=document.getElementById('stmode').value;
  const size=parseInt(document.getElementById('stsize').value||'20',10);
  const out=document.getElementById('stout'); out.innerText='开始下载测速…';
  let rounds = (mode==='multi') ? 5 : 1, res=[];
  try{
    for(let i=0;i<rounds;i++){
      if(stopFlag) break;
      const t0=now();
      const resp=await fetch('/api/speedtest/down?size_mb='+size, {credentials:'include'});
      const reader = resp.body.getReader(); let got=0;
      while(true){
        const {done, value}=await reader.read(); if(done) break;
        got += (value? value.length : 0);
      }
      const dt=(now()-t0)/1000.0;
      const speed = got / dt;
      res.push(speed);
      out.innerText += `\n第${i+1}次：${(speed/1024/1024).toFixed(2)} MB/s (${(got/1024/1024).toFixed(1)} MB / ${dt.toFixed(2)} s)`;
    }
    if(res.length>1){
      const avg = res.reduce((a,b)=>a+b,0)/res.length;
      out.innerText += `\n平均：${(avg/1024/1024).toFixed(2)} MB/s`;
    }
  }catch(e){ showErr('下载测速失败'); }
  finally{ disable(btn,false); }
}
async function doUL(){
  stopFlag=false;
  const btn=document.getElementById('btnUL'); disable(btn,true);
  const mode=document.getElementById('stmode').value;
  const size=parseInt(document.getElementById('stsize').value||'20',10);
  const out=document.getElementById('stout'); out.innerText='开始上传测速…';
  let rounds = (mode==='multi') ? 5 : 1, res=[];
  try{
    for(let i=0;i<rounds;i++){
      if(stopFlag) break;
      const blob = new Blob([crypto.getRandomValues(new Uint8Array(size*1024*1024))]);
      const t0=now();
      const r = await fetch('/api/speedtest/up', {method:'POST', credentials:'include', body: blob});
      const js = await r.json();
      const dt=(now()-t0)/1000.0;
      const received = js.received || 0;
      const speed = received / dt;
      res.push(speed);
      out.innerText += `\n第${i+1}次：${(speed/1024/1024).toFixed(2)} MB/s (${(received/1024/1024).toFixed(1)} MB / ${dt.toFixed(2)} s)`;
    }
    if(res.length>1){
      const avg = res.reduce((a,b)=>a+b,0)/res.length;
      out.innerText += `\n平均：${(avg/1024/1024).toFixed(2)} MB/s`;
    }
  }catch(e){ showErr('上传测速失败'); }
  finally{ disable(btn,false); }
}
function stopST(){ stopFlag=true; toast('已停止'); }

document.addEventListener('DOMContentLoaded', ()=>{
  attachLabels();
  document.querySelectorAll('button').forEach(b=> b.setAttribute('type','button'));
  loadAll();
  setInterval(loadAll, 3000);
});
