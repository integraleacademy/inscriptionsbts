/* Real import template: catalogue selection, annual budgets and final selection. */
const fs = require('node:fs'), assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
require('node:child_process').execFileSync(process.env.PYTHON || 'python', ['tests/render_planning_import_fixture.py'], {stdio: 'pipe'});
const dom = new JSDOM(fs.readFileSync('tmp/import-qa/import.html', 'utf8'), {
  url: 'https://example.test/admin/planning/import?promotion_id=demo&period_id=demo:1', runScripts: 'outside-only', pretendToBeVisual: true,
});
const w = dom.window, d = w.document, $ = id => d.getElementById(id);
w.scrollTo = () => {};
const sources = ['ANGLAIS', 'ANGLAIS TD', 'EXPRESSION'];
const rows = sources.map((subject, i) => ({key: String(i), date: '2027-01-04', start: '09:00', end: '11:00', page: 1,
  subject_key: subject, subject, trainer: 'Mme EXEMPLE A.', duration_minutes: 120}));
const extraction = {ok: true, source_token: 'signed-source',
  document: {rows, minutes: 360, pages: 1, group: 'BTS MOS', first_date: '2027-01-04', last_date: '2027-01-04'},
  subjects: [{id: 'catalog:english', name: 'Anglais', prepare_on_import: true, planned_hours: 45, study_year: 2},
    {id: 'catalog:french', name: 'Expression <img src=x>', prepare_on_import: true, planned_hours: null},
    {id: 'existing', name: 'Matière déjà préparée', planned_hours: 50}],
  trainers: [{id: 'teacher', nom: 'EXEMPLE', prenom: 'Alex', assigned: false}], new_trainers: [], rooms: [],
  mappings: {subjects: {ANGLAIS: 'catalog:english', 'ANGLAIS TD': 'catalog:english', EXPRESSION: ''},
    subject_trainers: Object.fromEntries(sources.map(s => [s, 'teacher']))},
};
let requests = [];
w.fetch = async (url, options) => {
  assert.equal(options.headers['X-CSRF-Token'], d.querySelector('.planning-import').dataset.csrf);
  if (url.endsWith('/analyze')) return {ok: true, json: async () => extraction};
  const body = JSON.parse(options.body); requests.push({url, body});
  if (url.endsWith('/preview')) return {ok: true, json: async () => ({ok: true, preview_token: 'signed-review',
    summary: {ready: 3, duplicate: 0, blocked: 0, minutes: 360}, calendar_changes: [],
    subject_preparations: [{id: 'new-english', name: 'Anglais', planned_hours: 45}, {id: 'new-french', name: 'Expression', planned_hours: 24}],
    trainer_assignments: [extraction.trainers[0]], trainer_creations: [],
    items: rows.map((row, i) => ({...row, status: 'ready', issues: [], trainer_id: 'teacher', subject_id: i === 2 ? 'new-french' : 'new-english'})),
  })};
  assert(url.endsWith('/commit')); return {ok: true, json: async () => ({ok: true, message: 'Cours importé.'})};
};
const wait = () => new Promise(resolve => setTimeout(resolve, 10));
const change = input => input.dispatchEvent(new w.Event('change', {bubbles: true}));
const edit = (input, value) => { input.value = value; input.dispatchEvent(new w.Event('input', {bubbles: true})); };
const submit = id => $(id).dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
const select = source => [...d.querySelectorAll('select[data-mapping=subjects]')].find(s => s.dataset.source === source);
const hours = id => d.querySelector('input[data-subject="catalog:' + id + '"]');
Object.defineProperty($('pi-file'), 'files', {value: [new w.File(['pdf'], 'planning.pdf', {type: 'application/pdf'})]});
$('pi-upload-form').reportValidity = () => true;
w.eval(fs.readFileSync('static/js/planning-import.js', 'utf8'));
(async () => {
  submit('pi-upload-form'); await wait();
  assert(!$('pi-mapping-section').hidden && $('pi-empty-subjects').hidden);
  assert.equal(select('ANGLAIS').value, 'catalog:english');
  assert.equal(select('ANGLAIS').querySelectorAll('optgroup').length, 2);
  assert.equal(d.querySelectorAll('#pi-subject-hours input').length, 0); // known volume needs no entry
  assert.equal(d.querySelectorAll('.pi-subject-volume').length, 1); // two labels, one catalogue volume
  assert($('pi-subject-hours').textContent.includes('45 h'));
  assert($('pi-subject-hours').textContent.includes('Repris automatiquement de Matières · 2e année'));
  select('EXPRESSION').value = 'catalog:french'; change(select('EXPRESSION'));
  assert.equal(hours('english'), null);
  assert(hours('french').required && hours('french').validity.valueMissing);
  assert.equal($('pi-subject-hours').querySelectorAll('img').length, 0);
  edit(hours('french'), '24');
  select('EXPRESSION').value = 'existing'; change(select('EXPRESSION')); assert.equal(hours('french'), null);
  select('EXPRESSION').value = 'catalog:french'; change(select('EXPRESSION')); assert.equal(hours('french').value, '24');
  assert($('pi-mapping-form').checkValidity());
  submit('pi-mapping-form'); await wait();
  assert.deepEqual(requests[0].body.subject_hours, {'catalog:french': '24'});
  assert(!$('pi-preview-section').hidden && !$('pi-subject-preparations').hidden);
  assert.equal($('pi-subject-preparation-list').children.length, 2);
  $('pi-select-all').checked = false; change($('pi-select-all'));
  assert($('pi-commit').disabled && $('pi-subject-preparations').hidden);
  const boxes = [...$('pi-courses').querySelectorAll('input')]; boxes[0].checked = true; change(boxes[0]);
  assert.equal($('pi-subject-preparation-list').children.length, 1);
  assert($('pi-subject-preparation-list').textContent.includes('Anglais'));
  $('pi-back').click(); assert($('pi-preview-section').hidden && !$('pi-mapping-section').hidden);
  assert.equal(hours('english'), null);
  submit('pi-mapping-form'); await wait(); $('pi-select-all').checked = false; change($('pi-select-all'));
  const chosen = $('pi-courses').querySelector('input'); chosen.checked = true; change(chosen);
  $('pi-commit').click(); await wait();
  assert.deepEqual(requests.at(-1).body, {preview_token: 'signed-review', selected_keys: ['0']});
  assert(!$('pi-success').hidden);
  $('pi-new-file').click(); extraction.subjects = []; submit('pi-upload-form'); await wait();
  assert(!$('pi-empty-subjects').hidden);
  assert($('pi-empty-subjects').querySelector('a').href.includes('/admin/matieres?diploma=MOS'));
  console.log('PASS: catalogue choices, automatic known annual budgets, required missing hours, safe labels, selection summary and commit payload.');
  dom.window.close();
})().catch(error => { console.error(error); dom.window.close(); process.exitCode = 1; });
