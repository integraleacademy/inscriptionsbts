/* Run with node tests/room_month_frontend.cjs (jsdom required). */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/_room_month.html'), 'utf8').replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '');
const script = fs.readFileSync(path.join(root, 'static/js/room-month.js'), 'utf8');
const storageKey = 'bts.roomAvailability.excludedRooms.v1';
const tick = () => new Promise(resolve => setImmediate(resolve));

async function fixture(saved, extraRoom = false) {
  const dom = new JSDOM('<a id="room-month-open"></a>' + html, {
    url:'https://school.example.test/admin/salles?vue=disponibilites&mois=2027-01', runScripts:'outside-only'
  });
  const w = dom.window, doc = w.document, reads = [];
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new w.Event('close')); };
  if (saved !== undefined) w.localStorage.setItem(storageKey, saved);
  w.fetch = async (url, options) => {
    assert.equal(options.method || 'GET', 'GET');
    reads.push(url);
    const params = new URL(url, w.location.href).searchParams;
    const first = params.get('from'), day = first.startsWith('2027-01') ? '2027-01-04' : first;
    const starters = [['a','Salle 2B','free'], ['b','Annexe Vernèdes','partial'], ['c','Atelier Modulable Paris','busy']];
    if (extraRoom) starters.push(['d','Nouvelle salle','free']);
    const rooms = starters.map(([id,name,state]) => ({id, name, active:1, free_days:Number(state === 'free'),
      days:{[day]:{state, free:state === 'free' ? [['08:00','18:00']] : state === 'partial' ? [['12:00','18:00']] : []}}}));
    return {ok:true, json:async () => ({rooms, dates:[day], first, last:params.get('to'), connected:true})};
  };
  w.eval(script);
  await tick();
  const $ = id => doc.getElementById('room-month-' + id);
  const toggle = id => $('filter-choices').querySelector('input[value="' + id + '"]').click();
  return {w, $, toggle, reads, doc};
}

async function checkStableNavigation() {
  const {w, $, doc} = await fixture();
  const dialog = doc.getElementById('room-month');
  const originalFetch = w.fetch;
  const requests = [];
  w.fetch = (url, options) => new Promise(resolve => {
    requests.push({signal:options.signal, finish:() => resolve(originalFetch(url, options))});
  });

  const january = $('days').firstElementChild;
  assert.equal($('days').children.length, 42);
  $('next').click();
  assert.equal($('results').hidden, false);
  assert.equal($('results').getAttribute('aria-busy'), 'true');
  assert.equal($('calendar').inert, true);
  assert.match($('loading').textContent, /février 2027/);
  assert.equal($('days').firstElementChild, january);
  assert.match($('heading').textContent, /janvier 2027/);
  $('next').click();
  assert.equal(requests[0].signal.aborted, true);
  requests[1].finish(); await tick();
  requests[0].finish(); await tick();
  assert.match($('heading').textContent, /mars 2027/);
  assert.equal($('calendar').inert, false);
  assert.equal($('loading').hidden, true);
  assert.equal($('days').children.length, 42);
  $('prev').click();
  requests[2].finish(); await tick();
  assert.match($('heading').textContent, /février 2027/);
  assert.equal($('days').children.length, 42);
  assert.equal($('days').querySelectorAll('button').length, 28);

  // A browser without the Fullscreen API can still expand the dialog and leave with Escape.
  $('fullscreen').click();
  assert.equal(dialog.classList.contains('month-expanded'), true);
  assert.equal($('fullscreen').getAttribute('aria-pressed'), 'true');
  assert.match($('fullscreen-label').textContent, /Quitter/);
  const cancel = new w.Event('cancel', {cancelable:true});
  dialog.dispatchEvent(cancel);
  assert.equal(cancel.defaultPrevented, true);
  assert.equal(dialog.open, true);
  assert.equal($('fullscreen').getAttribute('aria-pressed'), 'false');
  $('fullscreen').click();
  $('next').click();
  dialog.querySelector('.tool-close').click();
  assert.equal(requests[3].signal.aborted, true);
  requests[3].finish(); await tick();
  assert.equal(doc.documentElement.classList.contains('room-month-open'), false);
  assert.equal(dialog.classList.contains('month-expanded'), false);
  assert.match($('heading').textContent, /février 2027/);
  w.close();
}

(async () => {
  const a = await fixture('not JSON');
  const {w,$,toggle,reads} = a;
  const day = () => $('days').querySelector('[data-date]');
  assert.equal($('free').textContent, 'Salle 2B');
  $('filter-toggle').click();
  assert.equal($('filter-toggle').getAttribute('aria-expanded'), 'true');
  toggle('a');
  assert.equal(reads.length, 1);
  assert.match($('filter-count').textContent, /1 salle exclue sur 3/);
  assert.equal(day().className, 'partial');
  assert.match(day().getAttribute('aria-label'), /0 salle\(s\) libre\(s\), 1 partiellement/);
  assert.doesNotMatch($('free').textContent + $('list').textContent, /Salle 2B/);
  assert.match($('list').textContent, /12:00–18:00/);
  toggle('b');
  assert.equal(day().className, 'busy');
  assert.equal(day().querySelector('small').textContent, 'Aucune');
  $('next').click(); await tick();
  assert.equal(day().dataset.date, '2027-02-01');
  assert.equal($('filter-choices').querySelector('[value="b"]').checked, true);
  assert.doesNotMatch($('list').textContent, /Annexe/);
  toggle('c');
  assert.equal($('calendar').hidden, true);
  assert.match($('empty').textContent, /Toutes les salles sont exclues/);
  const saved = w.localStorage.getItem(storageKey);
  const b = await fixture(saved, true);
  assert.equal(b.$('free').textContent, 'Nouvelle salle');
  assert.equal(b.$('list').querySelectorAll('article').length, 1);
  b.w.close();
  $('filter-reset').click();
  assert.equal($('calendar').hidden, false);
  assert.equal($('empty').hidden, true);
  assert.equal($('list').querySelectorAll('article').length, 3);
  assert.equal($('filter-choices').querySelectorAll('input:checked').length, 0);
  assert.equal(w.localStorage.getItem(storageKey), null);
  assert.equal(reads.length, 2);
  w.close();
  await checkStableNavigation();
  console.log('Disponibilités mensuelles, exclusions, navigation rapide et plein écran vérifiés.');
})().catch(error => { console.error(error); process.exit(1); });
