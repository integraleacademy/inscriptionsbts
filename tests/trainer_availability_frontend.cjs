/* DOM interactions against the real page structure; no browser or network. */
const fs = require('fs');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const source = fs.readFileSync('static/js/trainer-availability.js', 'utf8');
const template = fs.readFileSync('templates/trainer_availability.html', 'utf8');
let checks = 0;
const check = (actual, expected, message) => { assert.deepEqual(actual, expected, message); checks++; };
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
const baseDays = () => [
  { date:'2027-01-01', public_holiday:'Jour de l’an' },
  { date:'2027-01-05', course_count:2 },
  { date:'2027-01-07', admin_unavailable:true, unavailable:true, reason:'Absence indiquée par l’école' },
  { date:'2027-01-08', own_unavailable:true, unavailable:true },
  { date:'2027-01-09', admin_unavailable:true, unavailable:true, partial:true },
  { date:'2027-01-11', admin_unavailable:true, own_unavailable:true, unavailable:true }
];

function makePage() {
  let snapshot = { year:2026, school_year:true, label:'2026–2027', months:['2026-09','2026-10','2026-11','2026-12','2027-01','2027-02','2027-03','2027-04','2027-05','2027-06','2027-07'], today:'2027-01-04', min_date:'2027-01-04', days:baseDays(), revision:0 };
  const config = { year:2027, csrf_token:'fixture-csrf', state_url:'/formateur/indisponibilites/api/state', preview_url:'/formateur/indisponibilites/api/preview', commit_url:'/formateur/indisponibilites/api/commit', state:snapshot };
  const html = template.replace('{{ availability|tojson }}', JSON.stringify(config)).replace(/{%[\s\S]*?%}/g, '').replace(/{{[\s\S]*?}}/g, '');
  const dom = new JSDOM(html, { url:'https://school.example/formateur/indisponibilites', runScripts:'outside-only', pretendToBeVisual:true });
  const { window } = dom, document = window.document;
  const calls = [];
  let previewCount = 0, conflict = false;
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  window.fetch = async (url, options) => {
    calls.push({ url:String(url), options, body:options.body ? JSON.parse(options.body) : null });
    if (String(url).includes('/state')) return { ok:true, status:200, json:async()=>({...snapshot, ok:true}) };
    const body = JSON.parse(options.body);
    if (String(url).endsWith('/preview')) {
      previewCount++;
      const courses = body.action === 'unavailable' && body.dates.includes('2027-01-05') ? [
        { id:'one', date:'2027-01-05', start:'08:00', end:'10:00', title:'<img src=x onerror=alert(1)>', promotion_names:['MOS 1', 'MCO 1'], shared:true },
        { id:'two', date:'2027-01-05', start:'10:00', end:'12:00', title:'Culture générale', promotion_names:['MOS 1'], shared:false }
      ] : [];
      return { ok:true, status:200, json:async()=>({ ok:true, ...body, preview_token:'token-' + previewCount, courses, course_count:courses.length, requires_confirmation:!!courses.length }) };
    }
    if (conflict) return { ok:false, status:409, json:async()=>({ ok:false, message:'Le planning a changé.' }) };
    snapshot = { ...snapshot, days:[...baseDays(), { date:'2027-01-05', own_unavailable:true, unavailable:true, course_count:0 }] };
    return { ok:true, status:200, json:async()=>({ ok:true, message:'Enregistré', removed_count:2 }) };
  };
  window.eval(source);
  return { window, document, calls, setConflict:value=>{conflict=value;}, close:()=>window.close(), day:date=>document.querySelector('[data-ta-date="' + date + '"]'), button:id=>document.getElementById(id) };
}

(async () => {
  let page = makePage(), { document, day, button, calls } = page;
  check(document.querySelectorAll('.ta-month').length, 11, 'All eleven school months appear');
  check(document.querySelectorAll('[data-ta-date]').length, 334, 'Every school date is a real button');
  check(day('2027-01-01').disabled, true, 'Public holidays cannot be painted');
  check(day('2027-01-03').disabled, true, 'Past days cannot be newly blocked');
  check(day('2027-01-07').disabled, true, 'Full administrative blocks are protected');
  check(day('2027-01-09').disabled, false, 'Partial administrative blocks can be extended');
  check(day('2027-01-08').disabled, true, 'Existing own date is not added twice');
  check(day('2027-01-05').getAttribute('aria-label').includes('2 cours programmés'), true, 'Scheduled classes have accessible text');
  check(button('ta-save').disabled, true, 'Empty selection cannot submit');
  day('2027-01-05').click();
  check(day('2027-01-05').getAttribute('aria-pressed'), 'true', 'Click selects day');
  check(document.querySelector('[data-trainer-availability]').dataset.dirty, 'true', 'Unsaved selection is exposed');
  check(button('ta-next').disabled, true, 'Navigation cannot silently discard selection');
  check(document.querySelector('[data-ta-action="available"]').disabled, true, 'Action cannot change underneath a selection');
  check(calls.length, 0, 'Selection performs no server mutation');
  button('ta-save').click(); await settle();
  check(calls.length, 1, 'Save requests only a preview');
  check(calls[0].options.headers['X-CSRF-Token'], 'fixture-csrf', 'Mutations use the session CSRF token');
  check(calls[0].body, { dates:['2027-01-05'], action:'unavailable' }, 'Preview contains exact selected dates and action');
  check(button('ta-confirm-dialog').hasAttribute('open'), true, 'Destructive preview opens modal');
  check(document.querySelectorAll('.ta-conflict-course').length, 2, 'Every cancelled session is shown');
  check(button('ta-conflict-courses').querySelector('img'), null, 'Course text cannot inject HTML');
  check(button('ta-conflict-courses').textContent.includes('MOS 1 · MCO 1 · Cours commun'), true, 'Shared groups are explicitly disclosed');
  check(button('ta-confirm').textContent, 'Confirmer et supprimer 2 cours', 'Destructive button identifies deletion count');
  check(document.activeElement, button('ta-cancel-dialog'), 'Safe action gets initial keyboard focus');
  button('ta-cancel-dialog').click();
  check(calls.length, 1, 'Cancel never commits');
  check(day('2027-01-05').getAttribute('aria-pressed'), 'true', 'Cancel keeps selection');
  button('ta-save').click(); await settle(); button('ta-confirm').click(); await settle();
  const commit = calls.find(call => call.url.endsWith('/commit'));
  check(commit.body, {preview_token:'token-2', confirm_delete:true}, 'Explicit confirmation carries the fresh preview only');
  check(button('ta-confirm-dialog').hasAttribute('open'), false, 'Successful mutation closes dialog');
  check(document.querySelector('[data-trainer-availability]').dataset.dirty, 'false', 'Successful save clears dirty state');
  check(day('2027-01-05').classList.contains('is-own'), true, 'Calendar reload reflects saved dates');
  check(day('2027-01-05').classList.contains('has-course'), false, 'Deleted courses disappear from day markers');
  check(page.window.localStorage.getItem('academy-planning-updated') !== null, true, 'Other open tabs are notified');
  document.querySelector('[data-ta-action="available"]').click();
  check(day('2027-01-08').disabled, false, 'Own blocks become removable in available mode');
  check(day('2027-01-07').disabled, true, 'Admin-only blocks stay uneditable');
  check(day('2027-01-11').disabled, false, 'Own layer can be removed while admin layer remains');
  day('2027-01-08').click(); button('ta-save').click(); await settle();
  check(button('ta-confirm-description').textContent.includes('ne seront pas recréés'), true, 'Returning available does not promise restoration of deleted lessons');
  check(button('ta-delete-note').hidden, true, 'Non-destructive change has no deletion notice');
  page.close();

  page = makePage(); ({document, day, button, calls} = page);
  day('2027-01-05').click(); button('ta-save').click(); await settle();
  page.setConflict(true); button('ta-confirm').click(); await settle();
  check(button('ta-confirm-dialog').hasAttribute('open'), false, 'Stale preview is closed');
  check(day('2027-01-05').getAttribute('aria-pressed'), 'true', 'Still-applicable selected dates survive conflict refresh');
  check(button('ta-notice').textContent.includes('Rien n’a été supprimé'), true, 'Conflict clearly reports no destructive change');
  const countBefore = calls.length; button('ta-confirm').click(); await settle();
  check(calls.length, countBefore, 'Old confirmation cannot be replayed from closed dialog');
  button('ta-save').click(); await settle();
  check(calls.at(-1).url.endsWith('/preview'), true, 'After conflict a fresh preview is mandatory');
  button('ta-cancel-dialog').click(); button('ta-clear').click();
  check(button('ta-selection-count').textContent, 'Aucun jour sélectionné', 'Clear resets pending selection');
  check(button('ta-next').disabled, false, 'Clearing re-enables year navigation');
  day('2027-01-12').click();
  day('2027-01-15').dispatchEvent(new page.window.MouseEvent('click', {bubbles:true, shiftKey:true}));
  check(document.querySelectorAll('.ta-day.is-selected').length, 4, 'Shift click selects inclusive date range');
  button('ta-clear').click();
  day('2027-01-12').dispatchEvent(new page.window.MouseEvent('pointerdown', {bubbles:true, button:0}));
  day('2027-01-14').dispatchEvent(new page.window.MouseEvent('pointerover', {bubbles:true}));
  document.dispatchEvent(new page.window.MouseEvent('pointerup', {bubbles:true}));
  await settle();
  check(document.querySelectorAll('.ta-day.is-selected').length, 3, 'Mouse drag paints inclusive date range');
  const change = new page.window.CustomEvent('academy:planning-changed', {cancelable:true});
  check(page.window.dispatchEvent(change), false, 'Live update cannot reload over a local selection');
  check(document.querySelectorAll('.ta-day.is-selected').length, 3, 'Live update preserves local paint');
  page.close();

  page = makePage(); ({document, day, button} = page);
  let resolveFocusRefresh;
  page.window.fetch = () => new Promise(resolve => { resolveFocusRefresh = resolve; });
  page.window.dispatchEvent(new page.window.Event('focus'));
  day('2027-01-05').click();
  resolveFocusRefresh({ok:true, status:200, json:async()=>({ok:true, year:2027, today:'2027-01-04', days:[{date:'2027-01-05', own_unavailable:true, unavailable:true}]})});
  await settle();
  check(day('2027-01-05').getAttribute('aria-pressed'), 'true', 'Selection started after focus fetch remains selected');
  check(day('2027-01-05').classList.contains('is-own'), false, 'An in-flight quiet refresh cannot redraw newly dirty editor');
  check(day('2027-01-05').classList.contains('has-course'), true, 'In-flight refresh defers until trainer finishes local edits');
  button('ta-clear').click();
  page.window.dispatchEvent(new page.window.Event('focus'));
  day('2027-01-12').dispatchEvent(new page.window.MouseEvent('pointerdown', {bubbles:true, button:0}));
  resolveFocusRefresh({ok:true, status:200, json:async()=>({ok:true, year:2027, today:'2027-01-04', days:[{date:'2027-01-12', own_unavailable:true, unavailable:true}]})});
  await settle();
  check(day('2027-01-12').classList.contains('is-own'), false, 'A pointer gesture is protected before it creates its first selection');
  day('2027-01-14').dispatchEvent(new page.window.MouseEvent('pointerover', {bubbles:true}));
  document.dispatchEvent(new page.window.MouseEvent('pointerup', {bubbles:true}));
  check(document.querySelectorAll('.ta-day.is-selected').length, 3, 'Deferred refresh preserves the subsequent drag gesture');
  page.close();
  console.log('PASS: ' + checks + ' trainer availability DOM checks (selection, protected dates, explicit deletion, safe text, stale previews, reload and shared groups).');
})().catch(error => { console.error(error); process.exitCode = 1; });
