const el = id => document.getElementById(id);
const fields = ['stack_url','loki_url','loki_user','otlp_url','otlp_user','loki_token','otlp_token'];
let state, busy = false;
function link(url, text) {
  const a = document.createElement('a'); a.href=url; a.textContent=text; a.target='_blank'; a.rel='noopener'; return a;
}
function traceURL(stack,s) {
  const uid='grafanacloud-traces', url=new URL('/explore',stack);
  const range={from:new Date((s.ts-60)*1000).toISOString(),to:new Date(Date.parse(s.ended)+60000).toISOString()};
  const pane={datasource:uid,queries:[{refId:'A',queryType:'traceql',query:s.trace_id,datasource:{type:'tempo',uid}}],range};
  url.searchParams.set('schemaVersion','1'); url.searchParams.set('panes',JSON.stringify({trace:pane})); return url;
}
function dashboardURL(stack,s) {
  const url=new URL('/d/wow-character-gear',stack);
  if(s){
    for(const field of ['character','region','realm'])url.searchParams.set('var-'+field,s[field]);
    url.searchParams.set('var-session',s.session_id);
    url.searchParams.set('from',s.ts*1000-30000); url.searchParams.set('to',Math.max(Date.parse(s.ended),s.checkpoint_ms||0)+60000);
  }
  return url;
}
function render(s) {
  state=s;
  const real=s.config.mode==='real', stack=s.cloud.stack_url;
  el('real').setAttribute('aria-pressed',real);el('simulated').setAttribute('aria-pressed',!real);
  el('source-title').textContent=real?'Character saves':'Session simulator';
  el('source-status').textContent=real?(s.client_present?'Watching for saves':'Waiting for WoW directory'):'Ready to generate';
  el('source-copy').textContent=real?'Start recording once in WoW. Reloads export your session and resume recording.':'Run the addon with sample equipment or a leveling journey. The recording goes to your configured Grafana stack.';
  el('sim-controls').hidden=real;
  el('dashboard').hidden=!stack;
  if(stack)el('dashboard').href=dashboardURL(stack);
  const rows=s.sessions.map(item=>{
    const tr=document.createElement('tr');
    const cell=(value)=>{const td=tr.insertCell();if(value instanceof Node)td.append(value);else td.textContent=value;return td;};
    const title=document.createElement('strong');title.append(stack?link(dashboardURL(stack,item),item.character):document.createTextNode(item.character));
    const name=cell(title),origin=document.createElement('small');origin.textContent=item.realm+' · '+item.region.toUpperCase();name.append(origin);
    cell(new Date(item.ts*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}));
    cell(Math.floor(item.duration_seconds/60)+'m '+item.duration_seconds%60+'s');cell(item.rows);cell('Exported');
    cell(item.metrics?'Delivered':'Pending');cell(item.traces&&stack?link(traceURL(stack,item),'Open trace ↗'):item.traces?'Delivered':'Pending');
    return tr;
  });
  el('sessions').replaceChildren(...rows);el('session-count').textContent=rows.length+' shown';el('empty').hidden=!!rows.length;
  if(s.error)el('notice').textContent=s.error;
}
async function refresh(){const r=await fetch('/status');if(!r.ok)throw Error('Companion unavailable');render(await r.json());}
async function act(route,data={},message='Saved.',inDialog=false){
  if(busy)return;busy=true;const notice=el(inDialog?'settings-notice':'notice');
  notice.textContent=route.includes('cloud')||route.includes('collector')?'Starting collector…':'Working…';
  try{
    const r=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await r.json();if(!r.ok)throw Error(result.error||'Request failed');
    await refresh();notice.textContent=message;
  }catch(e){notice.textContent=e.message;}finally{busy=false;}
}
for(const mode of ['real','simulated'])el(mode).onclick=()=>act('/settings',{mode},mode==='real'?'Watching for real character saves.':'Simulation mode selected.');
el('generate').onclick=()=>act('/simulate',{example:el('example').value},'Recording exported. Delivery updates appear below.');
el('open-settings').onclick=()=>{
  if(!state)return;
  el('client').value=state.config.client;el('interval').value=state.config.interval;
  for(const k of fields){el(k).value=state.cloud[k]||'';if(k.endsWith('_token'))el(k).placeholder=state.cloud[k+'_set']?'Saved · leave blank to keep':'';}
  el('settings-notice').textContent='';el('settings').showModal();
};
el('close').onclick=()=>el('settings').close();
el('config-form').onsubmit=e=>{e.preventDefault();act('/settings',{client:el('client').value,interval:Number(el('interval').value)},'Capture settings saved.',true);};
el('cloud-form').onsubmit=async e=>{e.preventDefault();await act('/cloud',Object.fromEntries(fields.map(k=>[k,el(k).value])),'Cloud settings saved. Collector started.',true);el('loki_token').value=el('otlp_token').value='';};
el('start').onclick=()=>act('/start-collector',{},'Collector started.',true);
async function poll(){try{await refresh();}catch(e){el('source-status').textContent='Companion offline';}finally{setTimeout(poll,3500);}}
poll();
