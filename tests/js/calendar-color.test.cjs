const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../../static/js/calendar-color.js'), 'utf8');

function loadPicker({ automatic = true, count = 1 } = {}) {
  const node = (data = {}) => ({
    ...data, listeners: {},
    addEventListener(type, handler) { this.listeners[type] = handler; },
  });
  const pickers = Array.from({ length: count }, () => {
    const checkbox = automatic ? node({ checked: true }) : null;
    const input = node({
      value: '#16a34a', dataset: { suggestedColor: '#16A34A' },
      form: { querySelector: () => checkbox },
    });
    const output = node({ textContent: '' });
    return { input, output, checkbox, querySelector: (selector) => selector === 'input' ? input : output };
  });
  const document = node({ querySelectorAll: () => pickers });
  vm.runInNewContext(source, { document });
  document.listeners.DOMContentLoaded();
  return pickers;
}

test('initial preview shows the code without disabling automatic assignment', () => {
  const [{ output, checkbox }] = loadPicker();
  assert.equal(output.textContent, '#16A34A');
  assert.equal(checkbox.checked, true);
});

test('choosing a color updates the code and switches to manual mode', () => {
  const [{ input, output, checkbox }] = loadPicker();
  input.value = '#aabbcc';
  input.listeners.input();
  assert.equal(output.textContent, '#AABBCC');
  assert.equal(checkbox.checked, false);
  input.value = '#123456';
  input.listeners.change();
  assert.equal(output.textContent, '#123456');
});

test('reenabling automatic mode restores the suggested preview', () => {
  const [{ input, output, checkbox }] = loadPicker();
  input.value = '#aabbcc';
  input.listeners.input();
  checkbox.checked = true;
  checkbox.listeners.change();
  assert.equal(input.value, '#16a34a');
  assert.equal(output.textContent, '#16A34A');
});

test('existing profile picker works without an automatic checkbox', () => {
  const [{ input, output }] = loadPicker({ automatic: false });
  input.value = '#aabbcc';
  input.listeners.input();
  assert.equal(output.textContent, '#AABBCC');
});

test('pickers are scoped to their own form and empty pages are harmless', () => {
  const [first, second] = loadPicker({ count: 2 });
  first.input.value = '#aabbcc';
  first.input.listeners.input();
  assert.equal(second.checkbox.checked, true);
  assert.equal(second.output.textContent, '#16A34A');
  assert.deepEqual(loadPicker({ count: 0 }), []);
});
