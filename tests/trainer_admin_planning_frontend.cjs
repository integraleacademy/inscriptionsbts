const fs=require('node:fs'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process'),{JSDOM}=require('jsdom');
const render=spawnSync('python',['-c',`from jinja2 import Environment,FileSystemLoader
from datetime import date,timedelta
env=Environment(loader=FileSystemLoader('templates'))
days=[]
for i in range(365):
 d=date(2027,1,1)+timedelta(days=i);days.append(dict(date=d.isoformat(),unavailable=d.day==7 and d.month==1,public_holiday='Férié' if d==date(2027,1,1) else '',course_count=1 if d==date(2027,1,5) else 0,reason=''))
print(env.get_template('_trainer_admin_availability.html').render(csrf_token='csrf-fixture',trainer_availability=dict(year=2027,state=dict(days=days,revision='rev-a'),blocks=[],notifications=[],save_url='/admin/formateurs/t/indisponibilites/jours',block_url='/admin/formateurs/t/indisponibilites/bloc/')))`],{encoding:'utf8'});
assert.equal(render.status,0,render.stderr);
const dom=new JSDOM(render.stdout,{url:'https://example.test/admin/formateurs/t?tab=availability',runScripts:'outside-only'}),w=dom.window,d=w.document;
let requests=[],resolve;
w.fetch=(url,options)=>{requests.push({url,options});return new Promise(yes=>resolve=yes)};
w.eval(fs.readFileSync('static/js/trainer-admin-planning.js','utf8'));
const button=day=>d.querySelector(`[data-day="2027-01-${String(day).padStart(2,'0')}"]`),tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 assert.equal(d.querySelectorAll('.tap-month').length,12);assert.equal(d.querySelectorAll('[data-day]').length,365);assert.equal(button(1).disabled,true);assert.equal(button(7).disabled,true);assert.equal(button(5).disabled,false);assert.ok(button(5).classList.contains('has-course'));
 button(4).click();assert.equal(d.getElementById('tap-save').disabled,false);assert.match(d.getElementById('tap-selection-count').textContent,/1 journée/);
 button(6).dispatchEvent(new w.MouseEvent('click',{bubbles:true,shiftKey:true}));assert.match(d.getElementById('tap-selection-count').textContent,/3 journée/);
 d.getElementById('tap-save').click();d.getElementById('tap-save').click();assert.equal(requests.length,1);const sent=JSON.parse(requests[0].options.body);assert.deepEqual(sent.dates,['2027-01-04','2027-01-05','2027-01-06']);assert.equal(sent.expected_revision,'rev-a');assert.equal(requests[0].options.headers['X-CSRF-Token'],'csrf-fixture');
 resolve({ok:false,json:async()=>({ok:false,message:'Cours à déplacer',conflicts:[{date:'2027-01-05',start:'08:00',end:'10:00',title:'<script>no</script>'}]})});await tick();assert.match(d.getElementById('tap-feedback').textContent,/Cours à déplacer/);assert.match(d.getElementById('tap-feedback').textContent,/<script>no<\/script>/);assert.equal(d.getElementById('tap-feedback').querySelector('script'),null);assert.match(d.getElementById('tap-selection-count').textContent,/3 journée/);assert.equal(d.getElementById('tap-save').disabled,false);
 const event=new w.CustomEvent('academy:planning-changed',{cancelable:true});assert.equal(w.dispatchEvent(event),false);assert.match(d.getElementById('tap-feedback').textContent,/sélection est conservée/);
 d.getElementById('tap-clear').click();assert.equal(d.getElementById('tap-save').disabled,true);assert.equal(d.querySelectorAll('.is-selected').length,0);
 console.log('22 admin trainer calendar assertions passed.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
