const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../../static/js/calendar.js'), 'utf8');

// Execute the actual page script with a small DOM/FullCalendar adapter.
// No network request or browser dependency is needed for these regressions.
function loadCalendar({ href = 'https://agency.test/calendar/', canManage = true, confirmResult = true, fetchOk = true } = {}) {
  const nodes = new Map();
  const calls = { opened: 0, detailsOpened: 0, closed: 0, reset: 0, refetched: 0, requests: [], history: [], confirms: [], alerts: [] };
  const root = { dataset: { canManage: String(canManage), autoSyncSeconds: '10' } };
  const node = (id) => {
    if (!nodes.has(id)) {
      nodes.set(id, {
        dataset: {}, value: '', disabled: false, textContent: '', listeners: {},
        addEventListener(type, listener) { this.listeners[type] = listener; },
        append() {}, replaceChildren() {},
      });
    }
    return nodes.get(id);
  };
  const form = node('appointment-create-form');
  form.reset = () => { calls.reset += 1; };
  form.entries = [
    ['title', 'Dashboard appointment'], ['start_at', '2026-09-01T10:00'],
    ['end_at', '2026-09-01T11:00'], ['member_ids', '2'], ['member_ids', '3'],
    ['csrfmiddlewaretoken', 'test-token'], ['recurrence_frequency', ''],
    ['recurrence_end_date', ''],
  ];
  const dialog = node('appointment-form');
  dialog.showModal = () => { calls.opened += 1; };
  dialog.close = () => { calls.closed += 1; };
  const details = node('event-details');
  details.showModal = () => { calls.detailsOpened += 1; };
  details.close = () => { calls.closed += 1; };
  const documentListeners = {};
  let createdNodes = 0;
  const managementIds = new Set([
    'appointment-form', 'appointment-create-form', 'new-appointment',
    'edit-appointment', 'cancel-appointment', 'delete-appointment', 'quick-client',
  ]);
  const document = {
    addEventListener(type, listener) { documentListeners[type] = listener; },
    createElement(tag) { return node(`created-${tag}-${createdNodes++}`); },
    querySelector(selector) {
      if (selector === '.calendar-card') return root;
      if (selector === '[name=csrfmiddlewaretoken]') return { value: 'test-token' };
      return null;
    },
    getElementById(id) { return !canManage && managementIds.has(id) ? null : node(id); },
    querySelectorAll() { return []; },
  };
  const FullCalendar = {
    Calendar: class {
      constructor(element, options) { calls.options = options; }
      render() {}
      refetchEvents() { calls.refetched += 1; }
    },
  };
  const window = {
    FullCalendar, innerWidth: 1280, location: { href }, setInterval() {},
    history: {
      state: { previous: true },
      replaceState(state, title, url) { calls.history.push({ state, title, url }); },
    },
  };
  class FormData {
    constructor(element) { this.entries = element.entries; }
    [Symbol.iterator]() { return this.entries[Symbol.iterator](); }
    getAll(name) { return this.entries.filter(([key]) => key === name).map(([, value]) => value); }
  }
  vm.runInNewContext(source, {
    document, window, FullCalendar, URL, FormData,
    confirm: (message) => { calls.confirms.push(message); return confirmResult; },
    alert: (message) => { calls.alerts.push(message); },
    fetch: async (url, options) => {
      calls.requests.push({ url, options });
      return { ok: fetchOk, status: fetchOk ? 200 : 500, json: async () => ({ data: { id: 'test-appointment' } }) };
    },
  });
  documentListeners.DOMContentLoaded();
  const selectAppointment = () => calls.options.eventClick({ event: {
    id: 'appointment-id', title: 'Planification',
    start: new Date('2026-09-01T08:00:00Z'), end: new Date('2026-09-01T08:30:00Z'),
    extendedProps: {
      id: 'appointment-id', status: 'cancelled', members: [], description: '', notes: '',
      client: null, appointment_type: { id: 'type-id', name: 'Réunion interne' },
    },
  } });
  return { calls, node, form, selectAppointment };
}

test('dashboard shortcut opens a fresh form once without creating an appointment', () => {
  const { calls, node, form } = loadCalendar({ href: 'https://agency.test/calendar/?new=1&keep=value#week' });
  assert.equal(calls.opened, 1);
  assert.equal(calls.reset, 1);
  assert.equal(form.dataset.appointmentId, undefined);
  assert.equal(node('appointment-submit').textContent, 'Créer');
  assert.equal(calls.requests.length, 0);
  assert.equal(calls.history[0].url, '/calendar/?keep=value#week');
  assert.deepEqual(calls.history[0].state, { previous: true });
});

test('a normal calendar visit does not open the form; its existing button still works', () => {
  const { calls, node } = loadCalendar();
  assert.equal(calls.opened, 0);
  node('new-appointment').listeners.click();
  assert.equal(calls.opened, 1);
  assert.equal(calls.history.length, 0);
});

test('a member cannot open the form by manually adding the shortcut parameter', () => {
  const { calls } = loadCalendar({ href: 'https://agency.test/calendar/?new=1', canManage: false });
  assert.equal(calls.opened, 0);
  assert.equal(calls.reset, 0);
  assert.equal(calls.requests.length, 0);
});

test('unrecognized shortcut values do not open the form', () => {
  assert.equal(loadCalendar({ href: 'https://agency.test/calendar/?new=0' }).calls.opened, 0);
});

test('submitting the opened form uses the existing creation API and refreshes the calendar', async () => {
  const { calls, form } = loadCalendar({ href: 'https://agency.test/calendar/?new=1' });
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(calls.requests.length, 1);
  const { url, options } = calls.requests[0];
  assert.equal(url, '/api/appointments/');
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-CSRFToken'], 'test-token');
  const payload = JSON.parse(options.body);
  assert.equal(payload.title, 'Dashboard appointment');
  assert.deepEqual(payload.member_ids, [2, 3]);
  assert.equal(payload.csrfmiddlewaretoken, undefined);
  assert.equal(calls.closed, 1);
  assert.equal(calls.refetched, 1);
});

test('manager deletion requires confirmation then posts and refreshes', async () => {
  const { calls, node, selectAppointment } = loadCalendar();
  selectAppointment();
  assert.equal(calls.detailsOpened, 1);
  await node('delete-appointment').listeners.click();
  assert.match(calls.confirms[0], /Planification/);
  assert.match(calls.confirms[0], /uniquement ce rendez-vous/);
  assert.equal(calls.requests.at(-1).url, '/api/appointments/appointment-id/delete/');
  assert.equal(calls.requests.at(-1).options.method, 'POST');
  assert.equal(calls.requests.at(-1).options.headers['X-CSRFToken'], 'test-token');
  assert.equal(calls.closed, 1);
  assert.equal(calls.refetched, 1);
});

test('rejecting deletion confirmation makes no request', async () => {
  const { calls, node, selectAppointment } = loadCalendar({ confirmResult: false });
  selectAppointment();
  await node('delete-appointment').listeners.click();
  assert.equal(calls.requests.length, 0);
  assert.equal(calls.closed, 0);
  assert.equal(calls.refetched, 0);
});

test('failed deletion keeps details open and displays a clear error', async () => {
  const { calls, node, selectAppointment } = loadCalendar({ fetchOk: false });
  selectAppointment();
  await node('delete-appointment').listeners.click();
  assert.deepEqual(calls.alerts, ['Suppression impossible.']);
  assert.equal(calls.closed, 0);
  assert.equal(calls.refetched, 0);
});

test('ordinary member has no deletion control', () => {
  const { node } = loadCalendar({ canManage: false });
  assert.equal(node('delete-appointment').listeners.click, undefined);
});
