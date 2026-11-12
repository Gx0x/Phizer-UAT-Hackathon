import { api } from './api.js';
import { el } from './dom.js';
import { getRole, initHeader, setRole } from './header.js';
import { DEVELOPER_STATUSES, technicalContent } from './technical.js';

initHeader();
const root = document.getElementById('developer-root');

function ticketCard(ticket) {
  const content = ticket.content;
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const select = el('select', { id: `ticket-status-${ticket.id}` },
    DEVELOPER_STATUSES.map(([value, label]) => el('option', { value }, label)),
  );
  select.value = ticket.status;
  const save = el('button', { class: 'button button--quiet', type: 'submit' }, 'Update status');
  const form = el('form', { class: 'developer-status-form' },
    el('label', { for: `ticket-status-${ticket.id}` }, 'Development status'), select, save, status,
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (save.disabled) return;
    save.disabled = true;
    select.disabled = true;
    status.textContent = 'Saving status...';
    status.className = 'status';
    try {
      const result = await api(`/api/developer/tickets/${encodeURIComponent(ticket.id)}/status`, {
        method: 'PATCH', body: JSON.stringify({ expected_revision: ticket.revision, status: select.value }),
      });
      ticket.revision = result.ticket.revision;
      ticket.status = result.ticket.status;
      status.textContent = 'Status updated.';
    } catch (error) {
      status.textContent = error.message || 'Could not update the ticket.';
      status.className = 'status status--error';
    } finally {
      save.disabled = false;
      select.disabled = false;
    }
  });

  return el('li', { class: 'developer-ticket' },
    el('div', { class: 'issue__top' },
      el('span', { class: 'chip chip--status' }, 'Manager approved'),
      el('span', { class: 'chip chip--status' }, `${content.priority} priority`),
      el('h2', {}, content.title),
    ),
    el('p', { class: 'issue__meta' },
      `Approved ${new Date(ticket.approved_at).toLocaleString('en-GB')}. Based on ${ticket.source_report_count} report${ticket.source_report_count === 1 ? '' : 's'}.`,
    ),
    form,
    el('details', {}, el('summary', {}, 'Read approved technical specification'), technicalContent(content)),
  );
}

async function load() {
  root.replaceChildren(el('p', { role: 'status' }, 'Loading approved developer tickets...'));
  try {
    const tickets = await api('/api/developer/tickets');
    root.replaceChildren(
      el('div', { class: 'toolbar' },
        el('div', {}, el('h1', {}, 'Developer tickets'),
          el('p', { class: 'issue__meta' }, 'Technical specifications individually approved by the UAT manager.')),
        el('button', { class: 'button button--quiet', type: 'button', onclick: load }, 'Refresh'),
      ),
      tickets.length
        ? el('ul', { class: 'developer-ticket-list' }, tickets.map(ticketCard))
        : el('p', {}, 'No approved tickets yet. They appear here after manager approval.'),
    );
  } catch (error) {
    root.replaceChildren(el('p', { class: 'status status--error', role: 'alert' }, error.message),
      el('button', { class: 'button', type: 'button', onclick: load }, 'Try again'));
  }
}

if (getRole() === 'developer') load();
else root.replaceChildren(
  el('section', { class: 'notice' },
    el('h1', {}, 'This is the developer view'),
    el('p', {}, 'Switch role to see approved technical specifications.'),
    el('button', { class: 'button', type: 'button', onclick: () => {
      setRole('developer'); window.location.reload();
    } }, 'Switch to Developer'),
  ),
);
