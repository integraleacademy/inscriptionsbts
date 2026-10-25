// Run with a rendered admin page: node tests/company_registry_frontend.cjs page.html
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = fs.readFileSync(path.join(__dirname, '../static/js/company-registry.js'), 'utf8');
const dom = new JSDOM(html, {url:'https://school.example.test/admin/entreprises', runScripts:'outside-only'});
const w = dom.window, d = w.document;
let timerId = 0;
const timers = new Map(), requests = [];
w.setTimeout = callback => { timers.set(++timerId, callback); return timerId; };
w.clearTimeout = id => timers.delete(id);
w.fetch = (url, options) => new Promise(resolve => requests.push({url, options, resolve}));
w.eval(script);
const root = d.querySelector('[data-company-registry]'), form = root.closest('form');
const input = name => form.elements.namedItem(name);
const preview = root.querySelector('[data-registry-preview]');
const importer = root.querySelector('[data-registry-import]');
const tick = () => new Promise(resolve => setImmediate(resolve));
function type(value) { input('siret').value = value; input('siret').dispatchEvent(new w.Event('input')); }
function flushTimers() { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()); }
const result = (number, name = 'NOVA SERVICES') => ({fields: {siret:number, name, legal_name:'NOVA SERVICES SAS', address:'20 RUE DES APPRENTIS', postal_code:'83480', city:'PUGET-SUR-ARGENS', activity_code:'85.59A', activity_label:'Formation continue d’adultes', legal_form:'SAS (5710)', email:'evil@example.test'}, details:[{label:'Dirigeante',value:'<img src=x onerror=alert(1)>'}], warnings:[], token:'signed-preview'});
async function respond(index, data, status=200) { requests[index].resolve({ok:status===200,status,redirected:false,json:async()=>data}); await tick(); }
(async () => {
  input('name').value='Nom saisi'; input('contact').value='Contact choisi'; input('email').value='contact@example.test'; input('phone').value='0102030405';
  type('123'); flushTimers(); assert.equal(requests.length,0);
  type('123 456 789 00022'); assert.equal(requests.length,0); flushTimers(); assert.equal(requests.length,1);
  assert.equal(new URL(requests[0].url).searchParams.get('siret'),'12345678900022');
  assert.equal(requests[0].options.credentials,'same-origin');
  await respond(0,result('12345678900022'));
  assert.equal(preview.hidden,false); assert.equal(input('name').value,'Nom saisi'); assert.equal(input('registry_token').value,'');
  assert.equal(root.querySelectorAll('img').length,0); // public names render as text, never HTML
  importer.click();
  assert.equal(input('name').value,'NOVA SERVICES'); assert.equal(input('address').value,'20 RUE DES APPRENTIS');
  assert.equal(input('activity_label').value,'Formation continue d’adultes'); assert.equal(input('registry_token').value,'signed-preview');
  assert.equal(input('contact').value,'Contact choisi'); assert.equal(input('email').value,'contact@example.test'); assert.equal(input('phone').value,'0102030405');
  type('12345678900014'); assert.equal(input('registry_token').value,''); assert.equal(preview.hidden,true); flushTimers();
  type('12345678900030'); flushTimers(); // an older response arrives after the newer SIRET
  assert.equal(requests[1].options.signal.aborted,true);
  await respond(2,result('12345678900030','NOUVELLE ENTREPRISE'));
  await respond(1,result('12345678900014','ANCIENNE ENTREPRISE'));
  assert.equal(root.querySelector('[data-registry-name]').textContent,'NOUVELLE ENTREPRISE');
  importer.click(); assert.equal(input('name').value,'NOUVELLE ENTREPRISE');
  type('12345678900049'); flushTimers(); await respond(3,{error:'Aucun établissement trouvé.'},404);
  assert.equal(preview.hidden,true); assert.equal(input('name').value,'NOUVELLE ENTREPRISE');
  assert.equal(input('email').value,'contact@example.test'); assert.equal(input('registry_token').value,'');
  assert.match(root.querySelector('[data-registry-status]').textContent,/Aucun établissement/);
  const event = new w.KeyboardEvent('keydown',{key:'Enter',cancelable:true});
  input('siret').dispatchEvent(event); assert.equal(event.defaultPrevented,true); assert.equal(requests.length,5);
  await respond(4,{error:'Limite temporaire.'},429);
  assert.equal(root.querySelector('[data-registry-search]').disabled,false);
  // A login redirect is not treated as a registry result.
  root.querySelector('[data-registry-search]').click();
  requests[5].resolve({ok:true,status:200,redirected:true}); await tick();
  assert.match(root.querySelector('[data-registry-status]').textContent,/session a expiré/);
  console.log('SIRET UI: debounce, explicit import, contact preservation, text escaping, stale responses, changed SIRET, provider errors, Enter and expired session passed.');
  dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
