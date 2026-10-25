/* Actual rendered calendar navigation; no browser or external requests. */
const assert=require('node:assert/strict'),fs=require('node:fs'),{spawnSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const rendered=spawnSync('python',['-c',`from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader
E=Environment(loader=ChoiceLoader([DictLoader({'base.html':'<!doctype html><html><body>{% block content %}{% endblock %}</body></html>'}),FileSystemLoader('templates')]))
config=dict(year=2027,csrf_token='fixture-only',home_url='/formateur',planning_url='/formateur/planning',state_url='/formateur/indisponibilites/api/state',preview_url='/formateur/indisponibilites/api/preview',commit_url='/formateur/indisponibilites/api/commit',state=dict(year=2027,today='2027-01-04',min_date='2027-01-04',days=[],revision=0))
print(E.get_template('trainer_availability.html').render(availability=config,trainer={}))`],{encoding:'utf8'});
assert.equal(rendered.status,0,rendered.stderr);
const dom=new JSDOM(rendered.stdout,{url:'https://example.test/formateur/indisponibilites',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document,$=id=>d.getElementById(id);let calls=[],scrolled='';
w.HTMLElement.prototype.scrollIntoView=function(){scrolled=this.id};
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
w.HTMLDialogElement.prototype.close=function(){this.open=false};
w.fetch=async url=>{calls.push(String(url));return{ok:true,status:200,json:async()=>({year:Number(new URL(url).searchParams.get('year')),today:'2027-01-04',min_date:'2027-01-04',days:[],revision:0})}};
w.eval(fs.readFileSync('static/js/trainer-availability.js','utf8'));
const settle=async()=>{for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve));};
(async()=>{
 assert.equal(d.querySelectorAll('.trainer-portal-tab').length,3);
 assert.equal(d.querySelector('[aria-current="page"]').getAttribute('href'),'/formateur/indisponibilites');
 assert.equal($('ta-year-select').value,'2027');assert.equal($('ta-year-select').disabled,false);
 $('ta-year-select').value='2030';$('ta-year-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 assert.equal(calls.length,1);assert.match(calls[0],/year=2030/);assert.equal($('ta-calendar-title').textContent,'2030');assert.equal($('ta-year-select').value,'2030');
 const day=d.querySelector('[data-ta-date="2030-01-08"]');day.click();assert.equal(day.getAttribute('aria-pressed'),'true');assert.equal($('ta-year-select').disabled,true);assert.equal($('ta-year-submit').disabled,true);
 $('ta-year-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();assert.equal(calls.length,1);assert.match($('ta-notice').textContent,/Enregistrez ou effacez/);
 $('ta-month-select').value='11';$('ta-month-select').dispatchEvent(new w.Event('change'));assert.equal(scrolled,'ta-month-11');assert.equal(day.getAttribute('aria-pressed'),'true');
 $('ta-clear').click();assert.equal($('ta-year-select').disabled,false);assert.equal($('ta-year-submit').disabled,false);
 $('ta-month-select').value='';$('ta-month-select').dispatchEvent(new w.Event('change'));assert.equal(scrolled,'ta-calendar-title');
 console.log('18 trainer month/year navigation assertions passed.');w.close();
})().catch(error=>{console.error(error);w.close();process.exitCode=1;});
