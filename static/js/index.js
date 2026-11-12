import { api, getProfiles } from './api.js';
import { el } from './dom.js';
import { getRole, initHeader } from './header.js';

initHeader();

const requestsRoot = document.getElementById('tester-detail-requests');
const progressRoot = document.getElementById('tester-report-progress');

function requestCard(request, testerId, forms, onSaved) {
  const report = request.reports ?? {};
  const form = forms[report.category];
  const labels = Object.fromEntries((form?.fields ?? []).map((field) => [field.key, field.label]));
  const answerId = `detail-answer-${request.id}`;
  const answer = el('textarea', { id: answerId, name: 'answer', rows: 4 });
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const send = el('button', { class: 'button', type: 'submit' }, 'Send additional detail');
  const replyForm = el('form', { class: 'tester-detail-form', novalidate: true },
    el('label', { for: answerId }, 'Your answer'),
    answer,
    send,
    status,
  );
  let pending = false;

  replyForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (pending) return;
    const text = answer.value.trim();
    if (!text) {
      status.textContent = 'Add some detail before sending your answer.';
      status.className = 'status status--error';
      answer.focus();
      return;
    }
    pending = true;
    send.disabled = true;
    answer.disabled = true;
    status.className = 'status';
    status.textContent = 'Saving your answer and refreshing the report...';
    try {
      await api(`/api/detail-requests/${encodeURIComponent(request.id)}/answer`, {
        method: 'POST', body: JSON.stringify({ answer: text, tester_id: testerId }),
      });
      await onSaved('Thanks. Your answer has been returned to the manager.');
    } catch (error) {
      status.textContent = error.message || 'Could not save your answer. Please try again.';
      status.className = 'status status--error';
      pending = false;
      send.disabled = false;
      answer.disabled = false;
    }
  });

  return el('li', { class: 'tester-detail-card' },
    el('h3', {}, `Your ${form?.label ?? report.category ?? ''} report`),
    el('details', {},
      el('summary', {}, 'Read your original report'),
      el('dl', { class: 'answers' }, Object.entries(report.answers ?? {}).flatMap(([key, value]) => [
        el('dt', {}, labels[key] ?? key), el('dd', {}, value),
      ])),
    ),
    el('p', { class: 'detail-request-question' }, request.question),
    replyForm,
  );
}

async function loadRequests(message = '') {
  if (!requestsRoot) return;
  if (getRole() !== 'tester') {
    requestsRoot.hidden = true;
    return;
  }
  requestsRoot.replaceChildren(el('p', { role: 'status' }, 'Loading requests for more detail...'));
  try {
    const [profiles, forms] = await Promise.all([getProfiles(), api('/api/forms')]);
    const tester = profiles.find((profile) => profile.role === 'tester');
    if (!tester) throw new Error('The demo tester profile is missing. Run the profile seed first.');
    const requests = await api(`/api/detail-requests?tester_id=${encodeURIComponent(tester.id)}`);
    requestsRoot.replaceChildren(
      el('div', { class: 'toolbar' },
        el('h2', {}, 'Requests for more detail'),
        el('button', { class: 'button button--quiet', type: 'button', onclick: () => loadRequests() },
          'Refresh requests',
        ),
      ),
      el('p', {}, 'Your manager may ask a question about a report you submitted. Your original report is kept.'),
      ...(message ? [el('p', { class: 'status', role: 'status' }, message)] : []),
      requests.length
        ? el('ul', { class: 'tester-detail-list' }, requests.map((request) =>
            requestCard(request, tester.id, forms, loadRequests)))
        : el('p', {}, 'No requests for more detail at the moment.'),
    );
    if (message) await loadReportStatus();
  } catch (error) {
    requestsRoot.replaceChildren(
      el('h2', {}, 'Requests for more detail'),
      el('p', { class: 'status status--error', role: 'alert' }, error.message),
      el('button', { class: 'button button--quiet', type: 'button', onclick: () => loadRequests() }, 'Try again'),
    );
  }
}

async function loadReportStatus() {
  if (!progressRoot) return;
  if (getRole() !== 'tester') {
    progressRoot.hidden = true;
    return;
  }
  progressRoot.replaceChildren(el('p', { role: 'status' }, 'Loading your report progress...'));
  try {
    const profiles = await getProfiles();
    const tester = profiles.find((profile) => profile.role === 'tester');
    if (!tester) throw new Error('The demo tester profile is missing.');
    const reports = await api(`/api/tester/report-status?tester_id=${encodeURIComponent(tester.id)}`);
    const labels = {
      manager_review: 'With the UAT manager', needs_detail: 'More detail requested',
      forwarded: 'Forwarded to development', in_progress: 'In progress with development',
      ready_for_retest: 'Ready for retest',
    };
    progressRoot.replaceChildren(
      el('div', { class: 'toolbar' },
        el('h2', {}, 'Your report progress'),
        el('button', { class: 'button button--quiet', type: 'button', onclick: loadReportStatus }, 'Refresh progress'),
      ),
      el('p', {}, 'Latest reports for the demo tester profile, with forwarded reports first.'),
      reports.length
        ? el('ul', { class: 'report-progress-list' }, reports.map((report) =>
            el('li', { class: 'report-progress-card' },
              el('h3', {}, report.title),
              el('p', { class: 'report-progress-status' }, labels[report.status] ?? 'With the UAT manager'),
              el('p', { class: 'issue__meta' }, `Submitted ${new Date(report.created_at).toLocaleString('en-GB')}`),
            )))
        : el('p', {}, 'Your submitted reports will appear here.'),
    );
  } catch (error) {
    progressRoot.replaceChildren(el('h2', {}, 'Your report progress'),
      el('p', { class: 'status status--error', role: 'alert' }, error.message),
      el('button', { class: 'button button--quiet', type: 'button', onclick: loadReportStatus }, 'Try again'));
  }
}

loadRequests();
loadReportStatus();
