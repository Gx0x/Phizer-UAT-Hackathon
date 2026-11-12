import { el } from './dom.js';

export const TECHNICAL_FIELDS = [
  ['title', 'Title'],
  ['problem_summary', 'Problem summary'],
  ['expected_behaviour', 'Expected behaviour'],
  ['actual_behaviour', 'Actual behaviour'],
  ['reproduction_steps', 'Reported reproduction steps'],
  ['environment', 'Environment and occurrence'],
  ['log_notes', 'Supporting log notes'],
];
export const DEVELOPER_STATUSES = [
  ['todo', 'To do'], ['in_progress', 'In progress'], ['ready_for_retest', 'Ready for retest'],
];

export function technicalLog(entry) {
  return el('div', { class: 'technical-log' },
    el('p', { class: 'issue__meta' },
      `${entry.timestamp ?? ''} · ${entry.service ?? ''} · ${entry.level ?? ''} · ${entry.error_code ?? ''}`,
    ),
    el('pre', {}, entry.message ?? ''),
  );
}

export function technicalContent(content) {
  return el('div', { class: 'technical-content' },
    TECHNICAL_FIELDS.filter(([key]) => key !== 'title').map(([key, label]) =>
      el('section', {},
        el('h3', {}, label),
        el('p', { class: 'technical-content__text' }, content[key] || 'Not supplied in the feedback.'),
      )),
    el('section', {},
      el('h3', {}, 'Approved supporting logs'),
      content.supporting_logs?.length
        ? content.supporting_logs.map(technicalLog)
        : el('p', {}, 'No log entries were selected for this ticket.'),
    ),
  );
}
