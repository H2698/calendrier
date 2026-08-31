const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../../static/js/calendar.js'), 'utf8');

// Execute the actual page script with a small DOM/FullCalendar adapter.
// No network request or browser dependency is needed for these regressions.
function loadCalendar({ href = 'https://agency.test/calendar/', canManage = true } = {}) {
  const nodes = new Map();
  const calls = { opened: 0, closed: 0, reset: 0, refetched: 0, requests: [], history: [] };
  const root = { dataset: { canManage: String(canManage), autoSyncSeconds: '10' } };
  const node = (id) => {
    if (!nodes.has(id)) {
      nodes.set(id, {
        dataset: {}, value: '', disabled: false, textContent: '', listeners: {},
        addEventListener(type, listener) { this.listeners[type] = listener; },
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
  const documentListeners = {};
  const managementIds = new Set([
    'appointment-form', 'appointment-create-form', 'new-appointment',
    'edit-appointment', 'cancel-appointment', 'quick-client',
  ]);
  const document = {
    addEventListener(type, listener) { documentListeners[type] = listener; },
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
    fetch: async (url, options) => {
      calls.requests.push({ url, options });
      return { ok: true, json: async () => ({ data: { id: 'test-appointment' } }) };
    },
  });
  documentListeners.DOMContentLoaded();
  return { calls, node, form };
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
