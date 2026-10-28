/* The actual bulk-room dialog: selected-slot intersection and explicit commit. */
const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const html='<button id="planning-bulk-rooms">Salles</button><button id="planning-add-event">Événement</button><div id="planning-budget-alert"></div>'+fs.readFileSync('templates/_planning_extras.html','utf8');
const settle=async()=>{await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));};
const rooms=[{id:'r1',name:'Salle 1',active:1},{id:'r2',name:'Salle 2',active:1},{id:'inactive',name:'Ancienne salle',active:0}];
function setup(){
  const dom=new JSDOM(html,{url:'https://example.test/admin/planning',runScripts:'outside-only'}),w=dom.window,d=w.document,$=id=>d.getElementById(id);
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  const candidates=Array.from({length:9},(_,i)=>({id:'c'+i,version:i+1,date:'2027-01-'+String(i+4).padStart(2,'0'),start:'09:00',end:'11:00',
    display_subject_id:i%2?'s2':'s1',display_subject_name:i%2?'Expression':'Anglais',room_id:i===8?'r1':null,room_name:i===8?'Salle 1':null,is_shared:i===0,kind:'course'}));
  const state={periodId:'p1:1',data:{period:{start_date:'2027-01-01',end_date:'2027-01-31'},rooms,subjects:[{id:'s1',name:'Anglais'},{id:'s2',name:'Expression'}]}};
  const calls=[],lookups=[];let refreshes=0;
  w.AcademyPlanning={getState:()=>state,promotionId:()=> 'p1',notice:()=>{},refresh:async()=>refreshes++,request:(url,options)=>{
    calls.push({url,options});
    if(url.startsWith('/rooms/courses?'))return Promise.resolve({courses:candidates});
    if(url==='/rooms/bulk-available')return new Promise((resolve,reject)=>lookups.push({options,resolve,reject}));
    if(url==='/rooms/bulk-preview')return Promise.resolve({token:'signed-preview',count:options.data.courses.length,shared:options.data.courses.some(c=>c.id==='c0')?1:0});
    if(url==='/rooms/bulk-commit')return Promise.resolve({count:1,message:'Salle affectée.'});
    throw Error('Unexpected request: '+url);
  }};
  w.eval(fs.readFileSync('static/js/planning-extras.js','utf8'));
  const form=$('planning-bulk-room-form'),select=form.elements.room_id;
  return {dom,w,d,$,form,select,calls,lookups,candidates,refreshes:()=>refreshes,
    open:async()=>{$('planning-bulk-rooms').click();await settle();},
    reply:(index,available)=>lookups[index].resolve({rooms:available}),
    choices:()=>[...select.options].filter(o=>o.value&&!o.disabled).map(o=>o.value),
    box:id=>$('planning-bulk-room-list').querySelector('input[value="'+id+'"]'),
    change:(name,value)=>{const n=form.elements[name];if(typeof value==='boolean')n.checked=value;else n.value=value;n.dispatchEvent(new w.Event('change',{bubbles:true}));},
    submit:()=>form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})),
    writes:()=>calls.filter(c=>c.url==='/rooms/bulk-commit')};
}
(async()=>{
  // Screenshot workflow: eight unassigned courses, only a room free for all eight is offered.
  let t=setup();await t.open();assert(t.select.disabled);assert.deepEqual(t.choices(),[]);assert.equal(t.lookups.length,0);
  t.$('planning-bulk-room-all').click();assert.equal(t.lookups.length,1);assert.equal(t.lookups[0].options.data.courses.length,8);
  assert.equal(t.lookups[0].options.data.period_id,'p1:1');assert.equal(t.lookups[0].options.data.promotion_id,'p1');
  assert(t.select.disabled);assert(t.$('planning-bulk-room-check').disabled);assert(!t.box('c0').disabled);
  t.submit();assert(!t.calls.some(c=>c.url==='/rooms/bulk-preview'));
  t.reply(0,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r2']);assert(!t.select.disabled);
  t.change('room_id','r2');assert(!t.$('planning-bulk-room-check').disabled);t.submit();await settle();
  assert(!t.$('planning-bulk-room-save').disabled);assert.equal(t.writes().length,0);
  assert(t.$('planning-bulk-room-preview').textContent.includes('cours commun'));
  const preview=t.calls.find(c=>c.url==='/rooms/bulk-preview').options.data;
  assert.equal(preview.room_id,'r2');assert.equal(preview.courses.length,8);
  assert.deepEqual(JSON.parse(JSON.stringify(preview.courses)),t.candidates.slice(0,8).map(c=>({id:c.id,version:c.version})));

  // Any checkbox change invalidates confirmation immediately; older responses stay ignored.
  t.box('c0').click();assert(t.$('planning-bulk-room-save').disabled);assert(t.select.disabled);
  t.box('c1').click();assert(t.lookups[1].options.signal.aborted);
  t.reply(2,[rooms[0]]);await settle();assert.deepEqual(t.choices(),['r1']);assert.equal(t.select.value,'');
  t.reply(1,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r1']);
  t.$('planning-bulk-room-none').click();assert.deepEqual(t.choices(),[]);assert(t.select.disabled);assert.equal(t.writes().length,0);t.dom.window.close();

  // A missing common room explains how to proceed; narrowing the selection restores choices.
  t=setup();await t.open();t.$('planning-bulk-room-all').click();t.reply(0,[]);await settle();
  assert.deepEqual(t.choices(),[]);assert(t.select.disabled);assert(t.$('planning-bulk-room-check').disabled);
  assert(t.$('planning-bulk-room-status').textContent.includes('Réduisez la sélection'));
  t.$('planning-bulk-room-none').click();t.box('c0').click();t.reply(1,[rooms[0]]);await settle();
  t.change('room_id','r1');t.submit();await settle();assert(!t.$('planning-bulk-room-save').disabled);
  const narrowed=t.calls.filter(c=>c.url==='/rooms/bulk-preview').at(-1).options.data;
  assert.deepEqual(JSON.parse(JSON.stringify(narrowed.courses)),[{id:'c0',version:1}]);
  t.$('planning-bulk-room-save').click();t.$('planning-bulk-room-save').click();await settle();
  assert.equal(t.writes().length,1);assert.equal(t.writes()[0].options.data.token,'signed-preview');assert.equal(t.refreshes(),1);assert(!t.$('planning-bulk-room-dialog').open);t.dom.window.close();

  // Filters affect the actual selection and trigger another intersection calculation.
  t=setup();await t.open();t.change('unassigned',false);t.$('planning-bulk-room-all').click();assert.equal(t.lookups[0].options.data.courses.length,9);
  t.change('unassigned',true);assert.equal(t.lookups[1].options.data.courses.length,8);
  t.change('subject','s1');assert.deepEqual(t.lookups[2].options.data.courses.map(c=>c.id),['c0','c2','c4','c6']);
  t.reply(2,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r2']);
  t.change('from','2027-01-05');assert.deepEqual(t.choices(),[]);assert(t.select.disabled);assert.equal(t.$('planning-bulk-room-list').querySelectorAll('input').length,0);
  t.reply(0,[rooms[0]]);t.reply(1,[rooms[0]]);await settle();assert.deepEqual(t.choices(),[]);t.dom.window.close();

  // An error offers a retry, never the full catalogue. Closing invalidates pending lookups.
  t=setup();await t.open();t.box('c0').click();t.lookups[0].reject(Error('Synchronisation en cours.'));await settle();
  assert(t.select.disabled);assert.deepEqual(t.choices(),[]);assert(!t.$('planning-bulk-room-retry').hidden);
  t.$('planning-bulk-room-retry').click();t.reply(1,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r2']);
  t.box('c1').click();t.$('planning-bulk-room-dialog').close();assert(t.lookups[2].options.signal.aborted);
  await t.open();t.box('c0').click();t.reply(3,[rooms[0]]);await settle();
  t.reply(2,[rooms[1]]);await settle();assert.deepEqual(t.choices(),['r1']);assert.equal(t.writes().length,0);t.dom.window.close();
  console.log('PASS: eight-slot bulk room intersection, filters, stale responses, empty intersection, retry, shared preview, explicit one-time commit and reopened dialogs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
