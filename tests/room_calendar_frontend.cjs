/* Run with node tests/room_calendar_frontend.cjs (jsdom required).
   Exercise the shipped UI, including the batch payload and failed drops. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.join(__dirname, '..');
const template = fs.readFileSync(path.join(root, 'templates/_room_schedule.html'), 'utf8').replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '');
const script = fs.readFileSync(path.join(root, 'static/js/room-schedule.js'), 'utf8');
const tick = async () => { for (let i = 0; i < 5; i++) await new Promise(setImmediate); };
const base = (key, day, room, extra = {}) => ({key, date: '2027-01-' + day, room_id: room, title: key,
  source: 'bts', formation: 'BTS', start_min: 540, end_min: 660, start: '09:00', end: '11:00', version: 1, ...extra});
async function fixture(unassigned = false) {
  const dom = new JSDOM('<main class="catalog-app" data-csrf="test-token">' + template + '</main>', {
    url: 'https://school.example.test/admin/salles', runScripts: 'outside-only'});
  const {window: w} = dom, doc = w.document;
  const rows = [base('course:a', '04', 'r1'), base('session:b', '05', 'r2', {source: 'session', formation: 'APS', owner: 'session:one', revision: 'revision-1', room_version: 1}),
    base('session:c', '06', 'r2', {source: 'session', formation: 'APS', owner: 'session:one', revision: 'revision-1', room_version: 1, exam: true}),
    base('course:untouched', '07', 'r1'), base('course:next-week', '11', 'r2'),
    base('unavailable:closed', '05', 'r3', {source: 'unavailable', formation: 'UNAVAILABLE', title: 'Travaux'})];
  const rooms = ['r1', 'r2', 'r3', 'r4', 'r5'].map(id => ({id, name: 'Salle ' + id, active: id !== 'r4'}));
  if (unassigned) rows.push(base('session:roomless', '04', null, {source: 'session', formation: 'DESP', owner: 'session:new', revision: 'new-revision', room_version: 2}));
  const sessions = [
    {owner: 'session:one', name: 'APS JANVIER 2027', start: '2027-01-05', assigned: true, assigned_count: 2, unassigned_count: 0, generated: true},
    {owner: 'session:new', name: 'DESP JANVIER 2027', start: '2027-01-04', assigned: false, assigned_count: 0, unassigned_count: 1, generated: true},
    {owner: 'session:missing', name: 'SSIAP FÉVRIER 2027', start: '2027-02-01', end: '2027-02-10', assigned: false, unassigned_count: 0, needs_schedule: true, generated: false},
    {owner: 'session:remote', name: 'En ligne', assigned: false, unassigned_count: 0, needs_schedule: false, generated: true}];
  const posts = [], reads = []; let fail = false, release = null;
  w.HTMLDialogElement.prototype.showModal = function() { this.open = true; };
  w.HTMLDialogElement.prototype.close = function() { this.open = false; this.dispatchEvent(new w.Event('close')); };
  w.scrollTo = () => {};
  w.fetch = async (url, options) => {
    if (url === '/admin/planning/api/rooms/sessions') return {ok: true, json: async () => ({sessions})};
    if (url.startsWith('/admin/planning/api/rooms/schedule?')) {
      reads.push(url); const query = new URL(url, w.location).searchParams;
      const visible = rows.filter(r => r.date >= query.get('start') && r.date <= query.get('end'));
      const unassignedCount = visible.filter(r => !r.room_id).length;
      return {ok: true, json: async () => ({rooms: unassignedCount ? [{id: null, name: 'À affecter', unassigned: true, active: true}, ...rooms] : rooms,
        reservations: structuredClone(visible), unassigned_count: unassignedCount,
        unassigned_sessions: unassigned ? sessions.filter(s => s.unassigned_count || s.needs_schedule) : [], connected: true, ready: true})};
    }
    assert.equal(url, '/admin/planning/api/rooms/calendar-move');
    assert.equal(options.headers['X-CSRF-Token'], 'test-token');
    const payload = JSON.parse(options.body); posts.push(payload);
    if (release) await new Promise(resolve => { release = resolve; });
    if (fail) return {ok: false, json: async () => ({message: 'Aucune salle modifiée : un créneau a changé.'})};
    for (const item of payload.slots) rows.find(r => r.key === item.key).room_id = payload.room_id;
    return {ok: true, json: async () => ({ok: true, count: payload.slots.length})};
  };
  w.eval(script);
  const $ = id => doc.getElementById(id);
  const week = async value => { $('rooms-date').value = value; $('rooms-date').dispatchEvent(new w.Event('change')); await tick(); };
  await week('2027-01-04');
  const card = key => [...doc.querySelectorAll('button[data-key]')].find(n => n.dataset.key === key);
  const cell = (room, date = '2027-01-04') => doc.querySelector(`td[data-room-id="${room}"][data-date="${date}"]`);
  const transfer = {setData() {}, effectAllowed: '', dropEffect: ''};
  const event = (element, name) => {
    const e = new w.Event(name, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'dataTransfer', {value: transfer}); element.dispatchEvent(e); return e;
  };
  const start = key => event(card(key), 'dragstart');
  const drop = async (room, date) => { event(cell(room, date), 'dragover'); event(cell(room, date), 'drop'); await tick(); };
  const select = (...keys) => { if ($('rooms-multiple').getAttribute('aria-pressed') !== 'true') $('rooms-multiple').click(); keys.forEach(key => card(key).click()); };
  return {w, doc, rows, posts, reads, $, week, card, cell, start, drop, select, event,
    finishSessions: () => { sessions.forEach(s => { s.unassigned_count = 0; s.needs_schedule = false; s.assigned = true; }); rows.filter(r => !r.room_id).forEach(r => r.room_id = 'r5'); },
    reject: () => { fail = true; }, hold: () => { release = true; }, release: () => release(), close: () => dom.window.close()};
}
async function run() {
  let f = await fixture();
  try {
    f.select('course:a', 'session:b', 'session:c');
    assert.match(f.$('rooms-selected-count').textContent, /3.*tout le groupe/);
    assert.ok(!f.start('course:a').defaultPrevented);
    assert.equal(f.doc.querySelectorAll('.room-dragging').length, 3);
    assert.equal(f.card('course:a').dataset.dragCount, '3');
    assert.match(f.$('rooms-drag-status').textContent, /3 créneaux/);
    const reads = f.reads.length;
    f.w.dispatchEvent(new f.w.CustomEvent('academy:rooms-changed')); await tick();
    assert.equal(f.reads.length, reads, 'polling must wait for the group drag');
    f.hold(); const dropping = f.drop('r5'); await tick();
    assert.equal(f.posts.length, 1);
    assert.ok(f.$('rooms-move-selected').disabled && f.$('rooms-clear-selected').disabled);
    assert.deepEqual(f.posts[0], {room_id: 'r5', slots: [
      {key: 'course:a', date: '2027-01-04', version: 1},
      {key: 'session:b', date: '2027-01-05', version: 1, revision: 'revision-1', room_version: 1},
      {key: 'session:c', date: '2027-01-06', version: 1, revision: 'revision-1', room_version: 1}]});
    f.release(); await dropping; await tick();
    assert.equal(f.doc.querySelectorAll('.selected, .room-dragging, [data-drag-count]').length, 0);
    assert.match(f.$('rooms-drag-status').textContent, /Les 3 créneaux ont été affectés/);
    assert.equal(f.rows.find(r => r.key === 'course:untouched').room_id, 'r1');
    assert.equal(f.card('session:c').closest('td').dataset.roomId, 'r5');
    assert.ok(f.card('session:c').classList.contains('room-exam'));
    assert.ok(f.reads.length > reads);
  } finally { f.close(); }

  f = await fixture();
  try {
    f.select('course:a', 'session:b');
    f.start('course:a'); await f.drop('r3');
    assert.equal(f.posts.length, 0, 'a closure on another selected day blocks the whole group');
    assert.match(f.$('rooms-drag-status').textContent, /05\/01\/2027.*Travaux/);
    assert.equal(f.doc.querySelectorAll('.selected').length, 2);
    f.start('course:a'); await f.drop('r4'); assert.equal(f.posts.length, 0, 'inactive destination');
    f.start('course:a'); await f.drop('r5', '2027-01-05'); assert.equal(f.posts.length, 0, 'wrong date column');
    f.start('course:a'); f.event(f.card('course:a'), 'dragend'); await tick();
    assert.equal(f.posts.length, 0); assert.equal(f.doc.querySelectorAll('.selected').length, 2);
    // The anchor is already in r1, but the other selected booking is not.
    f.start('course:a'); await f.drop('r1'); assert.equal(f.posts.length, 1);
    assert.equal(f.posts[0].slots.length, 2);
  } finally { f.close(); }

  f = await fixture();
  try {
    f.rows.push(base('course:overlap', '04', 'r2'));
    await f.week('2027-01-04');
    f.select('course:a', 'course:overlap'); f.start('course:a'); await f.drop('r5');
    assert.equal(f.posts.length, 0, 'selected bookings must not collide with each other');
    assert.match(f.$('rooms-drag-status').textContent, /Aucun créneau ne sera déplacé/);
  } finally { f.close(); }

  f = await fixture();
  try {
    f.select('course:a', 'session:b');
    assert.ok(f.start('course:untouched').defaultPrevented, 'unselected cards cannot silently replace the group');
    assert.equal(f.posts.length, 0);
    f.reject(); f.start('course:a'); await f.drop('r5');
    assert.equal(f.posts.length, 1); assert.equal(f.posts[0].slots.length, 2);
    assert.equal(f.rows[0].room_id, 'r1'); assert.equal(f.rows[1].room_id, 'r2');
    assert.equal(f.doc.querySelectorAll('.selected').length, 2, 'failed batch keeps selection');
    assert.ok(!f.$('rooms-move-selected').disabled);
    assert.match(f.$('rooms-drag-status').textContent, /Aucune salle modifiée/);
  } finally { f.close(); }

  f = await fixture();
  try {
    f.select('course:a'); await f.week('2027-01-11'); f.select('course:next-week');
    f.start('course:next-week'); await f.drop('r5', '2027-01-11');
    assert.deepEqual(f.posts[0].slots.map(r => r.date), ['2027-01-04', '2027-01-11']);
    assert.ok(f.rows.filter(r => ['course:a', 'course:next-week'].includes(r.key)).every(r => r.room_id === 'r5'));
  } finally { f.close(); }

  f = await fixture();
  try {
    await f.drop('r5'); assert.equal(f.posts.length, 0, 'external drags cannot mutate bookings');
    f.start('course:a'); await f.drop('r5'); assert.equal(f.posts[0].slots.length, 1, 'ordinary single drag still works');
    await new Promise(resolve => setTimeout(resolve, 400)); // native drag's trailing click is suppressed
    f.select('session:b', 'session:c'); f.$('rooms-move-selected').click();
    assert.ok(f.$('rooms-course-dialog').open, 'keyboard/click bulk dialog remains available');
    assert.match(f.$('rooms-course-heading').textContent, /2 créneaux/);
  } finally { f.close(); }

  f = await fixture();
  try {
    const view = f.$('rooms-planner-view'), parent = view.parentNode;
    f.select('course:a', 'session:b'); f.$('rooms-fullscreen').click();
    assert.ok(f.$('rooms-fullscreen-dialog').open);
    assert.equal(view.parentNode, f.$('rooms-fullscreen-dialog'));
    assert.equal(f.doc.querySelectorAll('.room-booking.selected').length, 2);
    f.$('rooms-fullscreen').click();
    assert.equal(view.parentNode, parent); assert.ok(!f.$('rooms-fullscreen-dialog').open);
    assert.equal(f.$('rooms-fullscreen').getAttribute('aria-pressed'), 'false');
    assert.equal(f.cell('r4').querySelector('.room-create'), null, 'inactive rooms cannot be booked');
    f.cell('r5').querySelector('.room-create').click();
    const form = f.$('rooms-reservation-form');
    assert.ok(f.$('rooms-reservation-dialog').open);
    assert.equal(form.elements.room_id.value, 'r5'); assert.equal(form.elements.date.value, '2027-01-04');
    form.elements.title.value = 'Examen VTC'; form.elements.title.dispatchEvent(new f.w.Event('input'));
    assert.ok(form.elements.exam.checked);
    form.elements.exam.checked = false; form.elements.exam.dispatchEvent(new f.w.Event('change'));
    form.elements.title.value = 'Examen blanc'; form.elements.title.dispatchEvent(new f.w.Event('input'));
    assert.ok(!form.elements.exam.checked, 'the user can override the exam suggestion');
    form.elements.all_day.checked = true; form.elements.all_day.dispatchEvent(new f.w.Event('change'));
    assert.ok(form.elements.start.disabled && form.elements.end.disabled);
    assert.ok(f.$('rooms-reservation-times').hidden);
    assert.equal(f.posts.length, 0, 'opening a free slot never creates a booking');
  } finally { f.close(); }
  f = await fixture(true);
  try {
    assert.equal(f.doc.querySelector('#rooms-calendar tbody tr:first-child th').textContent, 'Salle r1');
    assert.equal(f.card('session:roomless'), undefined, 'unassigned slots are not in the room matrix');
    assert.equal(f.cell(''), null, 'no virtual room row');
    assert.match(f.$('rooms-status').textContent, /5 salle\(s\) · 5 réservation\(s\)/);
    assert.ok(!f.$('rooms-status').textContent.includes('sans salle'));
    assert.equal(f.$('rooms-session-count').textContent, '2');
    assert.ok(!f.$('rooms-session-count').hidden);
    assert.equal(f.$('rooms-unassigned-sessions').getAttribute('aria-label'), 'Sessions à affecter : 2 sessions en attente');
    await f.week('2027-01-11');
    assert.equal(f.$('rooms-session-count').textContent, '2', 'count covers all pending sessions, not only the displayed week');
    f.$('rooms-fullscreen').click();
    const panel = f.$('rooms-session-panel'), parent = panel.parentNode;
    f.$('rooms-unassigned-sessions').click(); await tick();
    assert.ok(f.$('rooms-sessions-dialog').open && f.$('rooms-fullscreen-dialog').open);
    const form = f.$('rooms-session-form');
    assert.deepEqual([...form.elements.owner.options].map(n => n.value), ['', 'session:new', 'session:missing']);
    form.elements.owner.value = 'session:missing'; form.elements.owner.dispatchEvent(new f.w.Event('change'));
    assert.ok(!f.$('rooms-session-fallback').hidden && !f.$('rooms-session-fallback').disabled);
    assert.match(f.$('rooms-session-detail').textContent, /01\/02\/2027.*compléter/);
    f.$('rooms-sessions-only-unassigned').checked = false; f.$('rooms-sessions-only-unassigned').dispatchEvent(new f.w.Event('change'));
    assert.equal(form.elements.owner.options.length, 5);
    f.$('rooms-sessions-dialog').close(); await tick();
    assert.equal(panel.parentNode, parent);
    assert.ok(f.$('rooms-fullscreen-dialog').open);
    f.finishSessions(); await f.week('2027-01-04');
    assert.ok(f.$('rooms-session-count').hidden, 'notification disappears automatically when no sessions remain');
    assert.equal(f.$('rooms-unassigned-sessions').getAttribute('aria-label'), 'Sessions à affecter : aucune session en attente');
    assert.equal(f.card('session:roomless').closest('td').dataset.roomId, 'r5');
    assert.equal(f.posts.length, 0, 'opening the list never assigns a room');
  } finally { f.close(); }
  console.log('Room calendar: group drag, conflicts, fullscreen, free bookings and unassigned sessions passed.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
