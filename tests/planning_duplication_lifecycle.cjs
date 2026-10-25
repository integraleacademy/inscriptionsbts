/* Real DOM submit/click lifecycle: mocked HTTP only, no browser or production data. */
const fs = require('node:fs'), assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const html=spawnSync('python',['-c',`from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'<!doctype html><html><body>{% block content %}{% endblock %}</body></html>'}),FileSystemLoader('templates')]))
print(env.get_template('planning_admin.html').render(csrf_token='fixture',promotions=[dict(id='p1',nom='BTS MOS 1',active=True)],selected_promotion='p1'))`],{encoding:'utf8'});
assert.equal(html.status,0,html.stderr);
const settle=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
const wire=value=>JSON.parse(JSON.stringify(value));
function setup(mode='weeks',blocked=false){
 const dom=new JSDOM(html.stdout,{url:'https://example.test/admin/planning?promotion_id=p1',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,d=w.document,$=id=>d.getElementById(id),calls=[];
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 w.HTMLElement.prototype.scrollIntoView=function(){};
 const promotion={id:'p1',nom:'BTS MOS 1',bts:'MOS',niveau:1,date_debut:'2027-01-01',date_fin:'2027-01-31',active:true};
 // An older page believed the subject was full; the fresh preview has freed hours.
 const staleSubject={id:'s1',promotion_id:'p1',name:'Prévention',trainer_id:'t1',planned_hours:4,planned_minutes:240,scheduled_minutes:240,remaining_minutes:0,budget_configured:true};
 const freshBudget={...staleSubject,scheduled_minutes:120,remaining_minutes:120};
 const days=Array.from({length:31},(_,i)=>({date:`2027-01-${String(i+1).padStart(2,'0')}`,kind:'school'}));
 const course={id:'source',version:1,promotion_id:'p1',subject_id:'s1',trainer_id:'t1',room_id:null,date:'2027-01-04',start:'08:00',end:'10:00',title:'Prévention',duration_minutes:120,groups:[{promotion_id:'p1',subject_id:'s1'}],shared:[]};
 const snapshot={promotion,subjects:[staleSubject],catalog:{promotions:[promotion],subjects:[staleSubject]},courses:[course],rules:[],exceptions:[],days,rooms:[],trainers:[],calendar_configured:true};
 const preview={ok:true,mode,preview_token:'signed-fixture',budgets:[freshBudget],items:[{key:'0',valid:!blocked,course:{...course,id:undefined,date:'2027-01-11'},conflicts:blocked?[{type:'trainer_unavailable',message:'Le formateur est indisponible.'}]:[]} ]};
 let pendingPreview;
 w.fetch=async(url,options)=>{calls.push({url,options});if(url.includes('/courses/preview'))return new Promise(resolve=>{pendingPreview=()=>resolve({ok:true,json:async()=>preview})});if(url.includes('/courses/batch'))return {ok:true,json:async()=>({ok:true,count:1,created_keys:['0'],skipped:[],message:'Cours créé.'})};return {ok:true,json:async()=>snapshot}};
 let source=fs.readFileSync('static/js/planning.js','utf8').replace('  loadState({initial: true});','  window.testPlanning={state,openBatch};');w.eval(source);
 const state=w.testPlanning.state;state.data=snapshot;state.week='2027-01-04';w.testPlanning.openBatch(mode==='weeks'?null:course);
 return {dom,w,d,$,state,calls,release:()=>pendingPreview(),preview};
}
(async()=>{
 let checks=0;
 for(const mode of ['weeks','dates']){
  const t=setup(mode);await settle();
  assert.equal(t.$('planning-batch-commit').disabled,true);assert.match(t.$('planning-batch-action-help').textContent,/Sélectionnez/);checks+=2;
  t.d.querySelector(mode==='weeks'?'[data-batch-week="2027-01-11"]':'[data-batch-date="2027-01-11"]').click();
  assert.equal(t.$('planning-batch-commit').disabled,false);assert.match(t.$('planning-batch-commit').textContent,/Vérifier/);checks+=2;
  // The footer itself performs the first verification step, not a disabled dead end.
  t.$('planning-batch-commit').click();await settle();
  assert.equal(t.calls.filter(x=>x.url.includes('/courses/preview')).length,1);assert.equal(t.$('planning-batch-commit').disabled,true);assert.match(t.$('planning-batch-action-help').textContent,/vérification/);checks+=3;
  t.release();await settle();
  assert.equal(t.$('planning-batch-commit').disabled,false,'fresh server budget must override stale catalog');
  assert.equal(t.$('planning-batch-commit').textContent,'Créer 1 cours');
  assert.equal(t.$('planning-batch-items').querySelector('input').disabled,false);
  assert.match(t.$('planning-batch-action-help').textContent,/prêt à créer/);checks+=4;
  t.$('planning-batch-commit').click();t.$('planning-batch-commit').click();await settle();
  const commits=t.calls.filter(x=>x.url.includes('/courses/batch'));assert.equal(commits.length,1);
  assert.deepEqual(JSON.parse(commits[0].options.body).selected_keys,['0']);assert.equal(t.$('planning-batch-dialog').open,false);checks+=3;t.dom.window.close();
 }
 const t=setup('weeks',true);await settle();t.d.querySelector('[data-batch-week="2027-01-11"]').click();t.$('planning-batch-commit').click();await settle();t.release();await settle();
 assert.equal(t.$('planning-batch-commit').disabled,true);assert.match(t.$('planning-batch-action-help').textContent,/Aucun cours ne peut être créé/);assert.match(t.$('planning-batch-items').textContent,/formateur est indisponible/);assert.equal(t.calls.filter(x=>x.url.includes('/courses/batch')).length,0);checks+=4;t.dom.window.close();
 console.log(`PASS: ${checks} duplication lifecycle checks (calendar selection, real submit, fresh budgets, busy controls, blockers, one commit).`);
})().catch(error=>{console.error(error);process.exitCode=1});
