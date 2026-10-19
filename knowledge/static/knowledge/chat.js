const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
const el = id => document.getElementById(id);
let conversation = null, selected = new Set(), busy = false;
async function api(url, options={}) {
  const response = await fetch(url, {...options, headers: {'X-CSRFToken':csrf, ...(options.headers || {})}});
  if (response.redirected) { window.location.href='/accounts/login/'; throw new Error('Please sign in again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The request failed. Please retry.');
  return data;
}
function text(tag, value, className='') { const n=document.createElement(tag); n.textContent=value; n.className=className; return n; }
function notice(message, error=false) { el('notice').textContent=message; el('notice').className=error?'error':''; }
async function refreshDocuments() {
  const data=await api('/documents/');
  const current=new Set(data.documents.filter(d=>d.status==='ready').map(d=>d.id));
  selected=new Set([...selected].filter(id=>current.has(id)));
  el('doc-count').textContent=`(${data.documents.length})`;
  const container=el('documents'); container.replaceChildren();
  if(!data.documents.length) container.append(text('p','No documents yet. Add your first file above.','muted small'));
  data.documents.forEach(doc=>{
    const row=text('div','','doc'), label=document.createElement('label'), check=document.createElement('input');
    check.type='checkbox'; check.disabled=doc.status!=='ready'; check.checked=selected.has(doc.id);
    check.addEventListener('change',()=>check.checked?selected.add(doc.id):selected.delete(doc.id));
    label.append(check,text('span',doc.name)); row.append(label,text('div',`${doc.status} · ${Math.ceil(doc.size/1024)} KB`,'state'));
    if(doc.error) row.append(text('div',doc.error,'error small'));
    const actions=text('div','','doc-actions'), link=text('a','Download'); link.href=`/documents/${doc.id}/download/`; actions.append(link);
    if(doc.status==='ready'||doc.status==='failed') { const retry=text('button',doc.status==='failed'?'Retry':'Re-index'); retry.type='button'; retry.onclick=()=>action(`/documents/${doc.id}/retry/`); actions.append(retry); }
    if(doc.status!=='processing') { const remove=text('button','Delete'); remove.type='button'; remove.onclick=async()=>{if(confirm(`Delete ${doc.name} and its indexed passages?`)) { await action(`/documents/${doc.id}/delete/`); if(conversation) await loadConversation(conversation); }}; actions.append(remove); }
    row.append(actions); container.append(row);
  });
}
async function action(url) { try { await api(url,{method:'POST'}); await refreshDocuments(); } catch(e) {notice(e.message,true);} }
async function refreshConversations() {
  const data=await api('/chat/conversations/'); el('conversations').replaceChildren();
  data.conversations.forEach(c=>{const button=text('button',c.title,'conversation'+(conversation===c.id?' active':''));button.onclick=()=>{if(!busy) loadConversation(c.id).catch(e=>notice(e.message,true));};el('conversations').append(button);});
}
function message(role,content,citations=[]) {
  const bubble=text('article','','bubble '+role); bubble.append(text('span',role==='user'?'YOU':'PAPERTRAIL','role'),text('p',content));
  citations.forEach(c=>{const details=document.createElement('details');details.append(text('summary',`[${c.id}] ${c.name}${c.page?' · page '+c.page:''}`),text('blockquote',c.excerpt));const link=text('a','Download source');link.href=`/documents/${c.document_id}/download/`;details.append(link);bubble.append(details);});
  el('messages').append(bubble); bubble.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function loadConversation(id) { const data=await api(`/chat/${id}/`); conversation=id;el('messages').replaceChildren();data.messages.forEach(m=>message(m.role,m.content,m.citations));await refreshConversations(); }
el('upload-form').addEventListener('submit',async event=>{event.preventDefault();el('upload-button').disabled=true;notice('Uploading…');try {const result=await api('/documents/upload/',{method:'POST',body:new FormData(event.target)});notice(`${result.count} file(s) queued. Keep the indexing worker running. Select them once ready.`);event.target.reset();await refreshDocuments();} catch(e){notice(e.message,true);}finally{el('upload-button').disabled=false;}});
el('new-chat').onclick=()=>{if(busy)return;conversation=null;el('messages').replaceChildren();message('assistant','A fresh conversation. Select your sources and ask a question.');refreshConversations().catch(e=>notice(e.message,true));};
el('chat-form').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;if(!selected.size){notice('Select at least one ready document first.',true);return;}const question=el('question').value.trim();if(!question)return;busy=true;el('send').disabled=true;el('send').textContent='Thinking…';notice('Retrieving passages and generating an answer…');try {const data=await api('/chat/message/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,document_ids:[...selected],conversation_id:conversation})});if(!conversation)el('messages').replaceChildren();conversation=data.conversation_id;message('user',question);message('assistant',data.answer,data.citations);el('question').value='';notice('Answer ready. Expand the citations to check the passages.');await refreshConversations();}catch(e){notice(e.message,true);}finally{busy=false;el('send').disabled=false;el('send').textContent='Ask question ↗';}});
Promise.all([refreshDocuments(),refreshConversations()]).catch(e=>notice(e.message,true));
setInterval(()=>{if(!document.hidden)refreshDocuments().catch(e=>notice(e.message,true));},5000);
