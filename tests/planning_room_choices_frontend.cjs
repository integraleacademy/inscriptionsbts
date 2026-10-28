/* Real course dialog: room availability, stale responses, and saved memberships. */
const fs = require('node:fs'), assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const rendered = spawnSync(process.env.PYTHON || 'python', ['-c', `from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'<html><body>{% block content %}{% endblock %}</body></html>'}),FileSystemLoader('templates')]))
print(env.get_template('planning_admin.html').render(csrf_token='test-only',promotions=[dict(id='p1',nom='BTS CI',active=True),dict(id='p2',nom='BTS PI',active=True)],selected_promotion='p2'))`], {encoding:'utf8'});
assert.equal(rendered.status, 0, rendered.stderr);
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); };
const rooms = [{id:'r1',name:'Salle 1',active:1},{id:'r2',name:'Salle 2',active:1},{id:'inactive',name:'Ancienne salle',active:0}];
function setup(room = null) {
  const dom = new JSDOM(rendered.stdout, {url:'https://example.test/admin/planning?promotion_id=p2',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window, d = w.document, $ = id => d.getElementById(id), requests = [], writes = [];
  w.HTMLDialogElement.prototype.showModal = function(){this.open=true;};
  w.HTMLDialogElement.prototype.close = function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.HTMLElement.prototype.scrollIntoView = function(){};
  w.fetch = (url, options) => {
    if (url.includes('/rooms/available?')) return new Promise((resolve,reject) => requests.push({url,options,resolve,reject}));
    writes.push({url,options}); return new Promise(() => {});
  };
  w.eval(fs.readFileSync('static/js/planning.js','utf8').replace('  loadState({initial: true});', '  window.testPlanning={state,openCourse,courseValues};'));
  const api = w.testPlanning;
  const promotions = ['p1','p2'].map((id,i) => ({id,nom:i?'BTS PI':'BTS CI',bts:i?'PI':'CI',active:1,date_debut:'2027-01-01',date_fin:'2027-07-01'}));
  const subjects = promotions.map((p,i) => ({id:'s'+(i+1),promotion_id:p.id,name:'Anglais',trainer_id:'t1',planned_hours:40,planned_minutes:2400,remaining_minutes:0,budget_configured:true}));
  const course = {id:'common',version:3,promotion_id:'p1',subject_id:'s1',trainer_id:'t1',room_id:room,date:'2027-01-04',start:'09:00',end:'11:00',
    shared:[{promotion_id:'p2',subject_id:'s2'}],groups:promotions.map((p,i) => ({promotion_id:p.id,subject_id:'s'+(i+1),promotion_name:p.nom}))};
  api.state.data = {promotion:promotions[1],subjects:[subjects[1]],catalog:{promotions,subjects,trainers:[{id:'t1',name:'Exemple'}]},rooms};
  api.state.week = '2027-01-04'; api.openCourse(course);
  const form = $('planning-course-form');
  return {dom,w,$,api,course,form,requests,writes,select:form.elements.room_id,
    change: (field,value) => { if(typeof value==='boolean')form.elements[field].checked=value;else form.elements[field].value=value; form.elements[field].dispatchEvent(new w.Event('change',{bubbles:true})); },
    reply: (index,available) => requests[index].resolve({ok:true,json:async()=>({ok:true,rooms:available})}),
    submit: () => form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})),
    choices: () => [...form.elements.room_id.options].filter(o=>o.value&&!o.disabled).map(o=>o.value)};
}
(async () => {
  // An unassigned shared course only offers server-verified choices, from either planning.
  let t = setup();
  assert(t.select.disabled); assert.deepEqual(t.choices(),[]);
  const query = new URL(t.requests[0].url,'https://example.test').searchParams;
  assert.deepEqual(Object.fromEntries(query), {date:'2027-01-04',start:'09:00',end:'11:00',exclude_course_id:'common'});
  t.submit(); assert.equal(t.writes.length,0);
  t.reply(0,[rooms[1]]); await settle();
  assert(!t.select.disabled); assert.deepEqual(t.choices(),['r2']); assert.equal(t.select.value,'');
  t.change('room_id','r2'); t.submit(); t.submit(); await settle();
  assert.equal(t.writes.length,1);
  const write = t.writes[0]; assert.equal(write.options.method,'PUT'); assert(write.url.endsWith('/courses/common'));
  const saved = JSON.parse(write.options.body);
  assert.equal(saved.room_id,'r2'); assert.equal(saved.promotion_id,'p1'); assert.equal(saved.version,3);
  assert.deepEqual(saved.shared,[{promotion_id:'p2',subject_id:'s2'}]); t.dom.window.close();

  // Keep the current room if free; a newly conflicting assignment requires an explicit choice.
  t=setup('r1');t.reply(0,rooms.slice(0,2));await settle();assert.equal(t.select.value,'r1');assert(t.select.checkValidity());
  t.change('start','10:00');assert(t.select.disabled);t.reply(1,[rooms[1]]);await settle();
  assert.deepEqual(t.choices(),['r2']);assert.equal(t.select.value,'r1');assert(t.select.selectedOptions[0].disabled);
  assert(!t.select.checkValidity());t.submit();assert.equal(t.writes.length,0);
  t.change('room_id','');assert(t.select.checkValidity());assert.equal(t.api.courseValues(t.form).room_id,null);t.dom.window.close();

  // Rapid slot edits and responses arriving out of order cannot restore old room choices.
  t=setup();t.change('date','2027-01-05');t.change('end','12:00');
  assert(t.requests[0].options.signal.aborted);assert(t.requests[1].options.signal.aborted);
  t.reply(1,[rooms[0]]);await settle();assert(t.select.disabled);
  t.reply(2,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r2']);
  t.reply(0,[rooms[0]]);await settle();assert.deepEqual(t.choices(),['r2']);
  assert(new URL(t.requests[2].url,'https://example.test').searchParams.get('end')==='12:00');t.dom.window.close();

  // Failed verification never falls back to the full catalogue; retry can return no free rooms.
  t=setup();t.requests[0].resolve({ok:false,json:async()=>({ok:false,message:'Synchronisation en cours.'})});await settle();
  assert(t.select.disabled);assert.deepEqual(t.choices(),[]);assert(!t.$('planning-course-room-retry').hidden);
  t.submit();assert.equal(t.writes.length,0);
  t.$('planning-course-room-retry').click();assert(t.$('planning-course-room-retry').hidden);
  t.reply(1,[]);await settle();assert(!t.select.disabled);assert.equal(t.select.value,'');assert.deepEqual(t.choices(),[]);
  assert(t.$('planning-course-room-status').textContent.includes('Aucune salle disponible'));
  t.submit();await settle();assert.equal(JSON.parse(t.writes[0].options.body).room_id,null);t.dom.window.close();

  // Midnight, closed/reopened dialogs and creation have their own availability request.
  t=setup();t.change('end_at_midnight',true);
  assert.equal(new URL(t.requests[1].url,'https://example.test').searchParams.get('end'),'24:00');
  t.$('planning-course-dialog').close();assert(t.requests[1].options.signal.aborted);
  t.api.openCourse({...t.course,id:'another',date:'2027-01-05'});
  t.reply(1,[rooms[0]]);await settle();assert(t.select.disabled);
  t.reply(2,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r2']);
  assert.equal(new URL(t.requests[2].url,'https://example.test').searchParams.get('exclude_course_id'),'another');
  t.$('planning-course-dialog').close();t.api.openCourse();
  assert(!new URL(t.requests[3].url,'https://example.test').searchParams.has('exclude_course_id'));
  t.change('end','08:00');assert.equal(t.requests.length,4);assert(t.select.disabled);
  t.reply(3,[rooms[0]]);await settle();assert(t.select.disabled);t.dom.window.close();
  console.log('PASS: available-only choices, preserved shared memberships, changed times, current-room validation, stale responses, retries, no free rooms, midnight and dialog lifecycle.');
})().catch(error=>{console.error(error);process.exitCode=1;});
