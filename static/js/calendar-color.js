document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-calendar-color]').forEach((control) => {
    const input = control.querySelector('input');
    const output = control.querySelector('output');
    if (!input || !output) return;
    const automatic = input.form?.querySelector('[name="automatic_color"]');
    const syncCode = () => { output.textContent = input.value.toUpperCase(); };
    const chooseManually = () => {
      if (automatic) automatic.checked = false;
      syncCode();
    };
    input.addEventListener('input', chooseManually);
    input.addEventListener('change', chooseManually);
    automatic?.addEventListener('change', () => {
      if (automatic.checked && input.dataset.suggestedColor) {
        input.value = input.dataset.suggestedColor.toLowerCase();
        syncCode();
      }
    });
    syncCode();
  });
});
