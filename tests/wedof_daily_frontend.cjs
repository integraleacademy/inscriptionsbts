/* Opening a candidate tab only reads saved data; discovery needs an explicit click. */
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const dom = new JSDOM(`<main class="candidate-sheet" data-candidate-id="alice">
    <section id="panel-contrat-apprentissage" data-csrf="test-csrf" hidden>
      <button id="wc-add">Rattacher</button><button id="wc-close-search">Fermer</button>
      <p id="wc-notice"></p><p id="wc-error"></p><div id="wc-list"></div>
      <div id="wc-search"><form id="wc-search-form"><select id="wc-kind"><option value="wedof"></option></select>
        <input id="wc-reference"><select id="wc-financer"></select></form>
        <div id="wc-results"></div><div id="wc-preview"></div></div>
    </section></main>`, {url: 'https://school.example/admin/candidat/alice', runScripts: 'outside-only'});
  const w = dom.window, calls = [];
  w.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => options.method === 'GET'
      ? {ok: true, configured: true, has_contracts: false, html: '<button data-wc-detect>Rechercher maintenant</button>'}
      : {ok: true, pending: false, items: [], message: 'Recherche manuelle terminée.'}};
  };
  w.eval(fs.readFileSync('static/js/wedof-contracts.js', 'utf8'));
  await tick();
  assert.equal(calls.length, 0);
  const panel = w.document.getElementById('panel-contrat-apprentissage');
  panel.hidden = false;
  await tick(); await tick();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[0].url, '/admin/candidat/alice/contrats-apprentissage');
  panel.hidden = true;
  await tick();
  panel.hidden = false;
  await tick();
  assert.equal(calls.length, 1, 'Reopening the tab must not start WEDOF discovery');
  panel.querySelector('[data-wc-detect]').click();
  await tick();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, '/admin/candidat/alice/contrats-apprentissage/detecter');
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(calls[1].options.headers['X-CSRF-Token'], 'test-csrf');
  assert.deepEqual(JSON.parse(calls[1].options.body), {manual: true, origin: 'interactive'});
  dom.window.close();
  console.log('Candidate WEDOF UI: saved-data-only tab opening and explicit manual discovery passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
