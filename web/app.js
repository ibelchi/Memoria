'use strict';
const $ = id => document.getElementById(id);
const state = {items:[], total:0, page:1, pages:1, root:'', folder:'', collection:'', collections:[], tags:[], selected:new Set(), selecting:false, current:null, token:'', config:null, drafts:new Map(), loadSeq:0};
let queryTimer, toastTimer;
function element(tag, cls, text) { const e=document.createElement(tag); if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e; }
function toast(message, error=false) { $('toast').textContent=message; $('toast').className=error?'error':''; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,error?10000:5000); }
async function api(path, method='GET', data) {
  const options={method, headers:{}};
  if(state.token&&path!=='/api/config')options.headers['X-Catalog-Token']=state.token;
  if(method!=='GET'){options.headers={'Content-Type':'application/json','X-Catalog-Token':state.token}; options.body=JSON.stringify(data||{});}
  const response=await fetch(path,options); const result=await response.json();
  if(!response.ok)throw new Error(result.error||'El servei local no respon.'); return result;
}
function safe(action) { return async (...args)=>{try{await action(...args);}catch(e){toast(e.message,true);}}; }
function duration(v){ if(v===null)return '—'; const n=Math.round(v); return Math.floor(n/60)+':'+String(n%60).padStart(2,'0'); }
function dateText(v) { if(!v.recorded_at)return 'Data desconeguda'; const parsed=new Date(v.recorded_at.slice(0,10)+'T12:00:00'); return parsed.toLocaleDateString('ca-ES',{day:'numeric',month:'short',year:'numeric'})+(v.date_source==='mtime'?' · aproximada':v.date_source==='filename'?' · del nom':''); }
function draftKey(){return 'cataleg-drafts:'+(state.config.catalog_id||state.config.data_dir);}
function pageSizeKey(){return 'cataleg-page-size:'+(state.config.catalog_id||state.config.data_dir);}
function workflowState(v){const text=getDraft(v).text.trim();return text&&v.tags.length?'complete':v.omit_annotations&&!text&&!v.tags.length?'empty_by_choice':'pending';}
const workflowLabels={pending:'Pendent de catalogar',complete:'Catalogat',empty_by_choice:'Sense anotacions per decisió'};
function refreshWorkflow(id){const v=state.current?.id===id?state.current:state.items.find(v=>v.id===id);if(!v)return;const value=workflowState(v);for(const node of document.querySelectorAll('[data-status]'))if(node.dataset.status===id){node.textContent=workflowLabels[value];node.hidden=value==='pending';}if(state.current?.id===id){$('catalog-status').textContent=workflowLabels[value];$('annotation-decision').textContent=v.omit_annotations?'Torna a pendents':'Deixa sense anotacions';$('annotation-decision').disabled=!!(getDraft(v).text.trim()||v.tags.length);}}
function persistDrafts(){
  const values={}; for(const [id,d] of state.drafts)if(d.rev!==d.saved)values[id]=d.text;
  try{localStorage.setItem(draftKey(),JSON.stringify(values));}catch(e){toast('No es pot conservar l’esborrany al navegador. Mantén la finestra oberta fins que indiqui «Desat».',true);}
}
function getDraft(v){if(!state.drafts.has(v.id))state.drafts.set(v.id,{text:v.description,rev:0,saved:0,promise:null,timer:null,error:false});return state.drafts.get(v.id);}
function status(id,message,error=false){
  for(const e of document.querySelectorAll('[data-save]'))if(e.dataset.save===id)e.textContent=message;
  if(state.current?.id===id){$('save-status').textContent=message; if(error){const b=element('button','quiet','Torna-ho a provar');b.onclick=safe(()=>flush(id));$('save-status').append(b);}}
}
function edit(v,text){const d=getDraft(v);d.text=text;d.rev++;d.error=false;persistDrafts();status(v.id,'Desant…');refreshWorkflow(v.id);clearTimeout(d.timer);d.timer=setTimeout(()=>flush(v.id).catch(()=>{}),650);}
async function flush(id){
  const d=state.drafts.get(id);if(!d)return;clearTimeout(d.timer);
  if(d.promise){await d.promise;if(d.rev!==d.saved)return flush(id);return;}
  if(d.rev===d.saved)return;
  d.promise=(async()=>{
    while(d.saved!==d.rev){const rev=d.rev,text=d.text;const saved=await api('/api/videos/'+id,'PATCH',{description:text});d.saved=rev;const item=state.items.find(v=>v.id===id);if(item)Object.assign(item,saved);if(state.current?.id===id)Object.assign(state.current,saved);persistDrafts();refreshWorkflow(id);}
    d.error=false;status(id,'Desat');
  })();
  try{await d.promise;}catch(e){d.error=true;status(id,'No s’ha pogut desar. L’esborrany es conserva.',true);throw new Error('No s’ha pogut desar. Mantén la finestra oberta i torna-ho a provar.');}finally{d.promise=null;}
}
async function flushAll(){await Promise.all([...state.drafts.keys()].map(flush));}
function currentQuery(){const p=new URLSearchParams({page:state.page,limit:$('page-size').value,owner:$('owner-filter').value,video_type:$('type-filter').value,excluded:$('excluded-filter').checked?'1':'',favorite:$('favorite-filter').checked?'1':'',collection:state.collection,q:$('query').value,root:state.root,folder:state.folder,state:$('state').value,start:$('date-start').value,end:$('date-end').value,unknown:$('unknown-date').checked?'1':'',sort:$('sort').value,tags:$('tag-filter').value});return p;}
async function load(){
  const seq=++state.loadSeq;const result=await api('/api/videos?'+currentQuery());if(seq!==state.loadSeq)return;
  state.items=result.items;state.total=result.total;state.pages=result.pages;state.page=result.page;
  if(state.page>state.pages){state.page=state.pages;return load();}
  $('demo-notice').hidden=!state.items.some(v=>v.demo)&&!state.roots?.some(r=>r.id==='demo');
  $('count').textContent=state.total+' vídeo'+(state.total===1?'':'s')+(state.folder?' · inclou subcarpetes':'');
  $('grid').replaceChildren();for(const v of state.items)$('grid').append(card(v));
  $('empty').hidden=!!state.items.length;
  $('empty-title').textContent=state.roots?.length?'No hi ha resultats':'Encara no hi ha vídeos';
  $('empty-text').textContent=state.roots?.length?'Prova altres paraules o neteja els filtres. Si la carpeta és nova, actualitza-la des de Configuració.':'Prem el + de la barra lateral per incorporar vídeos.';
  for(const suffix of ['', '-top']){
    $('page-label'+suffix).textContent=state.page+' / '+state.pages;
    $('previous-page'+suffix).disabled=state.page===1;$('next-page'+suffix).disabled=state.page>=state.pages;
  }
  updateSelection();
}
function card(v){
  const d=getDraft(v),article=element('article','card'),picture=element('div','card-image');
  const button=element('button','thumb-button');button.setAttribute('aria-label','Obre el vídeo: '+(d.text||'Sense descripció'));
  const img=element('img');img.src='/api/videos/'+v.id+'/thumbnail';img.alt='';img.loading='lazy';button.append(img,element('span','duration',duration(v.duration)));
  const badge=element('span','review-badge',workflowLabels[workflowState(v)]);badge.dataset.status=v.id;badge.hidden=workflowState(v)==='pending';button.append(badge);
  button.onclick=safe(()=>openDetail(v));picture.append(button);
  const favorite=element('button','favorite-star',v.favorite?'★':'☆');
  favorite.setAttribute('aria-label',v.favorite?'Treu dels favorits':'Marca com a favorit');
  favorite.setAttribute('aria-pressed',String(!!v.favorite));
  favorite.onclick=safe(async()=>{await flushAll();await api('/api/videos/'+v.id,'PATCH',{favorite:!v.favorite});await load();});

  if(state.selecting){const check=element('input','select-box');check.type='checkbox';check.checked=state.selected.has(v.id);check.setAttribute('aria-label','Selecciona '+(d.text||'vídeo sense descripció'));check.onchange=()=>{check.checked?state.selected.add(v.id):state.selected.delete(v.id);updateSelection();};picture.append(check);}
  const body=element('div','card-body'),meta=element('div','card-meta');meta.append(element('div','card-date',dateText(v)),favorite);body.append(meta);
  const text=element('textarea','card-description');text.value=d.text;text.rows=2;text.placeholder='Afegeix una descripció…';text.maxLength=10000;text.setAttribute('aria-label','Descripció del vídeo');text.oninput=()=>edit(v,text.value);text.onblur=()=>flush(v.id).catch(e=>toast(e.message,true));body.append(text);
  const tags=element('div','tags');for(const t of v.tags)tags.append(element('span','tag',t.name));body.append(tags);
  const save=element('span','card-save',d.error?'No s’ha pogut desar':d.rev!==d.saved?'Esborrany pendent':'');save.dataset.save=v.id;body.append(save);
  if(!v.available||!v.root_available)body.append(element('div','card-warning','Fitxer o disc no disponible · anotacions conservades'));
  if(v.extraction==='error')body.append(element('div','card-warning','Error de metadades · pots continuar anotant'));
  article.append(picture,body);return article;
}
async function refreshNavigation(){
  const [roots,folders,tags,collections]=await Promise.all([api('/api/roots'),api('/api/folders'),api('/api/tags'),api('/api/collections')]);
  state.collections=collections;renderCollections();
  const expanded=new Set([...$('folders').querySelectorAll('details[open]')].map(e=>e.dataset.rootId));
  state.roots=roots;state.tags=tags;$('folders').replaceChildren();
  for(const root of roots){
    const group=element('details','root-group');group.dataset.rootId=root.id;group.open=expanded.has(root.id);group.append(element('summary','',root.label));
    const all=element('button','root-nav','Tota la carpeta');all.onclick=safe(()=>setScope(root.id,'',root.label));group.append(all);
    for(const folder of folders.filter(f=>f.root_id===root.id)){
      const b=element('button','folder-nav'+(state.root===root.id&&state.folder===folder.path?' active':''),folder.path.replaceAll('/',' / '));
      b.onclick=safe(()=>setScope(root.id,folder.path,folder.path.split('/').at(-1)));group.append(b);
    }
    $('folders').append(group);
  }
  const selected=$('tag-filter').value;$('tag-filter').replaceChildren(new Option('Qualsevol',''));$('known-tags').replaceChildren();
  for(const t of tags){$('tag-filter').append(new Option(t.name,t.id));$('known-tags').append(new Option(t.name,t.name));}$('tag-filter').value=selected;
  renderRoots();
}
async function setScope(root='',folder='',label='Tots els vídeos',unreviewed=false){await flushAll();state.collection='';state.root=root;state.folder=folder;state.page=1;$('scope').textContent=root?(folder||label)+' · inclou subcarpetes':'';$('scope').hidden=!root;$('exclude-folder').hidden=!root;$('state').value=unreviewed?'pending':'';$('all').classList.toggle('active',!root&&!unreviewed);$('unreviewed').classList.toggle('active',unreviewed);await refreshNavigation();await load();}
function updateSelection(){ $('bulk').hidden=!state.selecting;$('select-mode').textContent=state.selecting?'Acaba la selecció':'Selecciona';$('selected-count').textContent=state.selected.size+' seleccionats';$('bulk-tags').disabled=!state.selected.size;$('bulk-dates').disabled=!state.selected.size;$('bulk-review').disabled=!state.selected.size;$('bulk-collection').disabled=!state.selected.size;$('bulk-uncollect').hidden=!state.collection;$('bulk-uncollect').disabled=!state.selected.size; }
async function openDetail(v){await flushAll();state.current=await api('/api/videos/'+v.id);renderDetail();if(!$('detail').open)$('detail').showModal();}
function renderDetail(){
  const v=state.current,d=getDraft(v);$('description').value=d.text;refreshWorkflow(v.id);
  $('save-status').textContent=d.error?'No s’ha pogut desar':d.rev!==d.saved?'Esborrany pendent':'Desat';
  $('detail-tags').replaceChildren();for(const t of v.tags){const e=element('span','tag',t.name);const remove=element('button','','×');remove.setAttribute('aria-label','Retira l’etiqueta '+t.name);remove.onclick=safe(async()=>{await api('/api/bulk/tags','POST',{ids:[v.id],names:[t.name],remove:true});state.current=await api('/api/videos/'+v.id);renderDetail();});e.append(remove);$('detail-tags').append(e);}
  $('metadata').textContent=v.owner_name+' · '+dateText(v)+' · '+duration(v.duration)+(v.width?' · '+v.width+' × '+v.height:'');
  $('technical').textContent=v.root_label+' / '+v.relative_path+'\n'+(v.codec||'Còdec pendent')+' · '+(v.container||'Contenidor pendent')+'\nOrigen de la data: '+({sample:'mostra fictícia',metadata:'metadades (pendent de contrastar amb la gravació)',filename:'patró del nom del fitxer',mtime:'modificació del fitxer; aproximació'}[v.date_source]||'desconegut')+(v.date_original?'\nValor original: '+v.date_original:'')+(v.error?'\n'+v.error:'');
  const player=$('player'),newVideo=player.dataset.videoId!==v.id; if(newVideo){player.pause();player.removeAttribute('src');player.dataset.videoId=v.id;player.dataset.playbackError='';player.poster='/api/videos/'+v.id+'/thumbnail';player.load();}player.hidden=!!v.demo;$('sample-preview').hidden=!v.demo;if(v.demo)$('sample-preview').src=player.poster;
  $('playback-message').hidden=false;$('open-external').hidden=!!v.demo;$('reveal-video').hidden=!!v.demo;
  $('detail-collections').replaceChildren();for(const c of v.collections||[]){const chip=element('span','tag',c.name);const remove=element('button','','×');remove.setAttribute('aria-label','Treu de la col·lecció '+c.name);remove.onclick=safe(async()=>{await flushAll();await api('/api/collections/'+c.id+'/members','POST',{ids:[v.id],remove:true});state.current=await api('/api/videos/'+v.id);await refreshNavigation();renderDetail();});chip.append(remove);$('detail-collections').append(chip);}
  if(v.demo){$('playback-message').textContent='Aquesta és una mostra fictícia per provar la cerca i les anotacions. La il·lustració no és un fotograma i no hi ha cap gravació per reproduir.';}
  else if(!v.available||!v.root_available){$('playback-message').textContent='El fitxer o el disc no està disponible. Les teves anotacions es conserven.';}
  else if(unsupportedInBrowser(v)||player.dataset.playbackError){$('playback-message').textContent='Aquest format no es pot reproduir en aquest navegador. Prem «Obre la carpeta del vídeo» i obre l’arxiu des de Windows. No es generen còpies ni conversions.';}else if(newVideo){player.src='/api/videos/'+v.id+'/stream';$('playback-message').hidden=true;}else{$('playback-message').hidden=true;}
  const i=state.items.findIndex(item=>item.id===v.id);$('detail-position').textContent='Vídeo '+(i+1)+' de '+state.items.length+' en aquesta pàgina';$('previous-video').disabled=i<=0;$('next-video').disabled=i>=state.items.length-1;$('review-next').textContent=i>=state.items.length-1?'Torna al catàleg':'Següent vídeo →';
}
async function closeDetail(){await flushAll();$('player').pause();$('player').removeAttribute('src');$('player').load();$('detail').close();delete $('player').dataset.videoId;state.current=null;await refreshNavigation();await load();}
async function navigate(delta){await flushAll();const i=state.items.findIndex(v=>v.id===state.current.id),next=state.items[i+delta];if(next)await openDetail(next);else await closeDetail();}
function renderRoots(){
  $('roots-list').replaceChildren();for(const root of state.roots||[]){
    const row=element('div','root-item');row.append(element('strong','',root.label));
    if(root.id==='demo'){row.append(element('p','','Dades fictícies · sense fitxers reals. Per al teu catàleg, obre «Inicia catàleg».'));}
    else{const scan=element('button','secondary','Actualitza');scan.onclick=safe(async()=>{await flushAll();scan.disabled=true;try{const result=await api('/api/scans','POST',{root_id:root.id});pollScan(result.id,row,scan);}catch(e){scan.disabled=false;throw e;}});row.append(scan);const location=element('details','root-path-details');location.append(element('summary','','Ubicació i recuperació'),element('pre','',root.path));const move=element('button','secondary','Indica una nova ubicació');move.onclick=safe(()=>openRelocate(root));location.append(move);row.append(location);}
    if(root.id!=='demo'){
      const owner=element('details','root-path-details');owner.append(element('summary','','Propietari: '+(state.config.owners.find(o=>o.id===root.owner_id)?.name||'Pendent d’assignar')));
      const select=element('select');select.setAttribute('aria-label','Propietari de '+root.label);select.append(new Option('Tria el propietari',''));for(const o of state.config.owners)select.append(new Option(o.name,o.id));select.value=root.owner_id||'';
      const label=element('label','check');const check=element('input');check.type='checkbox';label.append(check,document.createTextNode(' Canvia també els vídeos ja assignats d’aquesta carpeta'));
      const button=element('button','secondary','Desa propietari');button.onclick=safe(async()=>{await flushAll();await api('/api/roots/'+root.id+'/owner','POST',{owner_id:select.value,apply_existing:check.checked});await refreshNavigation();await load();toast('Propietari actualitzat.');});owner.append(select,label,button);row.append(owner);
    }
    $('roots-list').append(row);
  }
}
async function pollScan(id,row,button){
  let label=row.querySelector('.scan-status');if(!label){label=element('span','scan-status');row.append(label);}
  try{const scan=await api('/api/scans/'+id);label.textContent=scan.processed+' vídeos processats · '+scan.errors+' errors'+(scan.message?' · '+scan.message:'');
    $('scan-progress').hidden=scan.status!=='running';$('scan-progress').textContent=label.textContent;
    if(scan.status==='running'){setTimeout(()=>pollScan(id,row,button),800);}else{button.disabled=false;await refreshNavigation();await load();toast(scan.status==='done'?'Exploració completada: '+scan.processed+' vídeos, '+scan.errors+' errors.':scan.message,scan.status!=='done');}
  }catch(e){button.disabled=false;$('scan-progress').hidden=true;label.textContent=e.message;toast(e.message,true);}
}
async function pickRoot(){await flushAll();if(state.roots?.some(r=>r.id==='demo')){toast('Obre el catàleg real per incorporar gravacions personals.',true);return;}$('root-add-path').value='';$('root-add-owner').value='';$('root-add-status').textContent='';$('root-add').showModal();}
async function settings(){await flushAll();await refreshNavigation();$('tools-status').textContent=state.config.ffmpeg&&state.config.ffprobe?'FFmpeg i ffprobe disponibles.':'No s’han trobat FFmpeg i ffprobe. Consulta les instruccions del projecte.';$('data-location').textContent=state.config.data_dir;$('settings').showModal();}
async function initialize(){
  state.config=await api('/api/config');state.token=state.config.token;
  try{const size=localStorage.getItem(pageSizeKey())||localStorage.getItem('cataleg-page-size:'+state.config.data_dir);if(['25','50','100','all'].includes(size))$('page-size').value=size;}catch(e){/* Default 50 remains available without browser storage. */}
  try{const drafts=JSON.parse(localStorage.getItem(draftKey())||localStorage.getItem('cataleg-drafts:'+state.config.data_dir)||'{}');for(const [id,text] of Object.entries(drafts))if(typeof text==='string')state.drafts.set(id,{text,rev:1,saved:0,timer:null,promise:null,error:false});if(state.drafts.size)toast('S’han recuperat esborranys pendents. Es desen quan continues treballant.');}catch(e){toast('No s’han pogut llegir els esborranys del navegador.',true);}
  await refreshNavigation();await load();
}
$('query').oninput=()=>{clearTimeout(queryTimer);queryTimer=setTimeout(safe(async()=>{await flushAll();state.page=1;await load();}),200);};
for(const id of ['type-filter','date-start','date-end','state','tag-filter','excluded-filter','unknown-date','favorite-filter','sort','owner-filter'])$(id).onchange=safe(async()=>{await flushAll();state.page=1;await load();});
$('all').onclick=safe(()=>setScope());$('unreviewed').onclick=safe(()=>setScope('','','Pendents de catalogar',true));
$('filter-toggle').onclick=()=>{$('filters').hidden=!$('filters').hidden;$('filter-toggle').setAttribute('aria-expanded',String(!$('filters').hidden));};
$('clear-filters').onclick=safe(async()=>{await flushAll();for(const id of ['query','type-filter','date-start','date-end','state','tag-filter','owner-filter'])$(id).value='';$('excluded-filter').checked=false;$('unknown-date').checked=false;$('favorite-filter').checked=false;state.page=1;await load();});
for(const suffix of ['', '-top']){
  $('previous-page'+suffix).onclick=safe(async()=>{await flushAll();state.page=Math.max(1,state.page-1);await load();window.scrollTo(0,0);});
  $('next-page'+suffix).onclick=safe(async()=>{await flushAll();state.page=Math.min(state.pages,state.page+1);await load();window.scrollTo(0,0);});
}
$('page-size').onchange=safe(async()=>{await flushAll();state.page=1;try{localStorage.setItem(pageSizeKey(),$('page-size').value);}catch(e){}await load();});
$('select-mode').onclick=safe(async()=>{await flushAll();state.selecting=!state.selecting;state.selected.clear();await load();});
$('clear-selection').onclick=safe(async()=>{state.selecting=false;state.selected.clear();await load();});
$('bulk-tags').onclick=()=>{$('bulk-tag-input').value='';$('bulk-dialog').showModal();};$('cancel-bulk').onclick=()=>$('bulk-dialog').close();
$('bulk-tag-form').onsubmit=safe(async e=>{e.preventDefault();await flushAll();const names=$('bulk-tag-input').value.split(',').map(x=>x.trim()).filter(Boolean);await api('/api/bulk/tags','POST',{ids:[...state.selected],names});$('bulk-dialog').close();await refreshNavigation();await load();toast('Etiquetes afegides.');});
$('bulk-review').onclick=safe(async()=>{await flushAll();await api('/api/bulk/annotation-decision','POST',{ids:[...state.selected],omit:true});await load();toast('Decisió desada per als vídeos seleccionats.');});
$('description').oninput=()=>edit(state.current,$('description').value);$('description').onblur=()=>{if(state.current)flush(state.current.id).catch(e=>toast(e.message,true));};
$('annotation-decision').onclick=safe(async()=>{await flushAll();await api('/api/bulk/annotation-decision','POST',{ids:[state.current.id],omit:!state.current.omit_annotations});state.current=await api('/api/videos/'+state.current.id);renderDetail();});
$('tag-form').onsubmit=safe(async e=>{e.preventDefault();await flushAll();const name=$('new-tag').value.trim();if(!name)return;await api('/api/bulk/tags','POST',{ids:[state.current.id],names:[name]});$('new-tag').value='';state.current=await api('/api/videos/'+state.current.id);await refreshNavigation();renderDetail();});
$('close-detail').onclick=safe(closeDetail);$('detail').addEventListener('cancel',e=>{e.preventDefault();safe(closeDetail)();});
$('previous-video').onclick=safe(()=>navigate(-1));$('next-video').onclick=safe(()=>navigate(1));$('review-next').onclick=safe(()=>navigate(1));
$('player').onerror=()=>{if(state.current&&!state.current.demo&&$('player').getAttribute('src')){$('player').dataset.playbackError='1';$('playback-message').hidden=false;$('playback-message').textContent='El navegador no pot reproduir aquest format. Obre la carpeta del vídeo i reprodueix l’arxiu des de Windows. No es generen còpies ni conversions.';}};
$('open-external').onclick=()=>openDesktop('open');
$('settings-button').onclick=safe(settings);$('close-settings').onclick=()=>$('settings').close();$('add-root').onclick=safe(pickRoot);
$('backup').onclick=safe(async()=>{await flushAll();const result=await api('/api/backup','POST',{});$('backup-result').textContent='Còpia desada: '+result.path;});
$('shutdown').onclick=safe(async()=>{await flushAll();await api('/api/shutdown','POST',{});$('settings').close();$('grid').replaceChildren();$('empty').hidden=false;$('empty-title').textContent='Catàleg tancat';$('empty-text').textContent='S’ha desat una còpia. Pots tancar aquesta pestanya i tornar a obrir l’aplicació amb la icona.';for(const b of document.querySelectorAll('button,input,select,textarea'))b.disabled=true;});
document.addEventListener('keydown',e=>{if(!$('detail').open||e.altKey||e.ctrlKey||e.metaKey)return;if(['INPUT','TEXTAREA','SELECT','VIDEO','BUTTON'].includes(document.activeElement.tagName))return;if(e.key==='ArrowRight'){e.preventDefault();safe(()=>navigate(1))();}if(e.key==='ArrowLeft'){e.preventDefault();safe(()=>navigate(-1))();}});
window.addEventListener('beforeunload',e=>{if([...state.drafts.values()].some(d=>d.rev!==d.saved)){e.preventDefault();e.returnValue='';}});
initialize().catch(e=>{toast(e.message,true);$('count').textContent='No es pot connectar amb el catàleg local.';});

let relocateRoot=null,relocatePlan=null,recoveryGroups=[];
async function openRelocate(root){
  await flushAll();relocateRoot=root;relocatePlan=null;$('relocate-old').textContent='Ubicació actual: '+root.path;
  $('relocate-path').value='';$('relocate-status').textContent='';$('relocate-plan').hidden=true;$('relocate').showModal();
}
async function checkRelocate(){
  relocatePlan=null;$('relocate-plan').hidden=true;const path=$('relocate-path').value.trim();if(!path)return;
  $('relocate-status').textContent='Comprovant el contingut dels vídeos… Pot trigar uns minuts en carpetes grans.';
  $('relocate-check').disabled=true;$('relocate-pick').disabled=true;$('close-relocate').disabled=true;$('relocate-path').disabled=true;
  try{
    relocatePlan=await api('/api/roots/'+relocateRoot.id+'/preview','POST',{path});
    $('relocate-summary').textContent='Vídeos verificats: '+relocatePlan.matched+' de '+relocatePlan.total+'. Amb diverses coincidències: '+relocatePlan.ambiguous+'. Sense coincidència: '+relocatePlan.unmatched+'. Els casos pendents conservaran les anotacions i es podran revisar a «Vídeos moguts» després d’explorar la nova carpeta.';
    $('relocate-plan').hidden=false;$('relocate-status').textContent='Comprovació completada. Revisa el resultat abans de confirmar.';
  }catch(e){$('relocate-status').textContent=e.message;throw e;}
  finally{$('relocate-check').disabled=false;$('relocate-pick').disabled=false;$('close-relocate').disabled=false;$('relocate-path').disabled=false;}
}
async function openRecovery(){await flushAll();$('recovery').showModal();await loadRecovery();}
async function loadRecovery(){
  $('recovery-status').textContent='Comprovant el catàleg…';recoveryGroups=await api('/api/recovery');$('recovery-list').replaceChildren();
  const unique=recoveryGroups.filter(g=>g.unique);$('recover-unique').hidden=!unique.length;$('recover-unique').textContent='Recupera coincidències úniques ('+unique.length+')';
  $('recovery-status').textContent=recoveryGroups.length?'Entrades amb ubicació pendent: '+recoveryGroups.length+'.':'No hi ha vídeos pendents de recuperar. Explora les carpetes després de moure fitxers.';
  for(const group of recoveryGroups){
    const box=element('section','recovery-item'),v=group.source;
    box.append(element('strong','',v.description||'Vídeo sense descripció'),element('p','location','Abans: '+v.root_label+' / '+v.relative_path));
    const tags=element('div','tags');for(const t of v.tags)tags.append(element('span','tag',t.name));tags.append(element('span','tag',workflowLabels[v.catalog_status]||'Pendent de catalogar'));box.append(tags);
    if(group.targets.length){
      const label=element('label','','Ubicació trobada amb contingut idèntic'),select=element('select');select.setAttribute('aria-label','Nova ubicació de '+(v.description||v.relative_path));
      if(!group.unique)select.append(new Option('Tria quina còpia correspon a aquesta entrada',''));
      for(const target of group.targets)select.append(new Option(target.root_label+' / '+target.relative_path,target.id));
      const button=element('button','secondary','Recupera les anotacions aquí');button.disabled=!select.value;select.onchange=()=>button.disabled=!select.value;
      button.onclick=safe(()=>recoverPairs([{source_id:v.id,target_id:select.value}]));box.append(label,select,button);
      if(!group.unique)box.append(element('p','','Hi ha còpies idèntiques. Tria explícitament la ubicació; no s’uniran automàticament.'));
    }else box.append(element('p','',v.sha256?'Encara no s’ha trobat una nova ubicació sense anotacions pròpies. Afegeix i explora la carpeta de destinació.':'No hi ha una empremta anterior al moviment. Torna a posar el fitxer a la ubicació original i explora-la abans de reorganitzar-lo.'));
    $('recovery-list').append(box);
  }
}
async function recoverPairs(pairs){
  await flushAll();for(const b of $('recovery').querySelectorAll('button,select'))b.disabled=true;
  $('recovery-status').textContent='Verificant els fitxers i recuperant les anotacions…';
  try{
    const result=await api('/api/recovery/apply','POST',{pairs});
    for(const pair of pairs){state.drafts.delete(pair.source_id);state.drafts.delete(pair.target_id);}persistDrafts();state.selected.clear();
    await refreshNavigation();await load();await loadRecovery();toast(result.recovered+' vídeos recuperats amb les anotacions.');
  }catch(e){$('recovery-status').textContent=e.message;throw e;}
  finally{$('close-recovery').disabled=false;$('recover-unique').disabled=false;for(const box of $('recovery-list').querySelectorAll('.recovery-item')){const select=box.querySelector('select'),button=box.querySelector('button');if(select){select.disabled=false;button.disabled=!select.value;}}}
}
$('recovery-button').onclick=safe(openRecovery);$('close-recovery').onclick=()=>$('recovery').close();
$('recover-unique').onclick=safe(()=>recoverPairs(recoveryGroups.filter(g=>g.unique).map(g=>({source_id:g.source.id,target_id:g.targets[0].id}))));
$('close-relocate').onclick=()=>$('relocate').close();
$('relocate').addEventListener('cancel',e=>{if($('close-relocate').disabled)e.preventDefault();});
$('recovery').addEventListener('cancel',e=>{if($('close-recovery').disabled)e.preventDefault();});
$('relocate-path').oninput=()=>{relocatePlan=null;$('relocate-plan').hidden=true;};
$('relocate-form').onsubmit=safe(async e=>{e.preventDefault();await checkRelocate();});
$('relocate-pick').onclick=safe(async()=>{const result=await api('/api/roots/pick','POST',{select_only:true});if(!result.cancelled){$('relocate-path').value=result.path;await checkRelocate();}});
$('relocate-confirm').onclick=safe(async()=>{
  if(!relocatePlan)return;await flushAll();$('relocate-confirm').disabled=true;$('close-relocate').disabled=true;
  $('relocate-status').textContent='Verificant de nou i actualitzant el catàleg…';
  try{const result=await api('/api/roots/'+relocateRoot.id+'/relink','POST',{token:relocatePlan.token});$('relocate').close();await refreshNavigation();await load();toast(result.matched+' vídeos revinculats. Explora la nova carpeta per incorporar altres vídeos o resoldre els casos pendents.');}
  catch(e){$('relocate-status').textContent=e.message;throw e;}
  finally{$('relocate-confirm').disabled=false;$('close-relocate').disabled=false;}
});

let editingCollection=null,deletingCollection=null,collectionSelection=[];
function renderCollections(){
  $('collections-list').replaceChildren();
  if(!state.collections.length)$('collections-list').append(element('p','collections-empty','Encara no hi ha col·leccions'));
  for(const c of state.collections){const b=element('button','collection-nav'+(state.collection===c.id?' active':''));b.append(element('span','',c.name),element('span','collection-count',String(c.video_count)));b.onclick=safe(()=>showCollection(c.id));$('collections-list').append(b);}
  const selected=$('collection-choice').value;$('collection-choice').replaceChildren(new Option('Tria una col·lecció',''));for(const c of state.collections)$('collection-choice').append(new Option(c.name,c.id));$('collection-choice').value=selected;
  if($('collection-manager').open)renderCollectionManager();
}
async function showCollection(id){
  await flushAll();state.collection=id;state.root='';state.folder='';state.page=1;state.selected.clear();$('state').value='';
  const c=state.collections.find(c=>c.id===id);$('scope').textContent=c?c.name:'';$('scope').hidden=!c;
  $('all').classList.remove('active');$('unreviewed').classList.remove('active');renderCollections();await load();
}
async function editCollection(c=null){await flushAll();editingCollection=c;$('collection-editor-title').textContent=c?'Canvia el nom':'Crea una col·lecció';$('collection-name').value=c?c.name:'';$('collection-editor').showModal();}
async function chooseCollection(ids){
  await flushAll();collectionSelection=[...ids];await refreshNavigation();$('collection-picker-count').textContent='Vídeos seleccionats: '+ids.length+'. Continuaran a les carpetes d’origen.';$('collection-choice').value=state.collection;$('collection-picker').showModal();
}
function renderCollectionManager(){
  $('collection-manager-list').replaceChildren();
  if(!state.collections.length)$('collection-manager-list').append(element('p','','Encara no hi ha col·leccions.'));
  for(const c of state.collections){const row=element('section','root-item');row.append(element('strong','',c.name),element('p','',c.video_count+' vídeos'));const rename=element('button','secondary','Canvia el nom');rename.onclick=safe(()=>editCollection(c));const remove=element('button','quiet','Elimina');remove.onclick=()=>{deletingCollection=c;$('collection-delete-name').textContent=c.name;$('collection-delete').showModal();};row.append(rename,remove);$('collection-manager-list').append(row);}
}
$('new-collection').onclick=safe(()=>editCollection());$('picker-new-collection').onclick=safe(()=>editCollection());$('manager-new-collection').onclick=safe(()=>editCollection());
$('cancel-collection-editor').onclick=()=>$('collection-editor').close();$('cancel-collection-picker').onclick=()=>$('collection-picker').close();
$('collection-name-form').onsubmit=safe(async e=>{
  e.preventDefault();const result=await api('/api/collections'+(editingCollection?'/'+editingCollection.id:''),editingCollection?'PATCH':'POST',{name:$('collection-name').value});
  $('collection-editor').close();await refreshNavigation();if($('collection-picker').open)$('collection-choice').value=result.id;
  if(state.collection===result.id){$('scope').textContent=result.name;}toast(editingCollection?'Nom actualitzat.':'Col·lecció creada.');
});
$('bulk-collection').onclick=safe(()=>chooseCollection([...state.selected]));$('detail-add-collection').onclick=safe(()=>chooseCollection([state.current.id]));
$('collection-picker-form').onsubmit=safe(async e=>{
  e.preventDefault();await flushAll();const id=$('collection-choice').value;if(!id)return;
  for(let i=0;i<collectionSelection.length;i+=500)await api('/api/collections/'+id+'/members','POST',{ids:collectionSelection.slice(i,i+500)});
  $('collection-picker').close();await refreshNavigation();await load();
  if(state.current){state.current=await api('/api/videos/'+state.current.id);renderDetail();}toast('Vídeos afegits a la col·lecció.');
});
$('bulk-uncollect').onclick=safe(async()=>{await flushAll();const ids=[...state.selected];for(let i=0;i<ids.length;i+=500)await api('/api/collections/'+state.collection+'/members','POST',{ids:ids.slice(i,i+500),remove:true});state.selected.clear();await refreshNavigation();await load();toast('Vídeos retirats de la col·lecció; els originals es conserven.');});
$('manage-collections').onclick=safe(async()=>{await flushAll();await refreshNavigation();renderCollectionManager();$('collection-manager').showModal();});$('close-collection-manager').onclick=()=>$('collection-manager').close();
$('cancel-collection-delete').onclick=()=>$('collection-delete').close();
$('confirm-collection-delete').onclick=safe(async()=>{await flushAll();await api('/api/collections/'+deletingCollection.id+'/delete','POST',{});$('collection-delete').close();if(state.collection===deletingCollection.id)await setScope();else{await refreshNavigation();await load();}toast('Col·lecció eliminada. Els vídeos es conserven.');});
$('reveal-video').onclick=()=>openDesktop('reveal');

$('cancel-root-add').onclick=()=>$('root-add').close();
$('root-add-pick').onclick=safe(async()=>{const result=await api('/api/roots/pick','POST',{});if(!result.cancelled)$('root-add-path').value=result.path;});
$('root-add-form').onsubmit=safe(async e=>{
  e.preventDefault();await flushAll();$('root-add-submit').disabled=true;$('root-add-status').textContent='Afegint la carpeta…';
  try{const root=await api('/api/roots','POST',{path:$('root-add-path').value,owner_id:$('root-add-owner').value});const scan=await api('/api/scans','POST',{root_id:root.id});$('root-add').close();await refreshNavigation();pollScan(scan.id,$('root-add-status'),$('root-add-submit'));toast('Carpeta afegida. S’estan llegint els vídeos.');}
  catch(e){$('root-add-status').textContent=e.message;$('root-add-submit').disabled=false;throw e;}
});
let storageMode='move',storagePlan=null,storageBusy=false;
const storageNames={move:'Trasllada aquest catàleg',open:'Obre un altre catàleg',create:'Crea un catàleg buit'};
const storageExplanations={move:'Tria una carpeta buida. Es copiaran i comprovaran el catàleg, les miniatures i les còpies. L’origen es conservarà i els vídeos originals no es mouran.',open:'Selecciona la carpeta que conté el catàleg que vols obrir. Les dades actuals es conservaran i es farà una còpia abans del canvi.',create:'Selecciona una carpeta buida per començar un catàleg nou. El catàleg actual es conservarà.'};
async function showStorage(mode){await flushAll();storageMode=mode;storagePlan=null;$('storage-title').textContent=storageNames[mode];$('storage-explanation').textContent=storageExplanations[mode];$('storage-path').value='';$('storage-status').textContent='';$('storage-plan').hidden=true;$('storage-dialog').showModal();}
function setStorageBusy(value){storageBusy=value;for(const e of $('storage-dialog').querySelectorAll('input,button'))e.disabled=value;}
$('storage-move').onclick=safe(()=>showStorage('move'));$('storage-open').onclick=safe(()=>showStorage('open'));$('storage-create').onclick=safe(()=>showStorage('create'));
$('storage-close').onclick=()=>$('storage-dialog').close();$('storage-dialog').addEventListener('cancel',e=>{if(storageBusy)e.preventDefault();});
$('storage-pick').onclick=safe(async()=>{const result=await api('/api/storage/pick','POST',{});if(!result.cancelled){$('storage-path').value=result.path;storagePlan=null;$('storage-plan').hidden=true;}});
$('storage-path').oninput=()=>{storagePlan=null;$('storage-plan').hidden=true;};
$('storage-form').onsubmit=safe(async e=>{
  e.preventDefault();await flushAll();setStorageBusy(true);storagePlan=null;$('storage-plan').hidden=true;$('storage-status').textContent='Comprovant la carpeta…';
  try{storagePlan=await api('/api/storage/preview','POST',{mode:storageMode,path:$('storage-path').value});$('storage-summary').textContent=storageNames[storageMode]+': '+storagePlan.path+'. Vídeos: '+storagePlan.videos+'.';$('storage-confirm').textContent='Confirma: '+storageNames[storageMode].toLowerCase();$('storage-plan').hidden=false;$('storage-status').textContent='Comprovació completada.';}
  catch(e){$('storage-status').textContent=e.message;throw e;}finally{setStorageBusy(false);}
});
$('storage-confirm').onclick=safe(async()=>{
  if(!storagePlan)return;await flushAll();setStorageBusy(true);$('storage-status').textContent='Preparant i comprovant el catàleg. Espera que acabi…';
  try{await api('/api/storage/apply','POST',{token:storagePlan.token});window.location.reload();}
  catch(e){$('storage-status').textContent=e.message;setStorageBusy(false);throw e;}
});

$('about-button').onclick=()=>$('about').showModal();$('close-about').onclick=()=>$('about').close();

$('activity-button').onclick=safe(async()=>{
  await flushAll();$('activity').showModal();$('activity-list').textContent='Carregant…';
  const rows=await api('/api/activity');$('activity-list').replaceChildren();
  if(!rows.length)$('activity-list').textContent='Encara no hi ha activitat registrada. Els canvis nous apareixeran aquí.';
  for(const row of rows){
    const item=element('li','activity-item');item.append(element('time','',new Date(row.created_at).toLocaleString('ca-ES')),element('span','',row.action),element('span','activity-label',row.label));
    if(row.root_path)item.append(element('span','activity-path',row.root_path));
    if(row.scan_id){
      const counts={added:row.items.filter(v=>v.change==='Afegit').length,changed:row.items.filter(v=>v.change==='Actualitzat').length};
      const summary=row.status==='running'?'Exploració en curs…':row.status==='error'||row.status==='interrupted'?'Exploració incompleta':counts.added+(counts.added===1?' vídeo afegit':' vídeos afegits')+' · '+counts.changed+(counts.changed===1?' actualitzat':' actualitzats');
      item.append(element('span','activity-label',summary+(row.errors?' · '+row.errors+' errors':'')));
      if(row.message)item.append(element('span','activity-label',row.message));
      if(row.items.length){const details=element('details','activity-videos');details.append(element('summary','',row.action==='Carpeta incorporada'?'Mostra els vídeos incorporats':'Mostra els vídeos afegits o actualitzats'));const list=element('ul');for(const v of row.items)list.append(element('li','',v.change+' · '+v.name));details.append(list);item.append(details);}
    }
    $('activity-list').append(item);
  }
});
$('close-activity').onclick=()=>$('activity').close();

let directoryResolve=null,directoryCurrent='',directoryParent=null,directorySeq=0;
async function browseDirectory(path=''){
  const seq=++directorySeq;$('directory-status').textContent='Carregant carpetes…';$('directory-select').disabled=true;
  try{const result=await api('/api/directories?'+new URLSearchParams({path}));if(seq!==directorySeq)return;
    directoryCurrent=result.path;directoryParent=result.parent;$('directory-path').value=result.path;$('directory-up').disabled=result.parent===null;
    $('directory-list').replaceChildren();for(const folder of result.folders){const b=element('button','directory-entry',folder.name);b.onclick=safe(()=>browseDirectory(folder.path));$('directory-list').append(b);}
    $('directory-status').textContent=result.folders.length?'':'Aquesta carpeta no té subcarpetes.';$('directory-select').disabled=!result.path;
  }catch(e){if(seq===directorySeq)$('directory-status').textContent=e.message;}
}
async function chooseFolder(buttonId,statusId){
  if(directoryResolve)return {cancelled:true};
  const promise=new Promise(resolve=>directoryResolve=resolve);$('directory-browser').showModal();await browseDirectory('');
  const result=await promise;$(statusId).textContent=result.cancelled?'Selecció cancel·lada.':'Carpeta seleccionada.';return result;
}
function finishDirectory(result){directorySeq++;$('directory-browser').close();const resolve=directoryResolve;directoryResolve=null;if(resolve)resolve(result);}
$('directory-close').onclick=()=>finishDirectory({cancelled:true});
$('directory-browser').oncancel=e=>{e.preventDefault();finishDirectory({cancelled:true});};
$('directory-select').onclick=()=>finishDirectory({path:directoryCurrent});
$('directory-drives').onclick=safe(()=>browseDirectory(''));
$('directory-up').onclick=safe(()=>browseDirectory(directoryParent||''));
$('directory-form').onsubmit=safe(async e=>{e.preventDefault();await browseDirectory($('directory-path').value);});
$('root-add-pick').onclick=safe(async()=>{const result=await chooseFolder('root-add-pick','root-add-status');if(!result.cancelled)$('root-add-path').value=result.path;});
$('storage-pick').onclick=safe(async()=>{const result=await chooseFolder('storage-pick','storage-status','/api/storage/pick');if(!result.cancelled){$('storage-path').value=result.path;storagePlan=null;$('storage-plan').hidden=true;}});
$('relocate-pick').onclick=safe(async()=>{const result=await chooseFolder('relocate-pick','relocate-status');if(!result.cancelled){$('relocate-path').value=result.path;await checkRelocate();}});

const renderDetailBase=renderDetail;
renderDetail=function(){renderDetailBase();const v=state.current;$('video-type').value=v.video_type;$('exclude-video').textContent=v.individually_excluded?'Torna al catàleg':v.folder_excluded?'Exclòs per la carpeta':'Exclou del catàleg';$('exclude-video').disabled=!!v.folder_excluded&&!v.individually_excluded;$('recycle-video').disabled=!!v.demo||!v.available||!v.root_available;};
let removalPlan=null,removalBusy=false;
async function prepareRemoval(action){
  await flushAll();$('player').pause();$('player').removeAttribute('src');$('player').load();
  $('removal-title').textContent=action==='recycle'?'Envia a la paperera':action==='restore'?'Torna al catàleg':'Exclou del catàleg';
  $('removal-message').textContent=action==='recycle'?'El fitxer original s’enviarà a la paperera de Windows i desapareixerà del catàleg. Les anotacions es conservaran. No s’eliminarà definitivament.':action==='restore'?'El vídeo tornarà a aparèixer al catàleg. Si el vas enviar a la paperera, restaura primer el fitxer des de Windows i actualitza la carpeta.':'El vídeo deixarà d’aparèixer al catàleg, també en actualitzar la carpeta. L’arxiu original i les anotacions es conservaran. Podràs recuperar-lo amb el filtre Exclosos del catàleg.';
  $('removal-file').textContent=state.current.relative_path;$('removal-status').textContent='Preparant confirmació…';$('removal-confirm').disabled=true;removalPlan=null;$('removal-dialog').showModal();
  try{const plan=await api('/api/videos/'+state.current.id+'/removal-preview','POST',{action});if(!$('removal-dialog').open)return;removalPlan={...plan,id:state.current.id};$('removal-file').textContent=plan.path;$('removal-status').textContent='';$('removal-confirm').disabled=false;}
  catch(e){$('removal-status').textContent=e.message;}
}
$('exclude-video').onclick=safe(()=>prepareRemoval(state.current.individually_excluded?'restore':'exclude'));
$('recycle-video').onclick=safe(()=>prepareRemoval('recycle'));
$('removal-cancel').onclick=()=>{if(!removalBusy){removalPlan=null;$('removal-dialog').close();delete $('player').dataset.videoId;renderDetail();}};
$('removal-dialog').oncancel=e=>{e.preventDefault();if(!removalBusy){removalPlan=null;$('removal-dialog').close();delete $('player').dataset.videoId;renderDetail();}};
$('removal-confirm').onclick=safe(async()=>{
  if(!removalPlan||removalBusy)return;removalBusy=true;$('removal-confirm').disabled=true;$('removal-cancel').disabled=true;
  $('removal-status').textContent='Aplicant el canvi…';
  try{await api('/api/videos/'+removalPlan.id+'/removal-confirm','POST',{token:removalPlan.token});$('removal-dialog').close();removalPlan=null;await closeDetail();toast('Canvi completat.');}
  catch(e){$('removal-status').textContent=e.message;removalPlan=null;}
  finally{removalBusy=false;$('removal-cancel').disabled=false;}
});

// Compact detail: keep destructive actions alongside player controls, annotation tools on the right.
const actionPanel=$('exclude-video').parentElement;$('player').parentElement.append(actionPanel);
let folderRulePlan=null;
async function prepareFolderRule(root,folder='',remove=false){
 await flushAll();folderRulePlan=await api('/api/folder-exclusions/preview','POST',{root_id:root,folder,remove});
 $('folder-exclude-title').textContent=remove?'Retira l’exclusió de carpeta':'Exclou aquesta carpeta';
 $('folder-exclude-summary').textContent=folderRulePlan.label+' · '+folderRulePlan.count+' vídeos actuals. '+(remove?'Es retirarà aquesta regla.':'S’amagaran també les subcarpetes i els vídeos nous que s’hi afegeixin.');$('folder-exclude-status').textContent='';$('folder-exclude-dialog').showModal();
}
$('exclude-folder').onclick=safe(()=>prepareFolderRule(state.root,state.folder));
$('folder-exclude-cancel').onclick=()=>$('folder-exclude-dialog').close();
async function renderFolderRules(){const rules=await api('/api/folder-exclusions');$('folder-rules').replaceChildren();if(!rules.length)$('folder-rules').textContent='No hi ha carpetes excloses.';for(const r of rules){const row=element('div','folder-rule');row.append(element('span','',r.label+(r.folder?' / '+r.folder:' (tota)')));const b=element('button','quiet','Torna a incloure');b.onclick=safe(()=>prepareFolderRule(r.root_id,r.folder,true));row.append(b);$('folder-rules').append(row);}}
$('settings-button').addEventListener('click',safe(renderFolderRules));
$('folder-exclude-confirm').onclick=safe(async()=>{if(!folderRulePlan)return;$('folder-exclude-confirm').disabled=true;try{await api('/api/folder-exclusions/confirm','POST',{token:folderRulePlan.token});$('folder-exclude-dialog').close();await load();await renderFolderRules();}catch(e){$('folder-exclude-status').textContent=e.message;}finally{$('folder-exclude-confirm').disabled=false;}});
$('video-type').onchange=safe(async()=>{await flushAll();state.current=await api('/api/videos/'+state.current.id,'PATCH',{video_type:$('video-type').value});toast('Tipus desat.');});
$('edit-date').onclick=()=>{const v=state.current;$('detected-date').textContent='Data detectada: '+(v.detected_at||'desconeguda')+'. La correcció només es desa al catàleg.';let dateValue=(v.date_override||v.recorded_at||'').slice(0,19);if(dateValue.length===10)dateValue+='T00:00:00';$('corrected-date').value=dateValue;$('date-dialog').showModal();};
$('date-cancel').onclick=()=>$('date-dialog').close();
async function saveDate(value){await flushAll();state.current=await api('/api/videos/'+state.current.id,'PATCH',{date_override:value});$('date-dialog').close();renderDetail();toast('Data desada al catàleg.');}
$('date-form').onsubmit=safe(async e=>{e.preventDefault();await saveDate($('corrected-date').value);});
$('date-reset').onclick=safe(()=>saveDate(null));
$('bulk-dates').onclick=()=>{$('shift-minutes').value='';$('shift-dialog').showModal();};
$('shift-cancel').onclick=()=>$('shift-dialog').close();
$('shift-form').onsubmit=safe(async e=>{e.preventDefault();await flushAll();await api('/api/bulk/shift-dates','POST',{ids:[...state.selected],minutes:Number($('shift-minutes').value)});$('shift-dialog').close();await load();toast('Dates corregides.');});

function unsupportedInBrowser(v){return !['h264','vp8','vp9','av1'].includes(v.codec)||!/\.(mp4|m4v|webm)$/i.test(v.relative_path);}

async function openDesktop(action){
 const v=state.current;if(!v)return;
 try{const result=await api('/api/videos/'+v.id+'/'+action,'POST',{});if(result.foreground===false)toast('Finestra oberta. Si Windows la manté darrere, selecciona-la a la barra de tasques.');}
 catch(e){$('desktop-copy').textContent='Copia la ruta';$('desktop-help-message').textContent=e.message;const relative=v.relative_path.replaceAll('/','\\');const folder=relative.includes('\\')?relative.slice(0,relative.lastIndexOf('\\')):'';$('desktop-help-path').value=v.root_path+(folder?'\\'+folder:'');$('desktop-help').showModal();}
}
$('desktop-help-close').onclick=()=>$('desktop-help').close();
$('desktop-copy').onclick=safe(async()=>{await navigator.clipboard.writeText($('desktop-help-path').value);$('desktop-copy').textContent='Ruta copiada';});
