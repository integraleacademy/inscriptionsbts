/* Local display refresh: never start WEDOF discovery from the directory. */
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const code = fs.readFileSync('static/js/campus.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const row = (id, label = 'À vérifier') => `<tr data-enrollment-id="${id}" data-bts="MOS" data-year="2026"><td><input type="checkbox" data-select-student value="${id}"></td><td><span>${label}</span><img data-student-photo src="/photo/${id}"></td><td><select><option value="">Choisir</option><option value="p1">P1</option><option value="p2">P2</option></select><button data-assign-one>Affecter</button></td></tr>`;
function setup({queue = ['alpha'], failure = false} = {}) {
  const dom = new JSDOM(`<main data-enrollments data-csrf="campus-token" data-wedof-csrf="wedof-token"><div data-enrollment-stats>Initial</div><p data-contract-feedback></p><button data-check-contracts>Vérifier</button><form class="campus-filters"><select name="mode"><option value="distanciel">Distanciel</option></select></form><strong data-selected-count></strong><select id="bulk-promotion"><option value="">Choisir</option><option value="p1" data-bts="MOS" data-year="2026">P1</option></select><button data-assign-bulk disabled>Affecter</button><p data-enrollment-feedback hidden></p><table><thead><tr><th><input type="checkbox" data-select-all></th></tr></thead><tbody data-enrollment-rows>${row('alpha')}${row('beta')}</tbody></table><script type="application/json" data-contract-discovery>${JSON.stringify(queue)}</script></main>`, {url: 'https://school.example/admin/inscriptions?mode=distanciel&contract=yes', runScripts: 'outside-only'});
  const w = dom.window, calls = [];
  let submits = 0;
  w.HTMLFormElement.prototype.requestSubmit = () => {submits++;};
  w.fetch = async (url, options) => {
    calls.push({url, options});
    assert.ok(!url.endsWith('/detecter'), 'The directory must not trigger WEDOF reads');
    if (url === '/admin/inscriptions/affecter') return {ok: false, json: async () => ({ok: false, error: 'Échec simulé'})};
    if (failure) return {ok: false, json: async () => ({ok: false, message: 'Lecture locale indisponible'})};
    return {ok: true, json: async () => ({ok: true, stats_html: '<strong data-kpi="with_contract">1</strong>', rows_html: row('alpha', 'Contrat trouvé') + row('beta'), discovery: []})};
  };
  w.eval(code);
  return {w, dom, calls, get submits() {return submits;}};
}
(async () => {
  const c = setup();
  const first = c.w.document.querySelector('[data-select-student]');
  first.checked = true; first.dispatchEvent(new c.w.Event('change', {bubbles: true}));
  c.w.document.querySelector('[data-enrollment-id="alpha"] select').value = 'p2';
  await tick();
  assert.equal(c.calls.length, 0, 'Opening a directory must not trigger checks');
  c.w.document.querySelector('[data-check-contracts]').click();
  await tick(); await tick();
  assert.equal(c.calls.length, 1);
  assert.equal(c.calls[0].url, '/admin/inscriptions/donnees?mode=distanciel&contract=yes');
  assert.equal(c.calls[0].options.method, undefined);
  assert.match(c.w.document.querySelector('[data-contract-feedback]').textContent, /chaque jour à 8 h/);
  assert.equal(c.w.document.querySelector('[data-kpi="with_contract"]').textContent, '1');
  assert.equal(c.w.document.querySelector('[data-select-student]').checked, true);
  assert.equal(c.w.document.querySelector('[data-enrollment-id="alpha"] select').value, 'p2');
  assert.match(c.w.document.querySelector('[data-selected-count]').textContent, /1 étudiant/);
  const photo = c.w.document.querySelector('[data-student-photo]');
  photo.dispatchEvent(new c.w.Event('error')); assert.equal(photo.hidden, true);
  c.w.document.querySelector('[data-assign-one]').click(); await tick();
  const assignment = c.calls.find(call => call.url.endsWith('/affecter'));
  assert.deepEqual(JSON.parse(assignment.options.body), {ids: ['alpha'], promotion_id: 'p2'});
  assert.equal(assignment.options.headers['X-CSRF-Token'], 'campus-token');
  assert.match(c.w.document.querySelector('[data-enrollment-feedback]').textContent, /Échec simulé/);
  c.w.document.querySelector('.campus-filters select').dispatchEvent(new c.w.Event('change', {bubbles: true}));
  assert.equal(c.submits, 1);
  c.dom.window.close();

  const failed = setup({queue: ['alpha', 'beta'], failure: true});
  failed.w.document.querySelector('[data-check-contracts]').click();
  await tick(); await tick();
  assert.equal(failed.calls.filter(call => call.url.endsWith('/detecter')).length, 0);
  assert.match(failed.w.document.querySelector('[data-contract-feedback]').textContent, /Lecture locale indisponible/);
  assert.equal(failed.w.document.querySelectorAll('[data-enrollment-id]').length, 2);
  assert.equal(failed.w.document.querySelector('[data-check-contracts]').disabled, false);
  failed.dom.window.close();

  const focused = setup();
  const selector = focused.w.document.querySelector('[data-enrollment-id="alpha"] select');
  selector.value = 'p2'; selector.focus();
  focused.w.document.querySelector('[data-check-contracts]').click();
  await tick(); await tick();
  assert.equal(focused.w.document.activeElement, selector);
  assert.equal(focused.w.document.querySelector('[data-enrollment-id="alpha"] select'), selector);
  selector.blur(); await new Promise(resolve => setTimeout(resolve, 10)); await tick();
  assert.notEqual(focused.w.document.querySelector('[data-enrollment-id="alpha"] select'), selector);
  assert.equal(focused.w.document.querySelector('[data-enrollment-id="alpha"] select').value, 'p2');
  focused.dom.window.close();
  console.log('Enrollment UI: no automatic discovery, local refresh, photos, assignment and error handling passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
