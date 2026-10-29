const fs=require('node:fs'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process'),{JSDOM}=require('jsdom');
const render=spawnSync('python',['-c',`from jinja2 import Environment,FileSystemLoader
from datetime import date,timedelta
env=Environment(loader=FileSystemLoader('templates'))
days=[]
for i in range(334):
 d=date(2026,9,1)+timedelta(days=i);days.append(dict(date=d.isoformat(),unavailable=d.day==7 and d.month==1,public_holiday='Férié' if d==date(2027,1,1) else '',course_count=1 if d==date(2027,1,5) else 0,reason=''))
print(env.get_template('_trainer_admin_availability.html').render(csrf_token='csrf-fixture',trainer_availability=dict(year=2026,state=dict(days=days,months=list(dict.fromkeys(day['date'][:7] for day in days)),revision='rev-a'),blocks=[],notifications=[],courses_url='/courses',planning_url='/admin/formateurs/t?tab=planning',save_url='/admin/formateurs/t/indisponibilites/jours',block_url='/admin/formateurs/t/indisponibilites/bloc/')))`],{encoding:'utf8'});
assert.equal(render.status,0,render.stderr);
const dom=new JSDOM(render.stdout,{url:'https://example.test/admin/formateurs/t?tab=availability',runScripts:'outside-only'}),w=dom.window,d=w.document;
let requests=[],resolve;
w.fetch=(url,options)=>{requests.push({url,options});return new Promise(yes=>resolve=yes)};
w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};
w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new w.Event('close'))};
w.eval(fs.readFileSync('static/js/trainer-calendar-courses.js','utf8'));
w.eval(fs.readFileSync('static/js/trainer-admin-planning.js','utf8'));
const button=day=>d.querySelector(`[data-day="2027-01-${String(day).padStart(2,'0')}"]`),tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 assert.equal(d.querySelectorAll('.tap-month').length,11);assert.equal(d.querySelectorAll('[data-day]').length,334);assert.equal(button(1).disabled,true);assert.equal(button(7).disabled,true);assert.equal(button(5).disabled,false);assert.ok(button(5).classList.contains('has-course'));
 button(4).click();assert.equal(d.getElementById('tap-save').disabled,false);assert.match(d.getElementById('tap-selection-count').textContent,/1 journée/);
 button(6).dispatchEvent(new w.MouseEvent('click',{bubbles:true,shiftKey:true}));assert.match(d.getElementById('tap-selection-count').textContent,/3 journée/);
 d.getElementById('tap-save').click();d.getElementById('tap-save').click();assert.equal(requests.length,1);const sent=JSON.parse(requests[0].options.body);assert.deepEqual(sent.dates,['2027-01-04','2027-01-05','2027-01-06']);assert.equal(sent.expected_revision,'rev-a');assert.equal(requests[0].options.headers['X-CSRF-Token'],'csrf-fixture');
 resolve({ok:false,json:async()=>({ok:false,message:'Cours à déplacer',conflicts:[{date:'2027-01-05',start:'08:00',end:'10:00',title:'<script>no</script>'}]})});await tick();assert.match(d.getElementById('tap-feedback').textContent,/Cours à déplacer/);assert.match(d.getElementById('tap-feedback').textContent,/<script>no<\/script>/);assert.equal(d.getElementById('tap-feedback').querySelector('script'),null);assert.match(d.getElementById('tap-selection-count').textContent,/3 journée/);assert.equal(d.getElementById('tap-save').disabled,false);
 const event=new w.CustomEvent('academy:planning-changed',{cancelable:true});assert.equal(w.dispatchEvent(event),false);assert.match(d.getElementById('tap-feedback').textContent,/sélection est conservée/);
 d.getElementById('tap-clear').click();assert.equal(d.getElementById('tap-save').disabled,true);assert.equal(d.querySelectorAll('.is-selected').length,0);
 const before=requests.length;d.querySelector('[data-course-date="2027-01-05"]').click();assert.equal(requests.length,before+1);assert.equal(requests.at(-1).options.method,undefined);assert.equal(requests.at(-1).options.cache,'no-store');assert.equal(d.querySelectorAll('.is-selected').length,0);
 resolve({ok:true,json:async()=>({courses:[{start:'09:00',end:'11:00',subject_name:'<img src=x onerror=alert(1)>',room_name:'Salle 3B',promotion_names:['BTS CI','BTS PI'],shared:true}]})});await tick();assert.equal(d.querySelectorAll('.tc-course').length,1);assert.equal(d.querySelector('.tc-course img'),null);assert.match(d.querySelector('.tc-course').textContent,/Salle 3B/);assert.match(d.querySelector('.tc-course').textContent,/BTS CI \/ BTS PI/);assert.ok(d.querySelector('.tc-dialog').open);d.querySelector('.tc-close').click();assert.equal(d.querySelector('.tc-dialog').open,false);
 console.log('Admin trainer calendar assertions passed: school year, selection, private read-only course inspection, safe text.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
