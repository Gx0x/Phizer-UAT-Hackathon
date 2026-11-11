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

function showFollowUp(result) {
  if (typeof result.follow_up !== 'string' || !result.follow_up.trim()) {
    return null;
  }

  const answerId = 'follow-up-answer';
  const status = el('p', {
    class: 'status',
    role: 'status',
    'aria-live': 'polite',
    'aria-atomic': 'true',
  });

  const textarea = el('textarea', {
    id: answerId,
    name: 'answer',
    rows: 4,
    placeholder: 'Add any details that might help...',
    'aria-describedby': 'follow-up-status',
  });

  status.id = 'follow-up-status';

  const send = el(
    'button',
    { class: 'button', type: 'submit' },
    'Send answer',
  );

  const skip = el(
    'button',
    { class: 'button button--quiet', type: 'button' },
    'Skip',
  );

  const actions = el(
    'div',
    { class: 'actions' },
    send,
    skip,
  );

  const form = el(
    'form',
    { class: 'form follow-up__form', novalidate: true },
    el('div', { class: 'field' },
      el('label', { for: answerId }, 'Your answer'),
      textarea,
    ),
    actions,
    status,
  );

  const section = el(
    'section',
    { class: 'follow-up', 'aria-labelledby': 'follow-up-heading' },
    el('h2', { id: 'follow-up-heading' }, 'One quick question'),
    el('p', { class: 'follow-up__question' }, result.follow_up),
    form,
  );

  let pending = false;
  let finished = false;

  function setStatus(message, isError = false) {
    status.textContent = message;
    status.className = isError
      ? 'status status--error'
      : 'status';
  }

  function finish(message) {
    finished = true;

    const confirmation = el('p', {
      class: 'follow-up__complete',
      role: 'status',
      'aria-live': 'polite',
      tabindex: '-1',
    }, message);

    form.replaceWith(confirmation);
    confirmation.focus();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (pending || finished) return;

    const answer = textarea.value.trim();

    if (!answer) {
      setStatus('Type an answer, or use Skip.', true);
      textarea.focus();
      return;
    }

    pending = true;
    send.disabled = true;
    skip.disabled = true;
    textarea.disabled = true;
    send.textContent = 'Sending...';
    setStatus('Sending your answer...');

    try {
      await api(
        `/api/reports/${encodeURIComponent(result.report_id)}/follow-up`,
        {
          method: 'POST',
          body: JSON.stringify({ answer }),
        },
      );

      finish('Thanks, that helps.');
    } catch (error) {
      setStatus(error.message || 'Could not send your answer. Try again.', true);

      pending = false;
      send.disabled = false;
      skip.disabled = false;
      textarea.disabled = false;
      send.textContent = 'Send answer';
      textarea.focus();
    }
  });

  skip.addEventListener('click', () => {
    if (pending || finished) return;
    finish('No problem, thanks for the report.');
  });

  return section;
}

function showConfirmation(result) {
  const followUp = showFollowUp(result);
  const duplicate = result.duplicate;
  const count = duplicate?.others_noticed;
  const duplicateNotice = duplicate?.outcome === 'likely' &&
    Number.isInteger(count) && count >= 1
    ? el('p', { class: 'duplicate-notice' },
        `This issue already has ${count} other ${count === 1 ? 'report' : 'reports'}. ` +
        "It's already on your manager's radar.",
      )
    : null;

  root.replaceChildren(
    el('section', {
      class: 'confirmation',
      tabindex: '-1',
      id: 'confirmation',
    },
      el('h1', {}, result.message),
      el('p', {},
        'Status: ',
        el('strong', {}, result.status),
        '. Your manager will take a look soon.',
      ),
      duplicateNotice,
      followUp,
      el('div', { class: 'actions' },
        el('a', {
          class: 'button',
          href: window.location.href,
        }, 'Add another report'),
        el('a', {
          class: 'button button--quiet',
          href: '/',
        }, 'Choose a different category'),
      ),
    ),
  );

  document.getElementById('confirmation').focus();
}

function renderForm(form) {
  const status = el('p', {
    class: 'status',
    role: 'status',
    'aria-live': 'polite',
  });

  const submit = el(
    'button',
    { class: 'button', type: 'submit' },
    'Send report',
  );

  const fields = form.fields.map((field) => {
    const id = `field-${field.key}`;

    const control = field.type === 'textarea'
      ? el('textarea', {
          id,
          name: field.key,
          placeholder: field.placeholder,
        })
      : el('input', {
          id,
          name: field.key,
          type: 'text',
          placeholder: field.placeholder,
          autocomplete: 'off',
        });

    return el('div', { class: 'field' },
      el('label', { for: id },
        field.label,
        field.optional
          ? el('span', { class: 'optional' }, ' (optional)')
          : null,
      ),
      control,
    );
  });

  const formEl = el(
    'form',
    { class: 'form', novalidate: true },
    ...fields,
    submit,
    status,
  );

  let submitting = false;

  function setStatus(text, isError = false) {
    status.textContent = text;
    status.className = isError
      ? 'status status--error'
      : 'status';
  }

  formEl.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (submitting) return;

    setStatus('');

    const answers = {};

    for (const field of form.fields) {
      answers[field.key] = formEl.elements[field.key].value;
    }

    // The only rule: not completely empty.
    // No minimum length anywhere.
    if (!Object.values(answers).some((value) => value.trim())) {
      setStatus(
        'Add at least one detail so we know what you spotted.',
        true,
      );

      formEl.elements[form.fields[0].key].focus();
      return;
    }

    submitting = true;
    submit.disabled = true;
    submit.textContent = 'Sending...';
    setStatus('Sending your report...');

    try {
      const profiles = await getProfiles();
      const tester = profiles.find(
        (profile) => profile.role === 'tester',
      );

      if (!tester) {
        throw new Error(
          'The demo tester profile is missing. Run the seed script first.',
        );
      }

      const result = await api('/api/reports', {
        method: 'POST',
        body: JSON.stringify({
          category,
          answers,
          tester_id: tester.id,
        }),
      });

      showConfirmation(result);
    } catch (error) {
      setStatus(error.message, true);
      submitting = false;
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
    showMessage(
      'Pick a category first so we can show the right questions.',
    );
    return;
  }

  renderForm(forms[category]);
}

main();
