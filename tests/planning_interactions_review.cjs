/* Independent interaction checks. Runs without browser or network access. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('static/js/planning.js', 'utf8');
const catalog = fs.readFileSync('static/js/planning-catalog.js', 'utf8');
function part(from, to, text = source) {
  const start = text.indexOf(from), end = text.indexOf(to, start + from.length);
  assert.ok(start >= 0 && end > start, `Source boundary missing: ${from} -> ${to}`);
  return text.slice(start, end);
}
function context(sourceCode, values = {}) {
  const ctx = vm.createContext({...values, URLSearchParams});
  vm.runInContext(sourceCode, ctx);
  return ctx;
}
const numeric = part('  const minutes =', '  const normal =');
const holidayHelpers = part('  const isPublicHoliday =', '  function courseName(');
const holiday = context(holidayHelpers + '\nglobalThis.checkHoliday = isPublicHoliday;', {state: {}}).checkHoliday;
const budgets = part('  function subjectBudget(', '  const catalogSubjects =');
const wire = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const subject = (overrides = {}) => ({id: 's1', promotion_id: 'p1', trainer_id: 't1', name: 'Culture', planned_hours: 2, planned_minutes: 120, scheduled_minutes: 45, remaining_minutes: 75, budget_configured: true, ...overrides});

async function run() {
  let checks = 0;
  const b = context(numeric + budgets + '\nglobalThis.label = minuteLabel;');
  assert.equal(b.label(75), '1 h 15');
  assert.equal(b.label(90), '1 h 30');
  assert.equal(b.subjectBudget(subject()).remaining, 75);
  assert.equal(b.budgetProblem(subject(), 75), '');
  assert.match(b.budgetProblem(subject(), 76), /1 h 15/);
  assert.match(b.budgetProblem(subject({budget_configured: false, planned_minutes: null, planned_hours: null}), 1), /renseigner/);
  assert.match(b.budgetProblem(subject({remaining_minutes: 0}), 1), /entièrement/);
  checks += 7;

  // Backend integer minutes prevail over rounded legacy hour fields.
  const catalogMath = context(part('  const number =', '  const promotionOf =', catalog) + '\nglobalThis.api = {minuteValue, duration, budget};');
  assert.equal(catalogMath.api.minuteValue({planned_minutes: 75, planned_hours: 1.3}, 'planned'), 75);
  assert.equal(catalogMath.api.duration(75), '1 h 15 min');
  assert.equal(catalogMath.api.duration(null), 'À définir');
  assert.equal(catalogMath.api.duration(0), '0 h');
  assert.equal(catalogMath.api.budget({planned_minutes: null, planned_hours: null, budget_configured: false}), false);
  checks += 5;

  const catalogItems = [subject(), subject({id: 's2', promotion_id: 'p2'})];
  const shared = context(part('  function cleanShared(', '  function renderSharedRows('), {catalogSubjects: () => catalogItems});
  assert.deepEqual(wire(shared.cleanShared([{promotion_id: 'p2', subject_id: 's2'}], 'p1')), [{promotion_id: 'p2', subject_id: 's2'}]);
  assert.throws(() => shared.cleanShared([{promotion_id: 'p1', subject_id: 's1'}], 'p1'), /fois/);
  assert.throws(() => shared.cleanShared([{promotion_id: 'p2', subject_id: 's1'}], 'p1'), /correspond/);
  assert.throws(() => shared.cleanShared([{promotion_id: 'p2', subject_id: ''}], 'p1'), /Choisissez/);
  checks += 4;

  // Editing from a secondary promotion must retain the original course owner.
  const courseState = {courseEdit: {promotion_id: 'p1'}, courseShared: [{promotion_id: 'p2', subject_id: 's2'}]};
  const cv = context(part('  const courseValues =', "  $('planning-course-form').addEventListener('submit'") + '\nglobalThis.values = courseValues;', {state: courseState, promotionId: () => 'p2', cleanShared: shared.cleanShared});
  const form = {elements: {subject_id: {value: 's1'}, trainer_id: {value: 't1'}, room_id: {value: ''}, date: {value: '2027-02-01'}, start: {value: '23:00'}, end: {value: '23:59'}, end_at_midnight: {checked: true}, title: {value: ' Cours partagé '}}};
  const values = cv.values(form);
  assert.equal(values.promotion_id, 'p1'); assert.equal(values.room_id, null); assert.equal(values.end, '24:00');
  assert.deepEqual(wire(values.shared), [{promotion_id: 'p2', subject_id: 's2'}]);
  checks += 4;

  const dates = part('  const parseDate =', '  const monday =');
  const days = ['2027-02-01', '2027-02-02', '2027-02-03'].map(date => ({date, kind: 'school'}));
  const paintState = {year: {days, calendar_revision: 'revision-a'}, data: {}, paintKind: 'company', paintDraft: new Map(), paintRevision: null};
  let renders = 0;
  const paint = context(dates + part('  function annualDay(', '  function renderPaintDraft(') + part('  function cancelPaint(', '  function annualClick('), {state: paintState, isPublicHoliday: holiday, kinds: {company: 'En entreprise', school: 'À l’école'}, renderPaintDraft: () => renders++});
  paint.applyPaintRange('2027-02-03', '2027-02-01');
  assert.equal(paintState.paintDraft.size, 3); assert.equal(paintState.paintRevision, 'revision-a');
  paintState.paintKind = 'school'; paint.applyPaintRange('2027-02-02', '2027-02-02');
  assert.equal(paintState.paintDraft.size, 2);
  paint.cancelPaint(); assert.equal(paintState.paintDraft.size, 0); assert.equal(paintState.paintRevision, null); assert.ok(renders >= 3);
  checks += 6;

  // Explicit save is the only write; a duplicate click cannot duplicate a batch.
  const paintNodes = new Map(); const node = id => { if (!paintNodes.has(id)) paintNodes.set(id, {textContent: '', disabled: false}); return paintNodes.get(id); };
  let pending = deferred(), calls = [], refreshes = 0;
  const saveState = {paintDraft: new Map([['2027-02-03', {date: '2027-02-03', kind: 'company'}], ['2027-02-01', {date: '2027-02-01', kind: 'company'}]]), paintRevision: 'revision-a'};
  const save = context(part('  async function savePaint(', '  async function refreshPaint('), {state: saveState, promotionId: () => 'p1', $: node, renderPaintDraft: () => {}, request: (url, options) => { calls.push({url, options}); return pending.promise; }, notice: () => {}, loadState: async () => refreshes++});
  const firstSave = save.savePaint(); await save.savePaint(); assert.equal(calls.length, 1); assert.equal(calls[0].url, '/calendar/bulk');
  assert.equal(calls[0].options.data.expected_revision, 'revision-a');
  assert.deepEqual(wire(calls[0].options.data.days.map(day => day.date)), ['2027-02-01', '2027-02-03']);
  pending.resolve({ok: true}); await firstSave; assert.equal(saveState.paintDraft.size, 0); assert.equal(refreshes, 1); assert.equal(saveState.paintBusy, false);
  saveState.paintDraft.set('2027-02-01', {date: '2027-02-01', kind: 'company'}); saveState.paintRevision = 'old'; pending = deferred();
  const staleSave = save.savePaint(); const conflict = new Error('Calendrier modifié.'); conflict.result = {conflicts: [{type: 'calendar_stale'}]}; pending.reject(conflict); await staleSave;
  assert.equal(saveState.paintDraft.size, 1); assert.equal(saveState.paintStale, true); await save.savePaint(); assert.equal(calls.length, 2); assert.equal(refreshes, 1);
  saveState.paintStale = false; pending = deferred(); const failedSave = save.savePaint(); pending.reject(new Error('Indisponible')); await failedSave; assert.equal(saveState.paintDraft.size, 1); assert.match(node('planning-paint-status').textContent, /Aucun jour/);
  checks += 13;

  // A selected available slot creates one course, even with rapid repeated clicks.
  let coursePending = deferred(), created = [];
  const selectedSlot = {promotion_id: 'p1', date: '2027-02-01', start: '09:00', end: '10:15'};
  const slotState = {data: {subjects: [subject()]}, slot: selectedSlot, slotChecks: new Map([['s1', {status: 'available'}]]), quickShared: [{promotion_id: 'p2', subject_id: 's2'}]};
  const quick = context(numeric + budgets + part('  async function createInSelectedSlot(', '  function availabilityOptions('), {state: slotState, promotionId: () => 'p1', $: id => id === 'planning-room' ? {value: ''} : node(id), renderSubjects: () => {}, renderSlotSelection: () => {}, formatDate: x => x, cleanShared: shared.cleanShared, notice: () => {}, clearSlot: () => { slotState.slot = null; }, loadState: async () => {}, request: (url, options) => { created.push({url, options}); return coursePending.promise; }});
  const create = quick.createInSelectedSlot('s1'); await quick.createInSelectedSlot('s1'); assert.equal(created.length, 1); assert.equal(created[0].options.data.room_id, null); assert.equal(created[0].options.data.end, '10:15'); assert.equal(created[0].options.data.shared[0].promotion_id, 'p2');
  coursePending.reject(new Error('Le formateur est indisponible.')); await create; assert.equal(slotState.slot, selectedSlot); assert.equal(slotState.slotChecks.get('s1').status, 'blocked'); assert.equal(slotState.quickBusy, false);
  slotState.slotChecks.set('s1', {status: 'available'}); coursePending = deferred(); const retry = quick.createInSelectedSlot('s1'); coursePending.resolve({ok: true}); await retry; assert.equal(slotState.slot, null);
  checks += 8;

  // Results from a previous slot must never paint a newer slot as available.
  let availabilityPending = deferred();
  const checkState = {data: {subjects: [subject()]}, slot: selectedSlot, slotCheckSeq: 0, loadSeq: 1, slotChecks: new Map(), quickShared: []};
  const checker = context(numeric + budgets + part('  async function checkSelectedSlot(', '  async function createInSelectedSlot('), {state: checkState, promotionId: () => 'p1', $: () => ({value: ''}), cleanShared: () => [], renderSubjects: () => {}, request: () => availabilityPending.promise});
  const oldCheck = checker.checkSelectedSlot(); checkState.slot = {...selectedSlot, start: '11:00', end: '12:15'}; checkState.slotCheckSeq++; availabilityPending.resolve({slots: [{date: selectedSlot.date, start: selectedSlot.start, available: true}]}); await oldCheck; assert.equal(checkState.slotChecks.size, 0);
  availabilityPending = deferred(); const currentCheck = checker.checkSelectedSlot(); availabilityPending.resolve({slots: [{date: selectedSlot.date, start: '11:00', available: true}]}); await currentCheck; assert.equal(checkState.slotChecks.get('s1').status, 'available');
  checks += 2;

  // A shared repeat consumes each subject's allowance once, even if a group repeats.
  const batchItems = ['0', '1'].map(key => ({key, course: {start: '09:00', end: '10:00', subject_id: 's1', groups: [{subject_id: 's1'}, {subject_id: 's2'}, {subject_id: 's2'}]}}));
  batchItems[1].conflicts = [{type: 'subject_budget', subject_id: 's2', planned_minutes: 90, scheduled_minutes: 0, pending_minutes: 60}];
  const batch = context(numeric + budgets + part('  function batchBudgetStatus(', '  function updateBatchCommit('), {catalogSubjects: () => [subject({remaining_minutes: 120}), subject({id: 's2', remaining_minutes: 90})], courseDuration: course => Number(course.end.slice(0, 2)) * 60 + Number(course.end.slice(3)) - Number(course.start.slice(0, 2)) * 60 - Number(course.start.slice(3))});
  const preview = {items: batchItems};
  let status = batch.batchBudgetStatus(preview, new Set(['0'])); assert.equal(status.withinBudget, true); assert.equal(status.canAdd(batchItems[1]), false);
  status = batch.batchBudgetStatus(preview, new Set()); assert.equal(status.canAdd(batchItems[1]), true);
  status = batch.batchBudgetStatus(preview, new Set(['1'])); assert.equal(status.withinBudget, true);
  status = batch.batchBudgetStatus(preview, new Set(['0', '1'])); assert.equal(status.withinBudget, false);
  checks += 5;

  // Dirty annual navigation waits for the explicit discard action; busy saves block it.
  const navNodes = new Map(); const navNode = id => { if (!navNodes.has(id)) navNodes.set(id, {textContent: '', close() { this.closed = true; }}); return navNodes.get(id); };
  let actions = 0, dialogOpens = 0; const navState = {paintDraft: new Map([['d', {}]])};
  const nav = context(part('  function navigatePlanning(', '  function selectView('), {state: navState, $: navNode, openDialog: () => dialogOpens++, notice: () => {}, cancelPaint: () => navState.paintDraft.clear()});
  nav.navigatePlanning(() => actions++); assert.equal(actions, 0); assert.equal(dialogOpens, 1);
  navNode('planning-confirm-action').onclick(); assert.equal(actions, 1); assert.equal(navState.paintDraft.size, 0);
  navState.quickBusy = true; nav.navigatePlanning(() => actions++); assert.equal(actions, 1);
  navState.quickBusy = false; nav.navigatePlanning(() => actions++); assert.equal(actions, 2);
  checks += 6;
  // Locked holidays are never painted, including within a multi-day range.
  paintState.year = {days: [{date: '2027-05-05', kind: 'school'}, {date: '2027-05-06', kind: 'public_holiday', public_holiday: true, locked: true, label: 'Ascension'}, {date: '2027-05-07', kind: 'school'}], calendar_revision: 4};
  paintState.paintKind = 'company'; paint.applyPaintRange('2027-05-05', '2027-05-07');
  assert.equal(paintState.paintDraft.size, 2); assert.equal(paintState.paintDraft.has('2027-05-06'), false); assert.equal(paintState.paintSkipped, 1);
  paint.paintDate('2027-05-06', 'school'); assert.equal(paintState.paintDraft.has('2027-05-06'), false);
  paint.cancelPaint(); assert.equal(paintState.paintSkipped, 0); checks += 5;

  const warningHelper = context(holidayHelpers, {state: {}});
  assert.deepEqual(wire(warningHelper.courseWarnings({room_id: null, warnings: []})), ['Salle à affecter.']);
  assert.deepEqual(wire(warningHelper.courseWarnings({room_id: 'r1', warnings: [], warning_labels: []})), []);
  assert.equal(warningHelper.courseWarnings({room_id: null, warning_labels: ['Salle à affecter.'], warnings: [{code: 'room_missing', message: 'Salle à affecter.'}]}).length, 1);
  assert.ok(warningHelper.courseWarnings({room_id: 'r1', warnings: [{code: 'trainer_missing', message: 'Formateur à affecter.'}]}).includes('Formateur à affecter.')); checks += 4;

  // A manual time selection cannot turn a holiday into an available slot.
  const lockedSlotState = {data: {}, slot: null}; let slotNotices = [];
  const lockedSlot = context(numeric + part('  function setSlot(', '  function clearSlot('), {state: lockedSlotState, knownDay: () => ({kind: 'public_holiday', label: 'Ascension'}), isPublicHoliday: holiday, notice: text => slotNotices.push(text), promotionId: () => 'p1'});
  lockedSlot.setSlot('2027-05-06', '08:00', '12:00'); assert.equal(lockedSlotState.slot, null); assert.match(slotNotices[0], /Ascension/); checks += 2;

  // Explicit duplication keeps the primary course ID/version even when opened from a secondary promotion.
  const copyCourse = {id: 'course1', version: 7, promotion_id: 'p1', subject_id: 's1', date: '2027-05-05', start: '08:00', end: '12:00', trainer_id: 't1', room_id: null, shared: [{promotion_id: 'p2', subject_id: 's2'}]};
  const copyState = {week: '2027-05-03', batch: {mode: 'dates', course: copyCourse, dates: new Set(['2027-05-10', '2027-05-07']), calendar: {days: [{date: '2027-05-05', kind: 'school'}, {date: '2027-05-06', kind: 'public_holiday', label: 'Ascension'}, {date: '2027-05-07', kind: 'school'}, {date: '2027-05-08', kind: 'company'}]}}};
  const copyPayload = context(part('  function batchPreviewPayload(', "  $('planning-batch-form').addEventListener('submit'"), {state: copyState, promotionId: () => 'p2', selectedWeekdays: () => [0], addDays: value => value});
  const payload = copyPayload.batchPreviewPayload({}); assert.equal(payload.promotion_id, 'p1'); assert.equal(payload.source_course_id, 'course1'); assert.equal(payload.source_version, 7); assert.equal(payload.mode, 'dates'); assert.deepEqual(wire(payload.dates), ['2027-05-07', '2027-05-10']);
  copyState.batch.calendarLoading = true; assert.throws(() => copyPayload.batchPreviewPayload({}), /Choisissez/); copyState.batch.calendarLoading = false;
  copyState.batch.dates.clear(); assert.throws(() => copyPayload.batchPreviewPayload({}), /Choisissez/); checks += 7;

  let invalidated = 0, dateRenders = 0; const copyNodes = {dataset: {}};
  const copyDates = context(part('  function batchDateProblem(', '  function updateBatchDates(') + part('  function setBatchDate(', '  function batchDateKey('), {state: copyState, isPublicHoliday: holiday, kinds: {company: 'En entreprise'}, $: () => copyNodes, invalidateBatch: () => invalidated++, updateBatchDates: () => dateRenders++});
  assert.match(copyDates.batchDateProblem('2027-05-06'), /Ascension/); assert.match(copyDates.batchDateProblem('2027-05-05'), /existe déjà/); assert.match(copyDates.batchDateProblem('2027-05-08'), /Aucun cours/); assert.equal(copyDates.batchDateProblem('2027-05-07'), '');
  copyDates.batchDateClick('2027-05-06'); assert.equal(copyState.batch.dates.size, 0);
  copyDates.batchDateClick('2027-05-07'); assert.equal(copyState.batch.dates.has('2027-05-07'), true); assert.equal(invalidated, 1);
  copyDates.batchDateClick('2027-05-07'); assert.equal(copyState.batch.dates.size, 0);
  copyDates.beginBatchDate('2027-05-07', {button: 0, preventDefault() {}, currentTarget: {focus() {}}}); copyDates.batchDateClick('2027-05-07'); assert.equal(copyState.batch.dates.size, 1); copyDates.extendBatchDate('2027-05-06'); assert.equal(copyState.batch.dates.size, 1);
  copyNodes.dataset.busy = '1'; copyDates.setBatchDate('2027-05-07', false); assert.equal(copyState.batch.dates.size, 1); assert.ok(dateRenders >= 3); checks += 12;

  console.log(`PASS: ${checks} independent planning/catalog checks (exact minutes, shared ownership, paint draft/save/cancel/conflict, single creation, stale slot response).`);
}
run().catch(error => { console.error(error); process.exitCode = 1; });
