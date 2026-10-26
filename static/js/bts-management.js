(() => {
  const sheet=document.querySelector('.candidate-sheet'), cid=sheet?.dataset.candidateId;
  const dialog=document.getElementById('management-dialog'), title=document.getElementById('management-dialog-title'), body=document.getElementById('management-dialog-body'), confirm=document.getElementById('management-dialog-confirm'), error=document.getElementById('management-dialog-error');
  const toastBox=document.getElementById('management-toast');let toastTimer;
  const $=selector=>document.querySelector(selector);
  const text=(tag,content,cls)=>{const el=document.createElement(tag);el.textContent=content;if(cls)el.className=cls;return el;};
  function toast(message,bad=false){clearTimeout(toastTimer);toastBox.textContent=message;toastBox.classList.toggle('error',bad);toastBox.hidden=false;toastTimer=setTimeout(()=>toastBox.hidden=true,5000);}
  async function api(path,options={}){const response=await fetch(path,{...options,headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}});const data=await response.json().catch(()=>({}));if(!response.ok||data.ok===false)throw Error(data.error||`Action impossible (${response.status}).`);return data;}
  const post=(path,data={})=>api(path,{method:'POST',headers:{'X-CSRF-Token':dialog.dataset.messageCsrf},body:JSON.stringify(data)});
  const campaign=path=>{const url=new URL(path,location.origin);url.searchParams.set('rentree',new URLSearchParams(location.search).get('rentree')||sheet?.dataset.year||'2027');return url.pathname+url.search;};
  function modal(heading,description,action,options={}){
    dialog.classList.remove('is-preview');title.textContent=heading;body.replaceChildren(text('p',description));error.hidden=true;confirm.textContent=options.label||'Confirmer';confirm.classList.toggle('danger',!!options.danger);confirm.disabled=false;
    options.build?.(body);confirm.onclick=async()=>{dialog.dataset.busy='true';confirm.disabled=true;error.hidden=true;try{if(await action(body)!==false)dialog.close();}catch(e){error.textContent=e.message;error.hidden=false;}finally{confirm.disabled=false;delete dialog.dataset.busy;}};
    dialog.showModal();
  }
  dialog.querySelectorAll('[data-dialog-cancel]').forEach(button=>button.addEventListener('click',()=>{if(dialog.dataset.busy!=='true')dialog.close();}));
  dialog.addEventListener('cancel',event=>{if(dialog.dataset.busy==='true')event.preventDefault();});
  dialog.addEventListener('click',event=>{if(event.target===dialog&&dialog.dataset.busy!=='true'){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  function selectField(container,label,choices,name='action') {const field=document.createElement('label');field.className='sheet-field';field.append(text('span',label));const select=document.createElement('select');select.name=name;for(const [value,caption]of choices){const option=text('option',caption);option.value=value;select.append(option);}field.append(select);container.append(field);return select;}
  function textarea(container,label,name){const field=document.createElement('label');field.className='sheet-field';field.append(text('span',label));const input=document.createElement('textarea');input.name=name;input.rows=4;field.append(input);container.append(field);return input;}
  function previewModal(heading,description,path,getData=()=>({}),options={}) {
    let token='',approvedData=null,preview;
    const invalidate=()=>{token='';approvedData=null;preview?.remove();confirm.textContent='Prévisualiser';dialog.classList.remove('is-preview');};
    modal(heading,description,async container=>{
      if(!token){
        const data=getData(container),inputs=[...container.querySelectorAll('select,textarea,input')];
        inputs.forEach(input=>input.disabled=true);
        try{
          const result=await post(path,{...data,preview:true});
          if(!result.preview_token)throw Error('Impossible de préparer l’aperçu.');
          token=result.preview_token;approvedData=data;
          preview=document.createElement('div');preview.className='workflow-preview';
          const display=document.createElement('div');
          const render=item=>{
            display.replaceChildren(text('h3',item.name));
            (item.warnings||[]).forEach(warning=>display.append(text('p',warning,'workflow-warning')));
            if(!item.messages.length)display.append(text('p','Ce changement ne déclenche aucun message.'));
            const panels=document.createElement('div');panels.className='workflow-panels';
            for(const file of item.files||[]){
              const section=document.createElement('section');section.className='workflow-pdf';
              const link=text('a','Ouvrir le certificat PDF','btn');link.href=file.url;link.target='_blank';link.rel='noopener';
              const frame=document.createElement('iframe');frame.src=file.url;frame.title='Certificat de scolarité joint au message';
              section.append(text('h4','Pièce jointe · PDF'),link,frame);panels.append(section);
            }
            for(const message of item.messages){
              const section=document.createElement('section');section.className='workflow-'+message.type;
              section.append(text('h4',message.type==='email'?'Aperçu de l’e-mail':'Aperçu du SMS'),text('p','Destinataire : '+message.recipient));
              if(message.type==='email'){
                section.append(text('p','Objet : '+message.subject));
                if(message.copy)section.append(text('small','Copie : '+message.copy));
                const frame=document.createElement('iframe');frame.setAttribute('sandbox','');frame.referrerPolicy='no-referrer';frame.title='Aperçu du message avant envoi';frame.srcdoc=message.html;section.append(frame);
              }else section.append(text('pre',message.body));
              panels.append(section);
            }
            display.append(panels);
          };
          if(result.dossiers.length>1){
            const picker=selectField(preview,`${result.dossiers.length} dossiers · Consultez les messages de chaque destinataire`,result.dossiers.map((item,i)=>[String(i),item.name]),'preview-dossier');
            picker.addEventListener('change',()=>render(result.dossiers[Number(picker.value)]));
          }
          preview.append(display,text('p','Aucun message n’a encore été envoyé. Confirmez après avoir relu les aperçus.','workflow-note'));
          render(result.dossiers[0]);container.append(preview);dialog.classList.add('is-preview');
          confirm.textContent=options.sendLabel||'Confirmer et envoyer';
        }finally{inputs.forEach(input=>input.disabled=false);}
        return false;
      }
      const result=await post(path,{...approvedData,preview_token:token});
      toast(result.message||'Envoi confirmé.');options.after?.(result);loadHistory();
    },{label:'Prévisualiser',build:container=>{
      options.build?.(container);
      container.querySelectorAll('select,textarea,input').forEach(input=>input.addEventListener('input',invalidate));
    }});
  }
  async function loadHistory(){
    const list=$('#candidate-history');if(!list)return;list.replaceChildren(text('li','Chargement de l’historique…'));
    try{const entries=await api(`/admin/logs/${encodeURIComponent(cid)}`);list.replaceChildren();const labels={FIELD_UPDATE:'Information modifiée',FICHE_MODIFIEE:'Fiche mise à jour',STATUT_CHANGE:'Statut modifié',STATUT_MODIFIE:'Statut modifié',MAIL_ENVOYE:'E-mail envoyé',SMS_ENVOYE:'SMS envoyé',DOC_MARK:'Contrôle d’un document',DOC_GENERE:'Document généré',PDF_GENERE:'Fiche PDF générée',RELANCE_ENVOYEE:'Relance envoyée'};for(const entry of entries){const item=document.createElement('li');item.append(text('b',labels[entry.type]||entry.type.replaceAll('_',' ').toLowerCase()),text('time',formatDate(entry.created_at)),text('p',entry.payload||''));list.append(item);}if(!entries.length)list.append(text('li','Aucune action enregistrée pour le moment.'));}catch(e){list.replaceChildren(text('li',e.message));}
  }
  function formatDate(value){if(!value)return'—';const d=new Date(value);return Number.isNaN(d.getTime())?value:d.toLocaleString('fr-FR',{dateStyle:'medium',timeStyle:'short'});}
  async function loadFiles(){
    const list=$('#candidate-files');if(!list)return;list.replaceChildren(text('p','Chargement des pièces…'));
    try{const files=await api(`/admin/files/${encodeURIComponent(cid)}`);list.replaceChildren();for(const file of files){const item=document.createElement('article');item.className='sheet-document';const info=document.createElement('div');info.append(text('b',file.label||'Pièce justificative'));const link=text('a',file.filename);link.href=file.url||`/admin/candidat/${encodeURIComponent(cid)}/document/${encodeURIComponent(file.filename)}`;link.target='_blank';link.rel='noopener';info.append(link,text('small',({conforme:'Conforme',non_conforme:'Non conforme',nouveau:'Nouveau document',en_attente:'À contrôler'})[file.status]||'À contrôler'));if(file.horodatage)info.append(text('small',file.horodatage));item.append(info);const actions=document.createElement('div');actions.className='document-decisions';if(file.type!=='nouveau'){for(const [decision,label]of [['conforme','Conforme'],['non_conforme','Non conforme']]){const button=text('button',label,'btn');button.type='button';button.disabled=file.status===decision;button.addEventListener('click',()=>{const execute=async()=>{await post('/admin/files/mark',{id:cid,filename:file.filename,decision});if(decision==='non_conforme')setStatus('docs_non_conformes');await loadFiles();toast('Décision enregistrée.');};if(decision==='non_conforme')modal('Marquer la pièce non conforme',`La pièce « ${file.filename} » sera retirée du dossier. Vous pourrez ensuite demander son remplacement au candidat.`,execute,{label:'Marquer non conforme'});else busy(button,execute);});actions.append(button);}}else actions.append(text('span','À enregistrer dans les pièces','new-document'));item.append(actions);list.append(item);}if(!files.length)list.append(text('p','Aucun justificatif disponible pour ce dossier.'));}catch(e){list.replaceChildren(text('p',e.message));}
  }
  async function busy(button,work){button.disabled=true;try{await work();}catch(e){toast(e.message,true);}finally{button.disabled=false;}}
  function tab(key,updateURL=true){
    if(!sheet||!document.getElementById('panel-'+key))return;
    sheet.querySelectorAll('.sheet-panel').forEach(panel=>panel.hidden=panel.id!=='panel-'+key);
    sheet.querySelectorAll('.sheet-tabs [role=tab]').forEach(button=>{const active=button.dataset.tabTarget===key;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
    if(updateURL)history.replaceState({},'',location.pathname+location.search+'#'+key);
    if(key==='documents')loadFiles();if(key==='historique')loadHistory();
  }
  document.querySelectorAll('[data-tab-target]').forEach(button=>button.addEventListener('click',()=>tab(button.dataset.tabTarget)));
  document.querySelectorAll('.sheet-tabs [role=tab]').forEach(button=>button.addEventListener('keydown',event=>{if(!['ArrowRight','ArrowLeft','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...document.querySelectorAll('.sheet-tabs [role=tab]')],current=buttons.indexOf(button);const i=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[i].focus();tab(buttons[i].dataset.tabTarget);}));
  function setStatus(value){const select=$('#candidate-status');if(select){select.value=value;select.dataset.current=value;}}
  if(sheet){
    tab(location.hash.slice(1)||'informations',false);
    $('#refresh-history')?.addEventListener('click',loadHistory);
    $('#candidate-status').addEventListener('change',event=>{const select=event.target,old=select.dataset.current,value=select.value;if(old===value)return;previewModal('Changer le statut du dossier',`Passer le dossier à « ${select.selectedOptions[0].textContent} ». Vérifiez les notifications associées avant de confirmer.`, '/admin/update-status',()=>({id:cid,value}),{sendLabel:'Confirmer le changement',after:()=>setStatus(value)});dialog.addEventListener('close',()=>{if(select.dataset.current===old)select.value=old;},{once:true});});
    $('[data-candidate-id]').querySelectorAll('[data-label-field]').forEach(input=>input.addEventListener('change',()=>{const checked=input.checked;busy(input,async()=>{try{await post('/admin/update-field',{id:cid,field:input.dataset.labelField,value:checked});toast('Suivi enregistré.');}catch(e){input.checked=!checked;throw e;}});}));
    $('#save-candidate-comment').addEventListener('click',event=>busy(event.currentTarget,async()=>{await post('/admin/update-field',{id:cid,field:'commentaires',value:$('#candidate-comment').value});toast('Note enregistrée.');}));
    const form=$('#candidate-information-form'),fields=$('#candidate-information-fields'),edit=$('#edit-candidate'),controls=$('#candidate-edit-actions');
    const editing=value=>{fields.disabled=!value;edit.hidden=value;controls.hidden=!value;};
    edit.addEventListener('click',()=>{editing(true);fields.querySelector('select,input')?.focus();});
    $('#cancel-edit').addEventListener('click',()=>{form.reset();editing(false);});
    form.addEventListener('submit',async event=>{event.preventDefault();const button=controls.querySelector('[type=submit]');await busy(button,async()=>{await post(`/admin/candidat/${encodeURIComponent(cid)}/informations`,Object.fromEntries(new FormData(form)));toast('Fiche enregistrée.');location.reload();});});
    document.querySelectorAll('[data-certificate]').forEach(button=>button.addEventListener('click',()=>previewModal('Envoyer le certificat de scolarité','Le certificat PDF et son e-mail sont préparés à partir du parcours actuel de l’étudiant.',`/admin/send_certificat/${encodeURIComponent(cid)}`)));
    document.querySelectorAll('[data-change-mode]').forEach(button=>button.addEventListener('click',()=>modal('Changer le parcours','Le certificat et les prochains messages utiliseront ce parcours. Aucun message ne sera envoyé par ce changement.',async container=>{await post(`/admin/candidat/${encodeURIComponent(cid)}/parcours`,{mode:container.querySelector('select').value});location.reload();},{label:'Enregistrer le parcours',build:container=>{selectField(container,'Parcours suivi',[['presentiel','Présentiel'],['distanciel','Distanciel']],'mode').value=sheet.dataset.mode;}})));
  }
  const resendChoices=[['candidature_validee','Candidature validée'],['inscription_confirmee','Inscription confirmée'],['reconfirmation','Demande de reconfirmation'],['reconfirmee','Inscription reconfirmée'],['docs_non_conformes','Documents non conformes']];
  const remindChoices=[['candidature_validee','Candidature validée sans confirmation'],['reconfirmation','Reconfirmation en attente'],['docs_non_conformes','Pièces toujours manquantes']];
  document.querySelectorAll('[data-management]').forEach(button=>button.addEventListener('click',async()=>{
    document.querySelectorAll('.directory-tools,.sheet-actions-menu').forEach(menu=>menu.open=false);
    try{switch(button.dataset.management){
      case'delete':modal('Supprimer ce dossier','Cette suppression est définitive. Seul le dossier de cette personne sera supprimé.',async()=>{await post(`/admin/delete/${encodeURIComponent(cid)}`);location.assign('/admin?rentree='+sheet.dataset.year);},{label:'Supprimer le dossier',danger:true});break;
      case'reconfirm':previewModal('Demander la reconfirmation','Vérifiez l’e-mail et le SMS destinés à l’étudiant.',`/admin/reconfirm/${encodeURIComponent(cid)}`,()=>({}),{after:()=>setStatus('reconf_en_cours')});break;
      case'aps':previewModal('Message APS','Vérifiez le message correspondant à son parcours APS.',`/admin/send_mail_aps/${encodeURIComponent(cid)}`);break;
      case'resend':case'remind':{const resend=button.dataset.management==='resend';previewModal(resend?'Renvoyer un message':'Relancer le candidat','Choisissez le modèle, puis consultez l’aperçu de l’e-mail et du SMS.',`/admin/${resend?'resend_mail_sms':'relance'}/${encodeURIComponent(cid)}`,container=>({action:container.querySelector('select[name=action]').value}),{build:container=>selectField(container,'Message',resend?resendChoices:remindChoices)});break;}
      case'checked-files':await post('/admin/update-field',{id:cid,field:'nouveau_doc',value:0});document.querySelectorAll('.new-doc-dot').forEach(el=>el.remove());toast('Contrôle des nouveaux documents enregistré.');break;
      case'merge-files':modal('Enregistrer les nouveaux documents','Les nouvelles versions remplaceront les anciennes pièces correspondantes.',async()=>{await post('/admin/files/merge',{id:cid});await loadFiles();toast('Nouveaux documents enregistrés.');},{label:'Enregistrer les documents'});break;
      case'notify-documents':previewModal('Demander le remplacement des pièces','Vérifiez les pièces demandées et les messages avant envoi.','/admin/files/notify',container=>({id:cid,commentaire:container.querySelector('textarea').value}),{after:()=>setStatus('docs_non_conformes'),build:container=>textarea(container,'Précisions pour le candidat (facultatif)','commentaire')});break;
      case'bulk-remind':case'bulk-reconfirm':{const remind=button.dataset.management==='bulk-remind';previewModal(remind?'Relancer les candidatures validées':'Demander les reconfirmations','Les aperçus présentent les destinataires et les messages de la rentrée sélectionnée.',campaign('/admin/'+(remind?'relance_all_validated':'reconfirm_all')),()=>({}),{after:refreshDirectory});break;}
      case'portal':{const state=await api('/get_portal_status');modal('Paramètres des inscriptions','L’ouverture est programmée le 1er décembre 2026 à 10 h, heure de Paris. Vous pouvez suspendre les inscriptions après cette date.',async body=>{await post('/set_portal_status',{status:body.querySelector('select').value,message:body.querySelector('textarea').value,comment:''});toast('Paramètres enregistrés.');},{label:'Enregistrer',build:body=>{const select=selectField(body,'Disponibilité du formulaire',[['open','Ouverture automatique à la date prévue'],['closed','Suspendre les inscriptions']]);select.value=state.campaign_year===2027?state.status:'open';const message=textarea(body,'Message en cas de suspension','message');message.value=state.campaign_year===2027?state.message||'':'';}});break;}
      case'clear-database':modal('Vider toute la base','Tous les candidats, documents et historiques de toutes les rentrées seront supprimés. Saisissez SUPPRIMER pour confirmer.',async body=>{if(body.querySelector('input').value!=='SUPPRIMER')throw Error('Saisissez exactement SUPPRIMER.');const response=await fetch('/admin/clear-db',{method:'POST'});if(!response.ok)throw Error('La suppression a échoué.');location.assign('/admin');},{label:'Vider toute la base',danger:true,build:body=>{const input=document.createElement('input');input.autocomplete='off';input.setAttribute('aria-label','Confirmation de suppression');body.append(input);}});break;
    }}catch(e){toast(e.message,true);}
  }));
  async function metrics(){try{const stats=await api(campaign('/api/kpi'));document.querySelectorAll('[data-metric]').forEach(el=>el.textContent=stats[el.dataset.metric]??0);}catch(e){toast(e.message,true);}}
  let refreshing=false;
  async function refreshDirectory(){if(refreshing||!$('#directory-rows')||dialog.open||document.querySelector('.directory-tools[open]'))return;refreshing=true;try{const response=await fetch(location.pathname+location.search,{headers:{Accept:'text/html'}});if(!response.ok)throw Error('Actualisation impossible.');const doc=new DOMParser().parseFromString(await response.text(),'text/html'),rows=doc.getElementById('directory-rows');if(!rows)throw Error('Reconnectez-vous pour actualiser les candidatures.');$('#directory-rows').replaceChildren(...rows.childNodes);$('#directory-count').textContent=doc.getElementById('directory-count').textContent;await metrics();}catch(e){toast(e.message,true);}finally{refreshing=false;}}
  if($('#directory-rows')){
    metrics();$('#directory-refresh').addEventListener('click',()=>{document.querySelector('.directory-tools').open=false;refreshDirectory();});
    document.addEventListener('click',event=>{const row=event.target.closest('[data-candidate-url]');if(row&&!event.target.closest('a,button,input,select'))location.assign(row.dataset.candidateUrl);});
    setInterval(()=>{if($('#directory-live').checked&&!document.hidden&&!document.activeElement?.matches('input,select'))refreshDirectory();},60000);
  }
})();
