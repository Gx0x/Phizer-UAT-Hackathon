import { api, getProfiles } from './api.js';
import { el } from './dom.js';
import { initHeader } from './header.js';

initHeader();

const root = document.getElementById('report-root');
const category = new URLSearchParams(window.location.search).get('category');

function showMessage(text) {
  root.replaceChildren(
    el('p', { text }),
    el('a', { class: 'button', href: '/' }, 'Choose a category'),
  );
}

function showConfirmation(result) {
  root.replaceChildren(
    el('section', { class: 'confirmation', tabindex: '-1', id: 'confirmation' },
      el('h1', {}, result.message),
      el('p', {}, 'Status: ', el('strong', {}, result.status), '. Your manager will take a look soon.'),
      el('div', { class: 'actions' },
        el('a', { class: 'button', href: window.location.href }, 'Add another report'),
        el('a', { class: 'button button--quiet', href: '/' }, 'Choose a different category'),
      ),
    ),
  );
  document.getElementById('confirmation').focus();
}

function renderForm(form) {
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const submit = el('button', { class: 'button', type: 'submit' }, 'Send report');

  const fields = form.fields.map((field) => {
    const id = `field-${field.key}`;
    const control = field.type === 'textarea'
      ? el('textarea', { id, name: field.key, placeholder: field.placeholder })
      : el('input', { id, name: field.key, type: 'text', placeholder: field.placeholder, autocomplete: 'off' });
    return el('div', { class: 'field' },
      el('label', { for: id },
        field.label,
        field.optional ? el('span', { class: 'optional' }, ' (optional)') : null,
      ),
      control,
    );
  });

  const formEl = el('form', { class: 'form', novalidate: true }, ...fields, submit, status);

  function setStatus(text, isError = false) {
    status.textContent = text;
    status.className = isError ? 'status status--error' : 'status';
  }

  formEl.addEventListener('submit', async (event) => {
    event.preventDefault();
    setStatus('');

    const answers = {};
    for (const field of form.fields) answers[field.key] = formEl.elements[field.key].value;

    // The only rule: not completely empty. No minimum length anywhere.
    if (!Object.values(answers).some((value) => value.trim())) {
      setStatus('Add at least one detail so we know what you spotted.', true);
      formEl.elements[form.fields[0].key].focus();
      return;
    }

    submit.disabled = true;
    submit.textContent = 'Sending...';

    try {
      const profiles = await getProfiles();
      const tester = profiles.find((profile) => profile.role === 'tester');
      if (!tester) {
        throw new Error('The demo tester profile is missing. Run the seed script first.');
      }
      const result = await api('/api/reports', {
        method: 'POST',
        body: JSON.stringify({ category, answers, tester_id: tester.id }),
      });
      showConfirmation(result);
    } catch (error) {
      setStatus(error.message, true);
      submit.disabled = false;
      submit.textContent = 'Send report';
    }
  });

  document.title = `${form.title} - UAT, Untangled`;
  root.replaceChildren(
    el('h1', {}, form.title),
    el('p', { class: 'lead' }, form.intro),
    formEl,
  );
}

async function main() {
  let forms;
  try {
    forms = await api('/api/forms');
  } catch (error) {
    showMessage(error.message);
    return;
  }

  if (!forms[category]) {
    showMessage('Pick a category first so we can show the right questions.');
    return;
  }
  renderForm(forms[category]);
}

main();
