/* Real account-tab markup, with all network writes mocked. */
const fs=require('node:fs'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const html=spawnSync('python',['-c',`import sys,tempfile
from pathlib import Path
sys.path.insert(0,'tests')
from test_trainer_workload import workload_db,workload_client
db=workload_db.__wrapped__(Path(tempfile.mkdtemp()))
client=workload_client.__wrapped__(db)
print(client.get('/admin/formateurs/t1?tab=account').text)`],{encoding:'utf8'});
assert.equal(html.status,0,html.stderr);
function fixture(){
 const dom=new JSDOM(html.stdout,{url:'https://example.test/admin/formateurs/t1?tab=account',runScripts:'outside-only'});
 const w=dom.window,calls=[];
 w.fetch=async(url,options)=>{calls.push({url,options});return{ok:false,json:async()=>({ok:false,message:'La promotion est utilisée dans le planning.'})}};
 w.eval(fs.readFileSync('static/js/trainer-workload.js','utf8'));
 return {dom,w,d:w.document,calls};
}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
(async()=>{
 let x=fixture();
 assert.equal(x.d.querySelectorAll('.tw-tab').length,4);
 assert.equal(x.d.querySelector('.tw-tab[aria-current=page]').textContent.trim(),'Compte & accès');
 assert.equal(x.d.querySelector('#trainer-hourly-rate-form'),null);
 const form=x.d.getElementById('trainer-profile-form'),email=form.elements.email;
 const access=x.d.querySelector('[data-profile-action=access]'),status=x.d.querySelector('[data-profile-action=status]');
 assert.equal(access.disabled,false);assert.equal(status.disabled,false);
 email.value='new@example.test';email.dispatchEvent(new x.w.Event('input',{bubbles:true}));
 assert.equal(access.disabled,true);assert.equal(status.disabled,true);
 assert.match(x.d.getElementById('tw-access-feedback').textContent,/Enregistrez les informations/);
 access.click();assert.equal(x.calls.length,0);
 form.dispatchEvent(new x.w.Event('submit',{cancelable:true}));
 assert.equal(email.disabled,true);
 assert.equal(x.calls.length,1);assert.match(x.calls[0].url,/t1\/update$/);
 assert.equal(x.calls[0].options.headers['X-CSRF-Token'],'test-token');
 assert.equal(x.calls[0].options.body.get('email'),'new@example.test');
 await tick();assert.equal(email.disabled,false);assert.equal(email.value,'new@example.test');
 assert.equal(access.disabled,true);assert.equal(status.disabled,true);
 assert.match(x.d.getElementById('tw-profile-feedback').textContent,/promotion est utilisée/);
 x.dom.window.close();
 x=fixture();x.w.fetch=async(url,options)=>{x.calls.push({url,options});return{ok:true,json:async()=>({ok:true,message:'Invitation envoyée au formateur.'})}};
 x.d.querySelector('[data-profile-action=access]').click();await tick();
 assert.equal(x.calls.length,1);assert.match(x.calls[0].url,/t1\/send-access$/);
 assert.equal(x.calls[0].options.body.get('csrf_token'),'test-token');
 assert.match(x.d.getElementById('tw-access-feedback').textContent,/Invitation envoyée/);
 x.dom.window.close();
 console.log('23 trainer account-tab DOM checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
