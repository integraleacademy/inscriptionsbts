/* Independent check: a poll must not erase editing begun while its fetch is in flight. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('static/js/planning.js', 'utf8');
const start = source.indexOf('  async function loadState(');
const end = source.indexOf('  async function refreshChangedPlanning(', start);
assert.ok(start >= 0 && end > start);
const code = source.slice(start, end);

async function scenario(action) {
  let resolve, renders = 0;
  const pending = new Promise(done => { resolve = done; });
  const nodes = new Map();
  const state = {
    data: {old: true}, week: '2027-01-04', loadSeq: 0, slotCheckSeq: 0,
    availabilitySeq: 0, availability: new Map(), paintDraft: new Map(),
    view: 'week', quickShared: [], slotFormDirty: false, syncPending: false,
  };
  let dialogOpen = false;
  const sandbox = {
    state, promotionId: () => 'p1', URLSearchParams,
    $: id => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); },
    app: {setAttribute() {}}, request: () => pending,
    addDays: () => '2027-01-10', today: () => '2027-01-04',
    document: {activeElement: null, querySelector: () => dialogOpen ? {} : null},
    renderPromotion() { renders++; }, renderSharedRows() { renders++; },
    renderSubjects() { renders++; }, renderCalendar() { renders++; },
    renderRules() { renders++; }, renderSlotSelection() { renders++; state.slotFormDirty = false; },
    onQuickSharedChange() {}, notice() {}, renderYear: async () => {},
    loadAvailability: async () => {}, checkSelectedSlot: async () => {},
    setTimeout: () => 1, clearTimeout() {},
  };
  vm.createContext(sandbox);
  vm.runInContext(code + '\nthis.load = loadState;', sandbox);
  const work = sandbox.load({fromSync: true});
  if (action === 'typing') state.slotFormDirty = true;
  if (action === 'painting') state.paintDraft.set('2027-01-06', 'school');
  if (action === 'dialog') dialogOpen = true;
  resolve({promotion: {id: 'p1', nom: 'P1'}, subjects: [], courses: []});
  await work;
  assert.equal(renders, 0, action + ': background refresh must defer rather than redraw');
  assert.equal(state.data.old, true, action + ': keep the visible snapshot until editing is complete');
  if (action === 'typing') assert.equal(state.slotFormDirty, true);
}

(async () => {
  for (const action of ['typing', 'painting', 'dialog']) await scenario(action);
  console.log('Planning background-refresh race: typing, painting and modal drafts preserved.');
})().catch(error => { console.error(error); process.exitCode = 1; });
