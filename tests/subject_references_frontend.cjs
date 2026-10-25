/* Render the real template and exercise the complete import journey with synthetic data. */
const fs = require('fs'), assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
require('child_process').execFileSync('python', ['tests/render_subject_reference_fixture.py'], {stdio:'pipe'});
const html = fs.readFileSync('tmp/reference-qa/matieres.html','utf8');
const catalog = JSON.parse(fs.readFileSync('tmp/reference-qa/catalog.json','utf8'));
const URL = 'https://www.legifrance.gouv.fr/loda/id/JORFTEXT000041728741';
const dom = new JSDOM(html, {url:'https://example.test/admin/matieres?promotion_id=demo',runScripts:'outside-only',pretendToBeVisual:true});
const w = dom.window, d=w.document, $=id=>d.getElementById(id);
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
let configured=false, polls=0, imports=0, keyPayload=null, importPayload=null, editPayload=null, job=null;
const recovering = process.env.REFERENCE_RECOVERY === '1';
let analyses=0, recoveries=0;
const settings=()=>({ok:true,configured,managed_by_server:false,bts_options:{MOS:'BTS Management opérationnel de la sécurité'},suggested_urls:{MOS:URL}});
const subject=(id,name,optional=false)=>({row_id:id,name,exam_unit:'U'+id,coefficient:3,optional,weekly_hours_first:2,weekly_hours_second:2,objectives:'Objectifs officiels',pedagogical_content:'Contenu officiel',exam_format:'Écrit',source_url:URL,source_label:'Annexe II c',evidence:'Coefficient 3',review_note:''});
const preview={qualification:'BTS MOS',reference_title:'Référentiel officiel',reference_version:'Test 2028',warnings:['Vérifier les coefficients.'],subjects:[subject('1','Culture générale'),subject('2','Management des ressources humaines'),subject('3','Langue facultative',true),{...subject('4','Matière non confirmée'),importable:false,source_issue:'Source non confirmée'}]};
const fullVersion='Version consultée. '.repeat(80)+'Réserve finale pour 2029 <img src=x onerror=alert(1)>';
const fullObjectives='Objectif pédagogique complet. '.repeat(500)+'Dernière précision à conserver.';
preview.full_text={'Version du référentiel':fullVersion};
preview.subjects[1].full_text={'Objectifs et compétences':fullObjectives};
let reloads=0;w.addEventListener('catalog:reload',()=>reloads++);
w.fetch=async(url,options={})=>{
 const method=options.method||'GET',data=options.body?JSON.parse(options.body):null;
 if(url==='/admin/planning/api/catalog')return response(catalog);
 if(url.endsWith('/references/settings')){
   if(method==='PUT'){keyPayload=data;configured=true}
   if(method==='DELETE')configured=false;
   return response(settings());
 }
 if(url.endsWith('/references/latest'))return response({ok:true,job});
 if(url.endsWith('/references/job-demo/recover')){assert.equal(method,'POST');recoveries++;job={...job,status:'ready',preview};return response(job)}
 if(url.endsWith('/references/analyze')){
   analyses++;
   assert.equal(data.source_url,URL);assert.equal(data.exam_year,2028);assert.equal(data.promotion_id,'demo');
   job={ok:true,job_id:'job-demo',status:'queued',promotion_id:'demo',query:{}};return response(job);
 }
 if(url.endsWith('/references/job-demo/import')){
   imports++;importPayload=data;job.status='imported';
   catalog.subjects.push({id:'imported',promotion_id:'demo',promotion_name:'BTS MOS',trainer_id:'',trainer_name:'',name:data.subjects[0].name,color:'#2563eb',planned_hours:null,scheduled_minutes:0,planned_minutes:null,budget_configured:false,import_id:'job-demo',...data.subjects[0],source_url:URL,reference_full_text:preview.full_text,full_text:preview.subjects[1].full_text});
   return response({ok:true,count:data.subjects.length,promotion_id:'demo',message:'Import terminé.'});
 }
 if(url.endsWith('/references/job-demo')){polls++;job={...job,status:'ready',preview};return response(job)}
 if(url.endsWith('/subjects/imported')&&method==='PUT'){editPayload=data;return response({ok:true,message:'Matière mise à jour.'})}
 throw new Error('Unexpected request '+method+' '+url);
};
function response(data){return {ok:true,json:async()=>data}}
const wait=()=>new Promise(r=>setTimeout(r,15));
const input=(el,value)=>{el.value=value;el.dispatchEvent(new w.Event('input',{bubbles:true}))};
const change=el=>el.dispatchEvent(new w.Event('change',{bubbles:true}));
const submit=id=>$(id).dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
w.eval(fs.readFileSync('static/js/planning-catalog.js','utf8'));
w.eval(fs.readFileSync('static/js/subject-references.js','utf8'));
(async()=>{
 await wait();$('reference-open').click();await wait();
 assert($('reference-dialog').open);assert.equal($('reference-qualification').value,'BTS Management opérationnel de la sécurité');
 assert.equal($('reference-url').value,URL);assert.equal($('reference-exam-year').value,'2028');assert($('reference-analyze').disabled);assert(!$('reference-settings-link').hidden);
 assert(!$('reference-key'));assert(!$('reference-settings'));assert.equal($('reference-settings-link').getAttribute('href'),'/admin/parametres');
 $('reference-close').click();configured=true;
 if(recovering)job={ok:true,job_id:'job-demo',status:'failed',promotion_id:'demo',query:{},recoverable:true};
 $('reference-open').click();await wait();assert(!$('reference-analyze').disabled);
 if(!recovering){
   submit('reference-search-form');await wait();assert(!$('reference-progress-step').hidden);assert.equal(catalog.subjects.length,1);
   $('reference-retry-poll').click();await wait();assert.equal(polls,1);assert.equal(analyses,1);
 }else{assert.equal(analyses,0);assert.equal(recoveries,1)}
 assert(!$('reference-review-step').hidden);
 const cards=[...d.querySelectorAll('.reference-subject')];assert.equal(cards.length,4);
 assert.equal($('reference-complete-text').querySelector('.reference-full-paragraph').textContent,fullVersion);
 assert.equal(cards[1].querySelector('.reference-full-paragraph').textContent,fullObjectives);
 assert.equal($('reference-dialog').querySelectorAll('img').length,0);
 const checks=cards.map(c=>c.querySelector('.reference-row-choice input'));
 assert(checks[0].disabled&&!checks[0].checked);assert(checks[1].checked);assert(!checks[2].checked);assert(checks[3].disabled&&!checks[3].checked);
 $('reference-select-all').click();assert(!checks[3].checked);$('reference-select-none').click();checks[1].checked=true;change(checks[1]);
 assert($('reference-import').disabled);assert.equal($('reference-selection-count').textContent,'1 matière sélectionnée');
 $('reference-reviewed').checked=true;change($('reference-reviewed'));assert(!$('reference-import').disabled);
 input(cards[1].querySelector('[data-field="name"]'),'Management adapté');assert(!$('reference-reviewed').checked);assert($('reference-import').disabled);
 input(cards[1].querySelector('[data-field="coefficient"]'),'5');input(cards[1].querySelector('[data-field="objectives"]'),'Objectifs ajustés');
 assert(w.sessionStorage.getItem('bts-reference-draft:job-demo').includes('Management adapté'));
 // Hostile content is plain text, never interpreted as markup.
 input(cards[1].querySelector('[data-field="objectives"]'),'<img src=x onerror=alert(1)>');assert.equal(d.querySelectorAll('.reference-subject img').length,0);
 $('reference-reviewed').checked=true;change($('reference-reviewed'));$('reference-import').click();await wait();
 assert.equal(imports,1);assert.equal(importPayload.subjects.length,1);assert.equal(importPayload.subjects[0].name,'Management adapté');assert.equal(importPayload.subjects[0].coefficient,5);
 assert.equal(importPayload.subjects[0].planned_hours,null);assert.equal(importPayload.subjects[0].trainer_id,'');assert(importPayload.reviewed);assert.equal(reloads,1);assert(!$('reference-done-step').hidden);
 assert.equal(w.sessionStorage.getItem('bts-reference-draft:job-demo'),null);
 $('reference-bottom-close').click();await wait();
 d.querySelector('[data-catalog-edit="imported"]').click();await wait();
 const form=$('catalog-form');assert(!$('catalog-save').disabled);assert(!form.elements.planned_hours.required);assert(!form.elements.trainer_id.required);
 const preserved=[...$('catalog-editor').querySelectorAll('.reference-full-paragraph')].map(n=>n.textContent);
 assert.deepEqual(preserved,[fullVersion,fullObjectives]);assert.equal($('catalog-editor').querySelectorAll('img').length,0);
 assert.equal(form.elements.coefficient.value,'5');form.elements.objectives.value='Après import';submit('catalog-form');await wait();
 assert.equal(editPayload.planned_hours,null);assert.equal(editPayload.objectives,'Après import');assert.equal(editPayload.coefficient,5);
 assert(!$('catalog-editor').open);
 console.log('PASS: complete reference import journey, key isolation, pending/ready states, duplicate and optional selection, long text preserved before/after import, safe text, drafts, selected-only commit, catalogue refresh and post-import editing.');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
