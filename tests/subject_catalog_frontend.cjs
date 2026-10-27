/* Real template: diploma filtering, per-diploma edits and creation without promotions. */
const fs = require('node:fs'), assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
require('node:child_process').execFileSync('python', ['tests/render_subject_reference_fixture.py'], {stdio:'pipe'});
const dom = new JSDOM(fs.readFileSync('tmp/reference-qa/matieres.html', 'utf8'), {url:'https://example.test/admin/matieres', runScripts:'outside-only', pretendToBeVisual:true});
const w=dom.window, d=w.document, $=id=>d.getElementById(id);
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
const catalog=JSON.parse(fs.readFileSync('tmp/reference-qa/catalog.json','utf8'));
catalog.promotions=[];catalog.trainers=[];catalog.subjects=[];
catalog.subject_catalog=[
 {id:'culture',name:'Culture générale',color:'#2563eb',version:1,planning_count:0,diploma_codes:['MCO','MOS'],diploma_details:{MOS:{coefficient:3,objectives:'Programme MOS'},MCO:{coefficient:4,objectives:'Programme MCO'}}},
 {id:'management',name:'Management',color:'#0891b2',version:1,planning_count:1,diploma_codes:['MOS'],diploma_details:{MOS:{coefficient:5}}},
 {id:'anglais',name:'Anglais',color:'#7c3aed',version:1,planning_count:0,diploma_codes:['CI','MCO'],diploma_details:{CI:{coefficient:2},MCO:{coefficient:3}}}
];
let writes=[];
w.fetch=async(url,options={})=>{
 const method=options.method||'GET',payload=options.body?JSON.parse(options.body):null;
 if(url==='/admin/planning/api/catalog')return {ok:true,json:async()=>catalog};
 assert(url.startsWith('/admin/planning/api/subject-catalog'));
 assert(options.headers['X-CSRF-Token']);writes.push({method,payload});
 if(method==='POST')catalog.subject_catalog.push({id:'created',version:1,planning_count:0,...payload});
 if(method==='PUT'){
  const item=catalog.subject_catalog.find(item=>url.endsWith('/'+item.id));
  assert.equal(payload.version,item.version);Object.assign(item,payload,{version:item.version+1});
  for(const change of payload.planning_allocations||[])Object.assign(catalog.subjects.find(row=>row.id===change.id),{planned_hours:change.planned_hours});
 }
 if(method==='DELETE'){
  assert.equal(payload.version,catalog.subject_catalog.find(item=>url.endsWith('/'+item.id)).version);
  if(url.endsWith('/management'))return {ok:false,json:async()=>({ok:false,message:'Cette matière comporte des cours dans un planning.',conflicts:[{type:'subject_used',promotion_id:'p1',promotion_name:'MOS <img src=x>',period_id:'p1:2',study_year:2,course_count:3}]})};
  catalog.subject_catalog=catalog.subject_catalog.filter(item=>!url.endsWith('/'+item.id));
 }
 return {ok:true,json:async()=>({ok:true,message:'Matière enregistrée.'})};
};
const wait=()=>new Promise(resolve=>setTimeout(resolve,15));
const change=input=>input.dispatchEvent(new w.Event('change',{bubbles:true}));
const filter=value=>{$('catalog-diploma-filter').value=value;change($('catalog-diploma-filter'))};
const search=value=>{$('catalog-search').value=value;$('catalog-search').dispatchEvent(new w.Event('input',{bubbles:true}))};
const names=()=>[...d.querySelectorAll('#catalog-grid h3')].map(n=>n.textContent);
const submit=()=> $('catalog-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
const check=(code,value)=>{const input=d.querySelector('#catalog-diploma-choices input[value="'+code+'"]');input.checked=value;change(input)};
w.eval(fs.readFileSync('static/js/subject-catalog.js','utf8'));
(async()=>{
 await wait();assert.deepEqual(names(),['Anglais','Culture générale','Management']);
 assert.equal($('catalog-stat-one').textContent,'3');assert.equal($('catalog-stat-three').textContent,'2');
 assert(!d.querySelector('[data-catalog-create]').disabled);
 filter('MOS');assert.deepEqual(names(),['Culture générale','Management']);assert(w.location.search.includes('diploma=MOS'));
 search('culture generale');assert.deepEqual(names(),['Culture générale']);
 search('BTS MCO');assert.deepEqual(names(),['Culture générale']);search('');
 $('catalog-sort').value='name-desc';change($('catalog-sort'));assert.deepEqual(names(),['Management','Culture générale']);
 catalog.subjects=[
  {id:'first',catalog_subject_id:'culture',diploma_code:'MOS',promotion_name:'MOS 2026–2028',promotion_active:1,study_year:1,planned_hours:40,scheduled_hours:10,period_start:'2026-09-01',period_end:'2027-07-01'},
  {id:'second',catalog_subject_id:'culture',diploma_code:'MOS',promotion_name:'MOS 2026–2028',promotion_active:1,study_year:2,planned_hours:30,scheduled_hours:0},
  {id:'archived',catalog_subject_id:'culture',diploma_code:'MOS',promotion_name:'MOS archive',promotion_active:0,study_year:1,planned_hours:20,scheduled_hours:20}
 ];
 d.querySelector('[data-catalog-edit="culture"]').click();
 const form=$('catalog-form');assert(!form.elements.promotion_id&&!form.elements.trainer_id&&!form.elements.planned_hours);
 assert.equal($('catalog-detail-diploma').value,'MOS');assert.equal(form.elements.coefficient.value,'3');
 form.elements.coefficient.value='9';form.elements.objectives.value='Objectifs MOS modifiés';
 form.elements.annual_hours_first.value='120';form.elements.annual_hours_second.value='80';$('catalog-apply-hours').click();
 const allocation=id=>d.querySelector('[data-allocation-id="'+id+'"]');
 assert.equal(allocation('first').value,'120');assert.equal(allocation('second').value,'80');
 assert(allocation('archived').disabled);assert.equal(allocation('archived').value,'20');
 allocation('first').value='125';allocation('first').dispatchEvent(new w.Event('input',{bubbles:true}));
 $('catalog-detail-diploma').value='MCO';change($('catalog-detail-diploma'));assert.equal(form.elements.coefficient.value,'4');
 assert.equal(form.elements.annual_hours_first.value,'');assert($('catalog-allocation-section').hidden);form.elements.annual_hours_first.value='60';
 form.elements.coefficient.value='6';form.elements.objectives.value='Objectifs MCO modifiés';check('CI',true);
 $('catalog-detail-diploma').value='CI';change($('catalog-detail-diploma'));assert.equal(form.elements.coefficient.value,'');form.elements.coefficient.value='2';
 $('catalog-detail-diploma').value='MOS';change($('catalog-detail-diploma'));assert.equal(form.elements.coefficient.value,'9');
 assert.equal(form.elements.annual_hours_first.value,'120');assert.equal(allocation('first').value,'125');
 submit();await wait();assert.equal(writes.length,1);
 const payload=writes[0].payload;assert.deepEqual([...payload.diploma_codes].sort(),['CI','MCO','MOS']);
 assert.equal(payload.diploma_details.MOS.coefficient,9);assert.equal(payload.diploma_details.MCO.coefficient,6);assert.equal(payload.diploma_details.CI.coefficient,2);
 assert.equal(payload.diploma_details.MOS.objectives,'Objectifs MOS modifiés');assert.equal(payload.diploma_details.MCO.objectives,'Objectifs MCO modifiés');
 assert.equal(payload.diploma_details.MOS.annual_hours_first,120);assert.equal(payload.diploma_details.MOS.annual_hours_second,80);assert.equal(payload.diploma_details.MCO.annual_hours_first,60);
 assert.deepEqual(payload.planning_allocations,[{id:'first',previous_planned_hours:40,planned_hours:125},{id:'second',previous_planned_hours:30,planned_hours:80}]);
 assert(!('promotion_id' in payload));assert(!$('catalog-editor').open);
 filter('');d.querySelector('[data-catalog-create]').click();form.elements.name.value='Nouvelle matière <img src=x onerror=alert(1)>';
 submit();await wait();assert.equal(writes.length,1);assert(!$('catalog-form-error').hidden);
 check('MOS',true);check('MCO',true);submit();await wait();assert.equal(writes.length,2);assert.equal(writes[1].method,'POST');
 assert.equal(d.querySelectorAll('#catalog-grid img').length,0);assert.equal(catalog.subjects.length,3);assert.deepEqual(writes[1].payload.planning_allocations,[]);
 filter('MCO');assert(names().includes('Nouvelle matière <img src=x onerror=alert(1)>'));filter('MOS');
 d.querySelector('[data-catalog-edit="management"]').click();$('catalog-delete').click();$('catalog-confirm-action').click();await wait();
 assert($('catalog-confirm').open);assert($('catalog-confirm-error').textContent.includes('planning'));
 const link=$('catalog-confirm-links').querySelector('a');assert(link.href.includes('promotion_id=p1'));assert(link.href.includes('period_id=p1%3A2'));assert.equal(link.target,'_blank');assert(link.textContent.includes('3 cours'));assert.equal($('catalog-confirm-links').querySelectorAll('img').length,0);
 $('catalog-confirm').close();$('catalog-editor').close();
 d.querySelector('[data-catalog-edit="created"]').click();$('catalog-delete').click();assert($('catalog-confirm-links').hidden);assert($('catalog-confirm-text').textContent.includes('sans cours'));
 $('catalog-confirm-action').click();await wait();assert(!$('catalog-confirm').open);assert(!$('catalog-editor').open);assert(!names().some(name=>name.startsWith('Nouvelle matière')));
 console.log('PASS: diploma filters, annual budgets, successful deletion, course protection with safe planning links, and versioned delete requests.');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
