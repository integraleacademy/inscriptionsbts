/* DOM interaction regression checks; no browser, remote resources or business writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const rendered = spawnSync('python', ['-c', `from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader
from types import SimpleNamespace
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'<!doctype html><html><body>{% block content %}{% endblock %}</body></html>'}),FileSystemLoader('templates')]))
print(env.get_template('planning_admin.html').render(csrf_token='test-only',promotions=[dict(id='p1',nom='BTS MOS 1',active=True)],selected_promotion='p1'))`], {encoding:'utf8'});
assert.equal(rendered.status, 0, rendered.stderr);
const dom = new JSDOM(rendered.stdout, {url:'https://example.test/admin/planning?promotion_id=p1',runScripts:'outside-only',pretendToBeVisual:true});
const {window:w}=dom, d=w.document;
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
w.HTMLElement.prototype.scrollIntoView=function(){};
let calls=[];
w.fetch=async(url,options)=>{calls.push({url,options});throw Error('Unexpected network call in test');};
let source=fs.readFileSync('static/js/planning.js','utf8');
source=source.replace('  loadState({initial: true});', `  window.planningTest={state,openBatch,setBatchMode,renderBatchWeekCalendar,setBatchWeek,batchPreviewPayload,renderBatchPreview,updateBatchCommit,batchReportData,showBatchReport,setPlanningFullscreen,togglePlanningFullscreen,planningSyncSafe,loadState,refreshChangedPlanning};`);
w.eval(source);
const a=w.planningTest, $=id=>d.getElementById(id), wire=value=>JSON.parse(JSON.stringify(value));
const promotion={id:'p1',nom:'BTS MOS 1',bts:'MOS',date_debut:'2027-05-01',date_fin:'2027-05-31'};
const subject={id:'s1',promotion_id:'p1',name:'Prévention',trainer_id:'t1',planned_hours:100,planned_minutes:6000,scheduled_minutes:120,remaining_minutes:5880};
const days=Array.from({length:31},(_,i)=>{const date=`2027-05-${String(i+1).padStart(2,'0')}`;return {date,kind:['2027-05-06','2027-05-17'].includes(date)?'public_holiday':'school',label:date==='2027-05-17'?'Lundi de Pentecôte':''};});
const course={id:'c1',version:3,date:'2027-05-03',start:'08:00',end:'10:00',subject_id:'s1',promotion_id:'p1',trainer_id:'t1',room_id:'r1',subject_name:'Prévention',groups:[{subject_id:'s1',promotion_id:'p1'}]};
a.state.data={promotion,subjects:[subject],catalog:{promotions:[promotion],subjects:[subject]},courses:[course]};
// Match loadState's visible workspace so focus tests exercise real inputs.
$('planning-selected').hidden=false;$('planning-unselected').hidden=true;
a.state.week='2027-05-03';
a.state.batch={mode:'weeks',sourceWeek:'2027-05-03',promotionId:'p1',course:null,calendar:{promotion,days},dates:new w.Set(),weeks:new w.Set(),calendarLoading:false};
a.setBatchMode('weeks');a.renderBatchWeekCalendar();
let checks=0;
async function run(){
  // Whole weeks stay clickable even when one or several days cannot receive courses.
  assert.equal($('planning-batch-weeks-fields').hidden,false);
  assert.equal($('planning-batch-dates-fields').hidden,true);
  assert.equal($('planning-batch-repeat-fields').hidden,true);
  const sourceWeek=d.querySelector('[data-batch-week="2027-05-03"]'),holidayWeek=d.querySelector('[data-batch-week="2027-05-17"]');
  assert.equal(sourceWeek.disabled,true);assert.equal(holidayWeek.disabled,false);
  assert.ok(holidayWeek.querySelector('.kind-public_holiday'));
  holidayWeek.click();assert.equal(a.state.batch.weeks.has('2027-05-17'),true);assert.equal(holidayWeek.getAttribute('aria-pressed'),'true');
  assert.match($('planning-batch-week-count').textContent,/1 semaine sélectionnée/);
  assert.equal($('planning-batch-preview').disabled,false);
  a.setBatchWeek('2027-05-24',true);
  assert.deepEqual(wire(a.batchPreviewPayload($('planning-batch-form'))),{promotion_id:'p1',mode:'weeks',source_start:'2027-05-03',target_weeks:['2027-05-17','2027-05-24']});
  a.state.batch.preview={preview_token:'old'};holidayWeek.click();assert.equal(a.state.batch.preview,null);
  a.setBatchWeek('2027-05-03',true);assert.equal(a.state.batch.weeks.has('2027-05-03'),false);
  a.setBatchWeek('2027-06-07',true);assert.equal(a.state.batch.weeks.has('2027-06-07'),false);
  $('planning-batch-week-clear').click();assert.equal(a.state.batch.weeks.size,0);assert.equal($('planning-batch-preview').disabled,true);
  assert.throws(()=>a.batchPreviewPayload($('planning-batch-form')),/semaine/);checks+=17;

  // Weekly repetitions send the saved Zoom URL with the course's other resources.
  const weekBatch=a.state.batch;
  a.state.batch={...weekBatch,course:{...course,zoom_url:'https://school.zoom.us/j/123?pwd=promo'}};
  a.setBatchMode('repeat');
  const batchForm=$('planning-batch-form');batchForm.elements.start_date.value='2027-05-10';batchForm.elements.end_date.value='2027-05-31';
  batchForm.querySelector('[name=weekdays][value="0"]').checked=true;
  assert.equal(a.batchPreviewPayload(batchForm).template.zoom_url,'https://school.zoom.us/j/123?pwd=promo');
  a.state.batch.course.zoom_url='';assert.equal(a.batchPreviewPayload(batchForm).template.zoom_url,'');
  a.state.batch=weekBatch;a.setBatchMode('weeks');checks+=2;

  // Week mode automatically leaves impossible occurrences out. Date mode retains explicit consent.
  const preview={preview_token:'test-token',mode:'weeks',partial:true,items:[{key:'a',valid:true,course:{...course,date:'2027-05-24'},conflicts:[]},{key:'b',valid:false,course:{...course,date:'2027-05-17'},conflicts:[{type:'public_holiday',message:'Lundi de Pentecôte : aucun cours possible.'}]}]};
  a.state.batch.preview=preview;a.renderBatchPreview(preview);
  assert.equal($('planning-batch-commit').disabled,false);assert.equal($('planning-batch-conflict-consent').hidden,true);
  assert.equal($('planning-batch-items').querySelector('input[value=b]').disabled,true);
  assert.match($('planning-batch-summary').textContent,/1 disponible\(s\).*1 à laisser/);
  a.state.batch.mode='dates';a.updateBatchCommit();assert.equal($('planning-batch-commit').disabled,true);
  $('planning-batch-skip').checked=true;a.updateBatchCommit();assert.equal($('planning-batch-commit').disabled,false);
  a.state.batch.mode='weeks';checks+=6;

  // Final report combines known and newly appeared blockers once, with real created count.
  const result={count:0,created_keys:[],skipped:[{key:'a',course:{...course,date:'2027-05-24'},conflicts:[{type:'trainer_unavailable',message:'Le formateur est indisponible.'}]}]};
  const report=a.batchReportData(preview,['a'],result);assert.equal(report.created,0);assert.equal(report.skipped.length,2);
  a.showBatchReport(preview,['a'],result);assert.equal($('planning-batch-report-dialog').open,true);
  assert.equal($('planning-batch-report-items').querySelectorAll('article').length,2);
  assert.match($('planning-batch-report-items').textContent,/Pentecôte/);assert.match($('planning-batch-report-items').textContent,/indisponible/);
  assert.match($('planning-batch-report-summary').textContent,/0cours créés2cours laissés/);$('planning-batch-report-dialog').close();checks+=7;

  // Native fullscreen covers the document so every modal remains in the same fullscreen tree.
  let nativeElement=null;
  Object.defineProperty(d,'fullscreenElement',{get:()=>nativeElement,configurable:true});
  d.documentElement.requestFullscreen=async()=>{nativeElement=d.documentElement;d.dispatchEvent(new w.Event('fullscreenchange'));};
  d.exitFullscreen=async()=>{nativeElement=null;d.dispatchEvent(new w.Event('fullscreenchange'));};
  await a.togglePlanningFullscreen();assert.equal(nativeElement,d.documentElement);assert.equal(a.state.fullscreen,true);
  assert.equal(d.body.classList.contains('planning-is-fullscreen'),true);assert.equal($('planning-fullscreen').getAttribute('aria-pressed'),'true');
  assert.match($('planning-fullscreen-label').textContent,/Quitter/);
  assert.equal(d.documentElement.contains($('planning-batch-report-dialog')),true);
  nativeElement=null;d.dispatchEvent(new w.Event('fullscreenchange'));assert.equal(a.state.fullscreen,false);
  d.documentElement.requestFullscreen=async()=>{throw Error('API denied');};await a.togglePlanningFullscreen();assert.equal(a.state.fullscreen,true);
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',cancelable:true}));assert.equal(a.state.fullscreen,false);checks+=9;

  // External changes never reload over a modal or unsaved calendar draft.
  a.state.paintDraft.set('2027-05-18',{});assert.equal(a.planningSyncSafe(),false);
  const changed=new w.CustomEvent('academy:planning-changed',{cancelable:true,detail:{revision:'new'}});w.dispatchEvent(changed);
  assert.equal(changed.defaultPrevented,true);assert.equal(a.state.syncPending,true);assert.equal($('planning-sync-notice').hidden,false);assert.equal(calls.length,0);
  a.state.paintDraft.clear();$('planning-course-dialog').showModal();assert.equal(a.planningSyncSafe(),false);$('planning-course-dialog').close();
  assert.equal(a.planningSyncSafe(),true);
  const slotDate=$('planning-slot-form').elements.date;slotDate.focus();assert.equal(a.planningSyncSafe(),false);slotDate.value='2027-05-24';slotDate.dispatchEvent(new w.Event('input',{bubbles:true}));slotDate.blur();assert.equal(a.state.slotFormDirty,true);assert.equal(a.planningSyncSafe(),false);assert.equal($('planning-slot-clear').hidden,false);a.state.slotFormDirty=false;checks+=11;
  // A refresh response must be discarded if editing begins after its request starts.
  w.clearTimeout(a.state.syncTimer);
  for (const action of ['typing','painting','dialog']) {
    a.state.slotFormDirty=false;a.state.paintDraft.clear();a.state.syncPending=true;a.state.loading=false;
    const snapshot={...a.state.data,oldSnapshot:action};a.state.data=snapshot;
    let resolve;w.fetch=()=>new Promise(done=>{resolve=done;});
    const work=a.refreshChangedPlanning();assert.equal(a.state.loading,true);
    if(action==='typing'){slotDate.value='2027-05-25';slotDate.dispatchEvent(new w.Event('input',{bubbles:true}));}
    if(action==='painting')a.state.paintDraft.set('2027-05-26',{date:'2027-05-26',kind:'company'});
    if(action==='dialog')$('planning-course-dialog').showModal();
    resolve({ok:true,json:async()=>({promotion,subjects:[subject],courses:[],days:[]})});await work;
    assert.equal(a.state.data,snapshot);assert.equal(a.state.syncPending,true);assert.equal(a.state.loading,false);
    if(action==='typing'){assert.equal(slotDate.value,'2027-05-25');assert.equal(a.state.slotFormDirty,true);}
    if(action==='painting')assert.equal(a.state.paintDraft.get('2027-05-26').kind,'company');
    if(action==='dialog'){assert.equal($('planning-course-dialog').open,true);$('planning-course-dialog').close();}
    w.clearTimeout(a.state.syncTimer);
  }
  checks+=16;
  // The annual-view second fetch gets the same guard before applying either snapshot.
  a.state.slotFormDirty=false;a.state.paintDraft.clear();a.state.syncPending=true;a.state.view='year';
  const annualSnapshot=a.state.data, resolvers=[];w.fetch=()=>new Promise(done=>resolvers.push(done));
  const annualWork=a.refreshChangedPlanning();assert.equal(resolvers.length,1);
  resolvers[0]({ok:true,json:async()=>({promotion,subjects:[subject],courses:[],days:[]})});
  for(let tick=0;tick<10;tick++)await Promise.resolve();assert.equal(resolvers.length,2);
  a.state.paintDraft.set('2027-05-27',{date:'2027-05-27',kind:'company'});
  resolvers[1]({ok:true,json:async()=>({promotion,subjects:[subject],courses:[],days:[]})});await annualWork;
  assert.equal(a.state.data,annualSnapshot);assert.equal(a.state.paintDraft.size,1);assert.equal(a.state.syncPending,true);w.clearTimeout(a.state.syncTimer);checks+=5;
  console.log(`PASS: ${checks} full DOM planning checks (week painting, partial copy report, fullscreen/Escape, safe synchronization).`);
  w.close();
}
run().catch(error=>{console.error(error);w.close();process.exitCode=1;});
