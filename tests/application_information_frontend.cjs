// Run against a Flask-rendered application page with jsdom on NODE_PATH:
// node tests/application_information_frontend.cjs /path/to/application.html
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync(process.argv[2], 'utf8');
let checks = 0;
function check(condition, message) { assert.ok(condition, message); checks++; }
function setup(saved = null) {
  const dom = new JSDOM(html, {url: 'https://example.test/candidature', runScripts: 'outside-only'});
  const w = dom.window;
  w.matchMedia = () => ({matches: true});
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.fetch = () => { throw new Error('Network requests are forbidden in this test'); };
  w.document.getElementById('saved-application').textContent = JSON.stringify(saved);
  w.eval(fs.readFileSync('static/js/admission-validation.js', 'utf8'));
  w.eval(fs.readFileSync('static/js/application-2027.js', 'utf8'));
  const d = w.document;
  function choose(name, value) {
    const input = d.querySelector(`input[name="${name}"][value="${value}"]`);
    check(!!input && !input.disabled, `${name}=${value} can be selected`);
    input.checked = true;
    input.dispatchEvent(new w.Event('change', {bubbles: true}));
  }
  return {dom, w, d, choose};
}

const {dom, w, d, choose} = setup();
check(d.getElementById('formation-info').hidden, 'No unrelated programme shown initially');
for (const [code, phrase] of Object.entries({
  MOS: 'sécurité privée', MCO: 'management d’équipe', NDRC: 'marketing digital',
  PI: 'conseillers immobiliers', CI: 'import-export', CG: 'finance d’entreprise'
})) {
  choose('bts', code);
  const panels = [...d.querySelectorAll('[data-training-info]')].filter(el => !el.hidden);
  check(!d.getElementById('formation-info').hidden && panels.length === 1, `One visible information panel for ${code}`);
  check(panels[0].dataset.trainingInfo === code && panels[0].textContent.includes(phrase), `${code} content matches selection`);
  check(panels[0].textContent.includes('2 ans') && panels[0].textContent.includes('Niveau 5'), `${code} diploma facts preserved`);
}
choose('mode', 'distanciel');
check(d.getElementById('infosDistanciel').open, 'Distance guidance opens on selection');
d.getElementById('infosDistanciel').open = false;
choose('bts', 'MCO');
check(!d.getElementById('infosDistanciel').open, 'Other changes respect manually closed guidance');
choose('mode', 'presentiel');
check(!d.getElementById('infosDistanciel').open, 'In-person selection closes distance guidance');
choose('bts', 'MOS');
choose('mos_parcours', 'autre');
choose('aps_souhaitee', 'oui');
check([...d.querySelectorAll('[data-condition="aps-yes"]')].every(el => !el.hidden), 'APS process appears in selection and recap');
choose('bts', 'MCO');
check([...d.querySelectorAll('[data-condition="aps-yes"]')].every(el => el.hidden), 'APS guidance disappears for another BTS');
check(!new w.FormData(d.getElementById('application-form')).has('aps_souhaitee'), 'Non-MOS payload excludes hidden APS fields');
choose('bts', 'MOS');
check([...d.querySelectorAll('[data-condition="aps-yes"]')].every(el => !el.hidden), 'Returning to MOS immediately restores the previous answers and guidance');
choose('aps_souhaitee', 'non');
check(!d.querySelector('[data-condition="aps-no"]').hidden, 'APS refusal shows the reason');
choose('mos_parcours', 'bac_pro_ms');
check(d.querySelector('[data-condition="aps"]').hidden, 'Bac pro MS does not require APS');
choose('mos_parcours', 'carte_cnaps');
check(d.querySelector('[data-condition="aps"]').hidden, 'Existing CNAPS card does not require APS');
choose('mos_parcours', 'autre');
choose('aps_souhaitee', 'oui');
d.querySelector('[data-step="6"]').click();
const recap = d.querySelector('.application-step[data-title="Le récapitulatif"]');
check(!recap.hidden, 'Recap can be opened in admin preview');
check(recap.textContent.includes('0 € pour l’apprenti') && recap.textContent.includes('Je confirme mon inscription'), 'Funding and admission next steps retained in recap');
check(d.getElementById('application-recap').textContent.includes('BTS MOS'), 'Recap retains selected programme');
check(d.getElementById('send-application').disabled, 'Admin preview cannot submit a real application');
dom.window.close();

for (const code of ['MOS', 'MCO', 'NDRC', 'PI', 'CI', 'CG']) {
  const {dom, d} = setup({bts: code, mode: 'distanciel', mos_parcours: 'autre', aps_souhaitee: 'oui'});
  check(!d.querySelector(`[data-training-info="${code}"]`).hidden, `${code} draft restores its information without another click`);
  check(d.getElementById('infosDistanciel').open, `${code} draft restores distance details`);
  check(d.querySelector('[data-condition="aps-yes"]').hidden === (code !== 'MOS'), `${code} draft restores the correct APS state`);
  dom.window.close();
}
console.log(`PASS: ${checks} application information interaction checks, no network or messages.`);
