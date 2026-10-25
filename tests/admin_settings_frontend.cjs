const fs = require('node:fs'), assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const dom = new JSDOM(fs.readFileSync('tmp/reference-qa/settings.html', 'utf8'), {url:'https://example.test/admin/parametres', runScripts:'outside-only'});
const w = dom.window, $ = id => w.document.getElementById(id);
let configured = true, managed = false, failure = false, writes = [];
w.fetch = async (url, options) => {
  assert.equal(url, '/admin/planning/api/references/settings');
  if (options.method !== 'GET') {
    assert(options.headers['X-CSRF-Token']);
    const data = JSON.parse(options.body); writes.push({method:options.method, data});
    if (!failure) configured = options.method === 'PUT';
  }
  return {ok:!failure,json:async()=>failure ? {ok:false,message:'Erreur de test'} : {ok:true,configured,managed_by_server:managed}};
};
const wait = () => new Promise(r => setTimeout(r, 10));
const submit = () => $('openai-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
w.eval(fs.readFileSync('static/js/admin-settings.js','utf8'));
(async () => {
  await wait();
  assert.equal($('openai-status').textContent,'Connexion configurée');
  assert.equal($('openai-key').value,''); assert.equal(writes.length,0);
  assert(!$('openai-form').hidden && !$('openai-remove').hidden);
  $('openai-key').value='sk-test-only-xxxxxxxxxxxxxxxxxxxxxxxx';submit();await wait();
  assert.equal(writes[0].method,'PUT');assert(writes[0].data.api_key.startsWith('sk-test-only-'));
  assert.equal($('openai-key').value,'');assert(!$('openai-success').hidden);
  assert.equal(w.sessionStorage.length,0);assert.equal(w.localStorage.length,0);
  failure=true;$('openai-remove').click();await wait();
  assert.equal($('openai-error').textContent,'Erreur de test');assert(configured);
  failure=false;$('openai-remove').click();await wait();
  assert(!configured);assert($('openai-remove').hidden);
  configured=true;managed=true;$('openai-retry').click();await wait();
  assert($('openai-form').hidden);assert(!$('openai-managed').hidden);assert($('openai-key').disabled);
  assert(!$('openai-error').textContent);assert(!w.document.body.textContent.includes('sk-test-only-'));
  console.log('Settings: saved configuration, key replacement, errors, removal and managed-server mode passed.');
  dom.window.close();
})().catch(error=>{console.error(error);process.exit(1)});
