import { api, getProfiles } from './api.js';
import { el } from './dom.js';

const LABELS = {
  under_review: 'Under review', forwarded: 'Forwarded to development',
  in_progress: 'In development', ready_for_retest: 'Ready for retest',
  completed: 'Completed', not_forwarded: 'Not taking forward',
};

export async function loadTesterUpdates(root) {
  if (!root) return;
  root.replaceChildren(el('p', { role: 'status' }, 'Loading your updates...'));
  try {
    const tester = (await getProfiles()).find((profile) => profile.role === 'tester');
    if (!tester) throw new Error('The demo tester profile is missing.');
    const updates = await api(`/api/tester/updates?tester_id=${encodeURIComponent(tester.id)}`);
    root.replaceChildren(
      el('div', { class: 'tester-updates__heading' },
        el('h2', { id: 'tester-updates-heading' }, 'Updates on your reports'),
        el('button', { class: 'button button--quiet', type: 'button', onclick: () => loadTesterUpdates(root) }, 'Refresh updates'),
      ),
      el('p', { class: 'issue__meta' }, 'Thank you for helping us improve. Check here for updates from the team.'),
      updates.length ? el('ul', { class: 'tester-updates__list' }, updates.map((update) =>
        el('li', { class: 'tester-update-card' },
          el('span', { class: `tester-update-status tester-update-status--${update.status}` }, LABELS[update.status] ?? 'Update from your team'),
          el('h3', {}, update.reports[0]?.title ?? 'Your report'),
          update.reports.length > 1 ? el('details', {},
            el('summary', {}, `Applies to ${update.reports.length} of your reports`),
            el('ul', {}, update.reports.map((report) => el('li', {}, report.title))),
          ) : null,
          el('p', { class: 'tester-update-message' }, update.message),
          update.reason ? el('div', {}, el('strong', {}, 'Why we made this decision'),
            el('p', { class: 'tester-update-message' }, update.reason)) : null,
          el('p', { class: 'issue__meta' }, `Updated ${new Date(update.updated_at).toLocaleString('en-GB')}`),
        )))
        : el('p', {}, 'Updates will appear here when your reports have been reviewed. Thank you for helping us improve.'),
    );
  } catch (error) {
    root.replaceChildren(el('h2', {}, 'Updates on your reports'),
      el('p', { class: 'status status--error', role: 'alert' }, error.message),
      el('button', { class: 'button button--quiet', type: 'button', onclick: () => loadTesterUpdates(root) }, 'Try again'));
  }
}

export function testerFeedbackPanel(issue, onSaved) {
  const host = el('div', {});
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const prepare = el('button', { class: 'button button--quiet', type: 'button' }, 'Prepare tester update');
  let busy = false;
  prepare.addEventListener('click', async () => {
    if (busy) return;
    busy = true;
    prepare.disabled = true;
    status.textContent = 'Loading message suggestions...';
    try {
      const context = await api(`/api/issues/${encodeURIComponent(issue.id)}/tester-feedback`);
      const action = el('select', { id: `feedback-action-${issue.id}` },
        (context.closed ? [['reopen', 'Reopen for review']] : [
          ['send_update', 'Send a progress update'], ['not_forwarded', 'Not taking forward'],
          ...(context.can_complete ? [['completed', 'Complete after checking the fix']] : []),
        ]).map(([value, label]) => el('option', { value }, label)),
      );
      action.value = context.closed ? 'reopen' : 'send_update';
      const message = el('textarea', { id: `feedback-message-${issue.id}`, rows: 5, maxlength: 3000 });
      const reason = el('textarea', { id: `feedback-reason-${issue.id}`, rows: 4, maxlength: 2000 });
      const reasonField = el('div', { class: 'field' },
        el('label', { for: reason.id }, 'Explain why you are not taking this forward (required)'), reason);
      const checked = el('input', { type: 'checkbox' });
      const confirmation = el('label', { class: 'tester-feedback-confirmation' }, checked,
        ' I have checked the fix and confirm this issue is resolved.');
      function suggest() {
        message.value = context.suggestions[action.value === 'send_update' ? context.current_status : action.value] ?? '';
        reasonField.hidden = action.value !== 'not_forwarded';
        confirmation.hidden = action.value !== 'completed';
        checked.checked = false;
      }
      action.addEventListener('change', suggest);
      suggest();
      const send = el('button', { class: 'button', type: 'submit' }, 'Send update to testers');
      const form = el('form', { class: 'tester-feedback-form', novalidate: true },
        el('p', {}, `Current status: ${LABELS[context.current_status] ?? context.current_status}. This applies to the testers linked to this grouped issue.`),
        el('div', { class: 'field' }, el('label', { for: action.id }, 'Action'), action),
        el('div', { class: 'field' }, el('label', { for: message.id }, 'Message to testers (editable)'), message),
        reasonField, confirmation,
        !context.closed && !context.can_complete ? el('p', { class: 'issue__meta' }, 'Completion becomes available when the developer ticket is Ready for retest. Check the fix before confirming completion.') : null,
        send,
      );
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (busy) return;
        if (!message.value.trim() || (action.value === 'not_forwarded' && !reason.value.trim())) {
          status.textContent = 'Add a message and, when not taking a report forward, an explanation.';
          return;
        }
        if (action.value === 'completed' && !checked.checked) {
          status.textContent = 'Confirm that you have checked the fix before completing this issue.';
          return;
        }
        busy = true; send.disabled = true; prepare.disabled = true;
        status.textContent = 'Saving the tester update...';
        try {
          await api(`/api/issues/${encodeURIComponent(issue.id)}/tester-feedback`, {
            method: 'POST', body: JSON.stringify({ action: action.value, message: message.value,
              reason: action.value === 'not_forwarded' ? reason.value : '', checked_fix: checked.checked }),
          });
          await onSaved();
        } catch (error) {
          status.textContent = error.message;
          status.className = 'status status--error';
        } finally { busy = false; send.disabled = false; prepare.disabled = false; }
      });
      host.replaceChildren(form);
      status.textContent = '';
      prepare.textContent = 'Reload message options';
    } catch (error) {
      status.textContent = error.message;
      status.className = 'status status--error';
    } finally { busy = false; prepare.disabled = false; }
  });
  return el('details', { class: 'tester-feedback-panel' },
    el('summary', {}, 'Update testers / close issue'), prepare, host, status);
}
