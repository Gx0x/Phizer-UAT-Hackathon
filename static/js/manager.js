import { api } from './api.js';
import { el } from './dom.js';
import { getRole, initHeader, setRole } from './header.js';

initHeader();

const root = document.getElementById('manager-root');

function showGate() {
  root.replaceChildren(
    el('section', { class: 'notice' },
      el('h1', {}, "This is the manager's view"),
      el('p', {}, 'The review queue is for the UAT manager. Switch role to see it.'),
      el('button', {
        class: 'button',
        type: 'button',
        onclick: () => { setRole('manager'); window.location.reload(); },
      }, 'Switch to Manager'),
    ),
  );
}

function formatDate(value) {
  return new Date(value).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

function answersList(issue, forms) {
  const labels = {};
  for (const field of forms[issue.category]?.fields ?? []) labels[field.key] = field.label;

  const reports = issue.reports ?? [];
  if (!reports.length) return el('p', { class: 'issue__meta' }, 'No report details found.');

  return el('div', {},
    reports.map((report, index) =>
      el('div', {},
        index > 0 ? el('hr', { class: 'report-divider' }) : null,
        el('p', { class: 'issue__meta' }, `Sent ${formatDate(report.created_at)}`),
        el('dl', { class: 'answers' },
          Object.entries(report.answers ?? {}).flatMap(([key, value]) => [
            el('dt', {}, labels[key] ?? key),
            el('dd', {}, value),
          ]),
        ),
      ),
    ),
  );
}

function issueCard(issue, forms) {
  const category = issue.category;
  return el('li', { class: `issue issue--${category}` },
    el('div', { class: 'issue__top' },
      el('span', { class: `chip chip--${category}` }, forms[category]?.label ?? category),
      el('span', { class: 'chip chip--status' }, issue.status),
      el('h2', { class: 'issue__title' }, issue.title),
    ),
    el('p', { class: 'issue__meta' },
      `Noticed by ${plural(issue.report_count, 'tester')}. First reported ${formatDate(issue.created_at)}.`),
    el('details', {},
      el('summary', {}, 'See what was reported'),
      answersList(issue, forms),
    ),
  );
}

async function load() {
  root.replaceChildren(el('p', { role: 'status' }, 'Loading the review queue...'));

  let issues;
  let forms;
  try {
    [issues, forms] = await Promise.all([api('/api/issues'), api('/api/forms')]);
  } catch (error) {
    root.replaceChildren(
      el('p', { class: 'status status--error', role: 'alert' }, error.message),
      el('button', { class: 'button', type: 'button', onclick: load }, 'Try again'),
    );
    return;
  }

  const heading = el('div', { class: 'toolbar' },
    el('div', {},
      el('h1', {}, 'Review queue'),
      el('p', { class: 'issue__meta' }, plural(issues.length, 'issue') + ', most-noticed first'),
    ),
    el('button', { class: 'button button--quiet', type: 'button', onclick: load }, 'Refresh'),
  );

  if (!issues.length) {
    root.replaceChildren(
      heading,
      el('p', {}, 'Nothing to review yet. Reports from testers will appear here.'),
      el('a', { class: 'button', href: '/' }, 'Add a test report'),
    );
    return;
  }

  root.replaceChildren(
    heading,
    el('ul', { class: 'queue' }, issues.map((issue) => issueCard(issue, forms))),
  );
}

if (getRole() === 'manager') load();
else showGate();
