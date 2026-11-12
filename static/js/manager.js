import { api } from './api.js';
import { el } from './dom.js';
import { getRole, initHeader, setRole } from './header.js';
import { TECHNICAL_FIELDS, technicalLog } from './technical.js';

initHeader();

const root = document.getElementById('manager-root');
let managerView = 'review';

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
  return new Date(value).toLocaleString('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

function confidenceLabel(value) {
  if (typeof value !== 'number' ||
      !Number.isFinite(value) ||
      value < 0 ||
      value > 1) {
    return null;
  }

  if (value < 0.5) return 'Low';
  if (value < 0.8) return 'Medium';
  return 'High';
}

function qualityAssessment(report) {
  const quality = report.ai_quality;

  // Legacy reports have no AI quality assessment.
  if (!quality || typeof quality !== 'object') {
    return null;
  }

  const status = quality.status;

  if (status !== 'ok') {
    return el('section', {
      class: 'ai-quality',
      'aria-label': 'AI quality assessment',
    },
      el('h3', { class: 'ai-quality__heading' }, 'AI quality check'),
      el('p', { class: 'ai-quality__unavailable' },
        'AI check unavailable, needs manager review.',
      ),
    );
  }

  const verdict = quality.is_clear === true
    ? 'Clear'
    : 'Needs more detail';

  const confidence = confidenceLabel(quality.confidence);

  const verdictRow = el('div', { class: 'ai-quality__verdict' },
    el('span', {
      class: quality.is_clear === true
        ? 'ai-quality__result ai-quality__result--clear'
        : 'ai-quality__result ai-quality__result--needs-detail',
    }, verdict),
    confidence
      ? el('span', { class: 'ai-quality__confidence' },
          `${confidence} confidence`,
        )
      : null,
  );

  const details = [];

  if (typeof quality.reasoning === 'string' &&
      quality.reasoning.trim()) {
    details.push(
      el('dt', {}, 'Reasoning'),
      el('dd', {}, quality.reasoning),
    );
  }

  if (typeof quality.model === 'string' &&
      quality.model.trim()) {
    details.push(
      el('dt', {}, 'Model'),
      el('dd', {}, quality.model),
    );
  }

  return el('section', {
    class: 'ai-quality',
    'aria-label': 'AI quality assessment',
  },
    el('h3', { class: 'ai-quality__heading' }, 'AI quality check'),
    verdictRow,
    details.length
      ? el('dl', { class: 'ai-quality__details' }, ...details)
      : null,
  );
}

function followUpDetails(report) {
  const question = report.follow_up_question;

  if (typeof question !== 'string' || !question.trim()) {
    return null;
  }

  const answer = report.follow_up_answer;

  const answerText = typeof answer === 'string' && answer.trim()
    ? answer
    : 'Not answered';

  return el('section', {
    class: 'report-follow-up',
    'aria-label': 'Tester follow-up',
  },
    el('h3', { class: 'report-follow-up__heading' }, 'Tester follow-up'),
    el('dl', { class: 'report-follow-up__details' },
      el('dt', {}, 'Question'),
      el('dd', {}, question),
      el('dt', {}, 'Answer'),
      el('dd', {}, answerText),
    ),
  );
}

function reportAnswers(report, category, forms) {
  const labels = {};

  for (const field of forms[category]?.fields ?? []) {
    labels[field.key] = field.label;
  }

  return el('dl', { class: 'answers' },
    Object.entries(report.answers ?? {}).flatMap(([key, value]) => [
      el('dt', {}, labels[key] ?? key),
      el('dd', {}, value),
    ]),
  );
}

function similarityLabel(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) ||
      value < -1 || value > 1) {
    return null;
  }

  return `${(value * 100).toFixed(1)}%`;
}

function duplicateAssessment(report, issue, forms, lookup) {
  const check = report.duplicate_check;

  if (!check || typeof check !== 'object' || check.status === 'skipped') {
    return null;
  }

  const heading = el('h3', { class: 'duplicate-check__heading' }, 'Duplicate check');

  if (check.status === 'unavailable') {
    return el('section', {
      class: 'duplicate-check',
      'aria-label': 'Duplicate check',
    }, heading,
      el('p', {}, 'Duplicate check unavailable, needs manager review.'),
    );
  }

  if (check.status !== 'ok') return null;

  const isMatch = check.outcome === 'likely' || check.outcome === 'possible';
  const matches = report.duplicate_matches ?? [];
  const matched = lookup.reports.get(check.matched_report_id);
  const match = matches.find((candidate) =>
    candidate.matched_issue_id === matched?.issue.id,
  ) ?? matches[0];

  let verdict = 'Saved as a new issue.';

  if (check.outcome === 'likely') {
    verdict = 'Grouped with this issue automatically.';
  } else if (check.outcome === 'possible') {
    const candidateTitle = lookup.issues.get(match?.matched_issue_id)?.title ?? matched?.issue.title;
    verdict = candidateTitle
      ? `Possible duplicate of: ${candidateTitle}`
      : 'Possible duplicate of an issue whose details are unavailable.';
  }

  const details = [el('p', { class: 'duplicate-check__verdict' }, verdict)];
  const similarity = similarityLabel(check.best_score);

  if (similarity) {
    details.push(el('dl', { class: 'duplicate-check__details' },
      el('dt', {}, 'Similarity score (calculated from the text)'),
      el('dd', {}, similarity),
    ));
  }

  if (isMatch) {
    if (match?.manager_decision === 'pending' || !match) {
      details.push(el('p', { class: 'duplicate-check__pending' },
        'Awaiting manager review.',
      ));
    }

    const explanation = typeof match?.reasoning === 'string' && match.reasoning.trim()
      ? match.reasoning
      : 'The wording is similar. AI explanation unavailable.';

    details.push(
      el('dl', { class: 'duplicate-check__details' },
        el('dt', {}, 'AI explanation (can be wrong)'),
        el('dd', {}, explanation),
      ),
      el('div', { class: 'duplicate-comparison' },
        el('section', { class: 'duplicate-comparison__report' },
          el('h4', {}, 'This report'),
          reportAnswers(report, issue.category, forms),
        ),
        el('section', { class: 'duplicate-comparison__report' },
          el('h4', {}, 'Existing report'),
          matched && matched.report.id !== report.id
            ? reportAnswers(matched.report, matched.issue.category, forms)
            : el('p', {}, 'The report used for this comparison is unavailable.'),
        ),
      ),
    );
  }

  return el('section', {
    class: 'duplicate-check',
    'aria-label': 'Duplicate check',
  }, heading, ...details);
}

function hasPendingPossible(issue) {
  return (issue.reports ?? []).some((report) =>
    report.duplicate_check?.status === 'ok' &&
    report.duplicate_check.outcome === 'possible' &&
    (!(report.duplicate_matches ?? []).length ||
      report.duplicate_matches.some((match) => match.manager_decision === 'pending')),
  );
}

function activeDetailRequest(report) {
  return (report.detail_requests ?? []).find((request) =>
    request.status === 'draft' || request.status === 'pending',
  );
}

function managerClarifications(report) {
  const replies = report.manager_clarifications ??
    (report.detail_requests ?? []).filter((request) => request.status === 'answered');
  if (!replies.length) return null;

  return el('section', { class: 'manager-clarifications' },
    el('h3', {}, 'Manager requests and replies'),
    replies.map((reply) => el('div', { class: 'manager-clarifications__reply' },
      el('dl', { class: 'answers' },
        el('dt', {}, 'Question'), el('dd', {}, reply.question),
        el('dt', {}, 'Tester answer'), el('dd', {}, reply.answer),
      ),
      reply.answered_at
        ? el('p', { class: 'issue__meta' }, `Answered ${formatDate(reply.answered_at)}`)
        : null,
    )),
  );
}

function requestDetailAction(report) {
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const mark = el('button', { class: 'button button--quiet', type: 'button' },
    'Request more detail',
  );
  mark.addEventListener('click', async () => {
    mark.disabled = true;
    status.className = 'status';
    status.textContent = 'Preparing a question...';
    try {
      await api(`/api/reports/${encodeURIComponent(report.id)}/detail-request`, { method: 'POST' });
      await load();
    } catch (error) {
      status.textContent = error.message || 'Could not move this report.';
      status.className = 'status status--error';
      mark.disabled = false;
    }
  });
  return el('div', { class: 'detail-request-actions' }, mark, status);
}

function detailRequestCard(issue, report, request, forms) {
  const draft = request.status === 'draft';
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const cancel = el('button', { class: 'button button--quiet', type: 'button' },
    'Return to review queue',
  );
  const send = draft
    ? el('button', { class: 'button', type: 'submit' }, 'Send to tester')
    : null;
  const question = draft
    ? el('textarea', { id: `manager-question-${request.id}`, rows: 4, maxlength: 2000 })
    : null;
  if (question) question.value = request.question ?? '';

  function setPending(value) {
    cancel.disabled = value;
    if (send) send.disabled = value;
    if (question) question.disabled = value;
  }

  async function perform(action, body) {
    setPending(true);
    status.className = 'status';
    status.textContent = action === 'send' ? 'Sending your question...' : 'Returning the report...';
    try {
      await api(`/api/detail-requests/${encodeURIComponent(request.id)}/${action}`, {
        method: 'POST',
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      await load();
    } catch (error) {
      status.className = 'status status--error';
      status.textContent = error.message || 'Could not update this request.';
      setPending(false);
    }
  }

  cancel.addEventListener('click', () => perform('cancel'));
  const controls = draft
    ? el('form', { class: 'detail-request-form', novalidate: true },
        el('label', { for: `manager-question-${request.id}` },
          request.suggestion_status === 'ok'
            ? 'AI-suggested question. Edit before sending.'
            : 'Suggested question. AI unavailable, please review and edit.',
        ),
        question,
        el('div', { class: 'detail-request-actions' }, send, cancel),
        status,
      )
    : el('div', {},
        el('h4', {}, 'Question sent to tester'),
        el('p', { class: 'detail-request-question' }, request.question),
        el('p', { class: 'issue__meta' }, 'Awaiting tester response.'),
        request.sent_at
          ? el('p', { class: 'issue__meta' }, `Sent ${formatDate(request.sent_at)}`)
          : null,
        cancel,
        status,
      );

  if (draft) {
    controls.addEventListener('submit', (event) => {
      event.preventDefault();
      if (send.disabled) return;
      const text = question.value.trim();
      if (!text) {
        status.textContent = 'Write a question before sending.';
        status.className = 'status status--error';
        question.focus();
        return;
      }
      return perform('send', { question: text });
    });
  }

  return el('li', { class: `detail-request-card issue--${issue.category}` },
    el('p', { class: 'issue__meta' }, `${forms[issue.category]?.label ?? issue.category} report`),
    el('h3', {}, issue.title),
    el('p', { class: 'issue__meta' }, `Submitted ${formatDate(report.created_at)}`),
    el('details', {},
      el('summary', {}, 'Read this report'),
      reportAnswers(report, issue.category, forms),
      followUpDetails(report),
      managerClarifications(report),
      qualityAssessment(report),
    ),
    controls,
  );
}

function answersList(issue, forms, lookup, allowRequests = true) {
  const reports = (issue.reports ?? []).filter((report) => !activeDetailRequest(report));

  if (!reports.length) {
    return el('p', { class: 'issue__meta' },
      'No report details found.',
    );
  }

  return el('div', {},
    reports.map((report, index) =>
      el('div', { class: 'report-details' },
        index > 0
          ? el('hr', { class: 'report-divider' })
          : null,
        el('p', { class: 'issue__meta' },
          `Sent ${formatDate(report.created_at)}`,
        ),
        report.occurred_at
          ? el('p', { class: 'issue__meta' }, `Reported occurrence: ${formatDate(report.occurred_at)}`)
          : null,
        reportAnswers(report, issue.category, forms),
        duplicateAssessment(report, issue, forms, lookup),
        followUpDetails(report),
        qualityAssessment(report),
        managerClarifications(report),
        allowRequests ? requestDetailAction(report) : null,
      ),
    ),
  );
}

function consolidatedIsCurrent(assessment, issue) {
  const current = new Map((issue.reports ?? []).map((report) => [report.id, report]));
  const sources = assessment.source_reports ?? [];

  return sources.length === current.size && sources.every((source) => {
    const report = current.get(source.id);
    if (!report) return false;
    const answers = report.answers ?? {};
    const savedAnswers = source.answers ?? {};
    return Object.keys(answers).length === Object.keys(savedAnswers).length &&
      Object.entries(savedAnswers).every(([key, value]) => answers[key] === value) &&
      (report.follow_up_question ?? null) === (source.follow_up_question ?? null) &&
      (report.follow_up_answer ?? null) === (source.follow_up_answer ?? null) &&
      (report.occurred_at ?? null) === (source.occurred_at ?? null) &&
      (report.created_at ?? null) === (source.created_at ?? null) &&
      (report.detail_revision ?? 0) === (source.detail_revision ?? 0) &&
      JSON.stringify((report.detail_requests ?? []).filter((item) => item.status === 'answered')
        .sort((a, b) => a.id.localeCompare(b.id)).map(({ id, question, answer, answered_at }) =>
          ({ id, question, answer, answered_at }))) === JSON.stringify(source.manager_clarifications ?? []);
  });
}

function logEvidence(assessment, issue) {
  if (issue.category !== 'bug' && issue.category !== 'awkward') return null;

  const evidence = assessment?.log_evidence;
  if (evidence?.status === 'skipped') return null;
  const content = [];

  if (!evidence) {
    content.push(el('p', {},
      'Generate or refresh the final report to search for supporting logs.',
    ));
  } else if (evidence.status !== 'ok') {
    content.push(el('p', { role: 'status' },
      evidence.message || 'Log evidence unavailable. Try refreshing the final report.',
    ));
  } else {
    content.push(el('p', { class: 'log-evidence__meta' },
      `Mock CloudWatch events searched within ${evidence.window_minutes} minutes before or after each report's occurrence time, or submission time when blank.`,
    ));
    if (evidence.session_start && evidence.session_end) {
      content.push(el('p', { class: 'log-evidence__meta' },
        `Mock session: ${formatDate(evidence.session_start)} to ${formatDate(evidence.session_end)}.`,
      ));
    }
    if (!consolidatedIsCurrent(assessment, issue)) {
      content.push(el('p', { class: 'consolidated-report__warning' },
        'Evidence belongs to an earlier source version. Refresh the final report.',
      ));
    }
    if (!evidence.matches?.length) {
      content.push(el('p', {}, 'No supporting logs found'));
    } else {
      content.push(el('p', { class: 'log-evidence__meta' },
        'Relevance is calculated from shared terms and timing. These events provide investigation leads.',
      ));
      const sourceNumbers = new Map((assessment.source_reports ?? []).map(
        (source, index) => [source.id, index + 1],
      ));
      content.push(el('ol', { class: 'log-evidence__list' },
        evidence.matches.map((entry, index) =>
          el('li', { class: 'log-evidence__entry' },
            el('h4', {}, `Log ${index + 1}`),
            el('dl', { class: 'log-evidence__details' },
              el('dt', {}, 'Timestamp'), el('dd', {}, formatDate(entry.timestamp)),
              el('dt', {}, 'Service'), el('dd', {}, entry.service),
              el('dt', {}, 'Level'), el('dd', {}, entry.level),
              el('dt', {}, 'Error code'), el('dd', {}, entry.error_code || 'None supplied'),
              el('dt', {}, 'Log relevance score'),
              el('dd', {}, similarityLabel(entry.relevance_score) ?? 'Unavailable'),
              el('dt', {}, 'Reasoning'), el('dd', {}, entry.reasoning),
              el('dt', {}, 'Related source reports'),
              el('dd', {}, (entry.report_ids ?? []).map((id) =>
                sourceNumbers.has(id) ? `Report ${sourceNumbers.get(id)}` : 'Source report unavailable',
              ).join(', ')),
            ),
            el('pre', { class: 'log-evidence__message' }, entry.message),
          ),
        ),
      ));
    }
  }

  return el('details', { class: 'log-evidence' },
    el('summary', {}, 'Supporting logs (mock CloudWatch)'),
    ...content,
  );
}

function consolidatedReport(issue, forms) {
  const minimumReports = ['bug', 'awkward'].includes(issue.category) ? 1 : 2;
  if (issue.report_count < minimumReports) return null;

  const assessment = issue.consolidated_report;
  const content = assessment?.content;
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });
  const generate = el('button', {
    class: 'button button--quiet',
    type: 'button',
  }, content ? 'Refresh final report' : 'Generate final report');

  generate.addEventListener('click', async () => {
    generate.disabled = true;
    status.textContent = 'Combining the reports...';
    status.className = 'status';
    try {
      const result = await api(
        `/api/issues/${encodeURIComponent(issue.id)}/consolidated-report`,
        { method: 'POST' },
      );
      if (result.status === 'unavailable') {
        throw new Error(result.message);
      }
      await load();
    } catch (error) {
      status.textContent = error.message || 'Could not refresh the final report.';
      status.className = 'status status--error';
      generate.disabled = false;
    }
  });

  const sections = [];

  if (content) {
    sections.push(
      el('h3', { class: 'consolidated-report__title' }, content.title),
      el('p', { class: 'consolidated-report__meta' },
        `Combined from ${plural(assessment.report_count, 'report')}. Updated ${formatDate(assessment.generated_at)}.`,
      ),
      el('p', { class: 'consolidated-report__meta' },
        assessment.status === 'ok'
          ? 'AI-written synthesis. Check it against the source reports.'
          : 'AI synthesis unavailable. Original supplied details are combined below.',
      ),
    );

    if (!consolidatedIsCurrent(assessment, issue)) {
      sections.push(el('p', { class: 'consolidated-report__warning', role: 'status' },
        'This version does not include the latest source details. Refresh the final report.',
      ));
    }

    sections.push(el('p', { class: 'consolidated-report__summary' }, content.summary));

    const fields = [
      ['expected_behaviour', 'Expected behaviour'],
      ['actual_behaviour', 'Actual behaviour'],
      ['steps_to_reproduce', 'Reported steps to reproduce'],
      ['affected_pages', 'Affected pages or screens'],
      ['browsers_devices', 'Browsers and devices'],
      ['impact', 'Reported impact'],
      ['conflicts', 'Conflicts or potentially different problems'],
      ['missing_information', 'Missing information'],
    ];

    for (const [key, label] of fields) {
      const values = content[key] ?? [];
      sections.push(el('section', { class: 'consolidated-report__section' },
        el('h4', {}, label),
        values.length
          ? el('ul', {}, values.map((value) => el('li', {}, value)))
          : el('p', { class: 'consolidated-report__meta' },
              key === 'conflicts' ? 'None identified in this synthesis.' : 'No details listed in this synthesis.',
            ),
      ));
    }

    sections.push(logEvidence(assessment, issue));

    sections.push(el('details', { class: 'consolidated-report__sources' },
      el('summary', {}, 'Source reports used for this version'),
      (assessment.source_reports ?? []).map((source, index) =>
        el('section', { class: 'consolidated-report__source' },
          el('h4', {}, `Report ${index + 1}`),
          source.occurred_at
            ? el('p', { class: 'issue__meta' }, `Reported occurrence: ${formatDate(source.occurred_at)}`)
            : null,
          reportAnswers(source, source.category ?? issue.category, forms),
          followUpDetails(source),
          managerClarifications(source),
        ),
      ),
    ));
  } else {
    sections.push(el('p', {},
      'Generate a detailed report combining the submitted answers and follow-ups for this issue.',
    ));
  }

  return el('details', { class: 'consolidated-report' },
    el('summary', {}, 'Final detailed report'),
    ...sections,
    el('div', { class: 'consolidated-report__actions' }, generate, status),
  );
}

function handoffPanel(issue, forms) {
  const status = el('p', { class: 'status', role: 'status', 'aria-live': 'polite' });

  if (issue.handoff_status === 'forwarded') {
    const reopen = el('button', { class: 'button button--quiet', type: 'button' }, 'Reopen for manager review');
    reopen.addEventListener('click', async () => {
      reopen.disabled = true;
      status.textContent = 'Returning the issue to manager review...';
      try {
        await api(`/api/issues/${encodeURIComponent(issue.id)}/reopen-handoff`, { method: 'POST' });
        managerView = 'review';
        await load();
      } catch (error) {
        status.textContent = error.message || 'Could not reopen the issue.';
        status.className = 'status status--error';
        reopen.disabled = false;
      }
    });
    return el('section', { class: 'technical-handover' },
      el('h3', {}, 'Forwarded to development'),
      el('p', {}, `Approved ${formatDate(issue.forwarded_at)}.`),
      reopen, status,
    );
  }

  const body = el('div', { class: 'technical-editor-host' });
  const generate = el('button', { class: 'button button--quiet', type: 'button' }, 'Prepare technical draft');
  let state = null;
  let busy = false;
  let editorShown = false;

  function renderEditor() {
    const draft = state.draft;
    const controls = {};
    const logChecks = [];
    const candidates = draft.source_snapshot.log_candidates ?? [];
    const save = el('button', { class: 'button button--quiet', type: 'button' }, 'Save draft');
    const approve = el('button', { class: 'button', type: 'submit' }, 'Approve and forward');
    const canApprove = state.source_is_current && !state.open_detail_requests;
    approve.disabled = !canApprove;
    const fields = TECHNICAL_FIELDS.map(([key, label]) => {
      const id = `technical-${issue.id}-${key}`;
      const control = key === 'title'
        ? el('input', { id, name: key, type: 'text', maxlength: 300 })
        : el('textarea', { id, name: key, rows: key === 'problem_summary' ? 5 : 3 });
      control.value = draft.content[key] ?? '';
      controls[key] = control;
      return el('div', { class: 'field' }, el('label', { for: id }, label), control);
    });
    const priority = el('select', { id: `technical-${issue.id}-priority` },
      ['low', 'medium', 'high', 'critical'].map((value) => el('option', { value }, value)),
    );
    priority.value = draft.content.priority;
    const logs = candidates.map((entry) => {
      const check = el('input', { type: 'checkbox', value: entry.id });
      check.checked = draft.content.included_log_ids.includes(entry.id);
      logChecks.push(check);
      return el('label', { class: 'technical-log-choice' },
        el('span', {}, check, ' Include this event'), technicalLog(entry),
      );
    });
    const form = el('form', { class: 'technical-editor', novalidate: true },
      draft.generation_status === 'fallback'
        ? el('p', { class: 'technical-warning' }, 'AI drafting unavailable. Review and edit the assembled draft.')
        : el('p', {}, 'AI-prepared draft. Review the wording, suggested priority and selected evidence before approval.'),
      !state.source_is_current
        ? el('p', { class: 'technical-warning' }, 'Reports have changed. Regenerate from the latest reports before approving.')
        : null,
      state.open_detail_requests
        ? el('p', { class: 'technical-warning' }, 'Answer or cancel open requests for more detail before forwarding.')
        : null,
      ...fields,
      el('div', { class: 'field' }, el('label', { for: `technical-${issue.id}-priority` }, 'Priority'), priority),
      el('fieldset', { class: 'technical-log-selection' },
        el('legend', {}, 'Choose supporting log events'),
        el('p', {}, 'Include relevant evidence. Log matches are investigation leads.'),
        logs.length ? logs : el('p', {}, 'No candidate log events were found.'),
      ),
      el('details', {},
        el('summary', {}, 'Source reports used for this draft'),
        draft.source_snapshot.reports.map((source, index) =>
          el('section', { class: 'technical-source' },
            el('h4', {}, `Report ${index + 1}`),
            reportAnswers(source, source.category ?? issue.category, forms),
            followUpDetails(source), managerClarifications(source),
          )),
      ),
      el('div', { class: 'technical-editor__actions' }, save, approve),
    );

    async function act(action) {
      if (busy || (action === 'approve' && !canApprove)) return;
      const content = Object.fromEntries(Object.entries(controls).map(([key, control]) => [key, control.value]));
      if (!content.title.trim() || !content.problem_summary.trim()) {
        status.textContent = 'Add a title and problem summary before forwarding.';
        status.className = 'status status--error';
        return;
      }
      content.priority = priority.value;
      content.included_log_ids = logChecks.filter((check) => check.checked).map((check) => check.value);
      busy = true;
      save.disabled = true;
      approve.disabled = true;
      generate.disabled = true;
      status.textContent = action === 'approve' ? 'Saving your approval and forwarding this issue...' : 'Saving draft...';
      status.className = 'status';
      try {
        const result = await api(`/api/issues/${encodeURIComponent(issue.id)}/${action === 'approve' ? 'approve-handoff' : 'technical-draft'}`, {
          method: action === 'approve' ? 'POST' : 'PUT',
          body: JSON.stringify({ expected_revision: state.draft.revision, content }),
        });
        if (action === 'approve') {
          managerView = 'forwarded';
          await load();
        } else {
          state.draft = result.draft;
          status.textContent = 'Draft saved.';
        }
      } catch (error) {
        status.textContent = error.message || 'Could not save the handover.';
        status.className = 'status status--error';
      } finally {
        busy = false;
        save.disabled = false;
        approve.disabled = !canApprove;
        generate.disabled = false;
      }
    }
    save.addEventListener('click', () => act('save'));
    form.addEventListener('submit', (event) => { event.preventDefault(); return act('approve'); });
    body.replaceChildren(form);
    editorShown = true;
  }

  generate.addEventListener('click', async () => {
    if (busy) return;
    busy = true;
    generate.disabled = true;
    status.textContent = 'Preparing an editable technical draft...';
    status.className = 'status';
    try {
      if (!state) state = await api(`/api/issues/${encodeURIComponent(issue.id)}/technical-draft`);
      if (!state.draft || editorShown) {
        state = await api(`/api/issues/${encodeURIComponent(issue.id)}/technical-draft`, { method: 'POST' });
      }
      renderEditor();
      generate.textContent = 'Regenerate from latest reports';
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message || 'Could not prepare the draft.';
      status.className = 'status status--error';
    } finally {
      busy = false;
      generate.disabled = false;
    }
  });

  return el('details', { class: 'technical-handover' },
    el('summary', {}, 'Technical developer handover'), generate, body, status,
  );
}

function issueCard(issue, forms, lookup) {
  const category = issue.category;
  const pendingCount = (issue.reports ?? []).filter(activeDetailRequest).length;

  return el('li', { class: `issue issue--${category}` },
    el('div', { class: 'issue__top' },
      el('span', { class: `chip chip--${category}` },
        forms[category]?.label ?? category,
      ),
      el('span', { class: 'chip chip--status' }, issue.handoff_status === 'forwarded' ? 'Forwarded' : issue.status),
      hasPendingPossible(issue)
        ? el('span', { class: 'chip chip--possible-duplicate' },
            'Possible duplicate: needs a decision',
          )
        : null,
      el('h2', { class: 'issue__title' }, issue.title),
    ),
    el('p', { class: 'issue__meta' },
      `${plural(issue.report_count, 'report')}. First reported ${formatDate(issue.created_at)}.`,
    ),
    pendingCount
      ? el('p', { class: 'issue__meta' }, `${plural(pendingCount, 'report')} awaiting more detail.`)
      : null,
    logEvidence(issue.consolidated_report, issue),
    consolidatedReport(issue, forms),
    handoffPanel(issue, forms),
    el('details', {},
      el('summary', {}, 'See what was reported'),
      answersList(issue, forms, lookup, issue.handoff_status !== 'forwarded'),
    ),
  );
}

async function load() {
  root.replaceChildren(
    el('p', { role: 'status' }, 'Loading the review queue...'),
  );

  let issues;
  let forms;

  try {
    [issues, forms] = await Promise.all([
      api('/api/issues'),
      api('/api/forms'),
    ]);
  } catch (error) {
    root.replaceChildren(
      el('p', {
        class: 'status status--error',
        role: 'alert',
      }, error.message),
      el('button', {
        class: 'button',
        type: 'button',
        onclick: load,
      }, 'Try again'),
    );
    return;
  }

  const lookup = {
    reports: new Map(),
    issues: new Map(issues.map((issue) => [issue.id, issue])),
  };

  for (const issue of issues) {
    for (const report of issue.reports ?? []) {
      lookup.reports.set(report.id, { report, issue });
    }
  }

  const forwardedIssues = issues.filter((issue) => issue.handoff_status === 'forwarded');
  const reviewItems = issues.filter((issue) => issue.handoff_status !== 'forwarded');
  const needsDetail = [];
  const reviewIssues = reviewItems.filter((issue) => {
    for (const report of issue.reports ?? []) {
      const request = activeDetailRequest(report);
      if (request) needsDetail.push({ issue, report, request });
    }
    return !(issue.reports ?? []).length ||
      issue.reports.some((report) => !activeDetailRequest(report));
  });
  needsDetail.sort((a, b) => new Date(b.request.created_at) - new Date(a.request.created_at));

  const heading = el('div', { class: 'toolbar' },
    el('div', {},
      el('h1', {}, managerView === 'forwarded' ? 'Forwarded issues' : 'Review queue'),
      el('p', { class: 'issue__meta' },
        `${plural(reviewItems.length, 'issue')} in review, ${plural(forwardedIssues.length, 'issue')} forwarded, ${plural(needsDetail.length, 'report')} needing more detail`,
      ),
    ),
    el('button', {
      class: 'button button--quiet', type: 'button', onclick: load,
    }, 'Refresh'),
  );

  const views = el('div', { class: 'manager-views', role: 'group', 'aria-label': 'Manager queue views' },
    ...[['review', 'Review'], ['forwarded', 'Forwarded']].map(([value, label]) =>
      el('button', { class: 'button button--quiet', type: 'button',
        'aria-pressed': String(managerView === value), onclick: () => { managerView = value; return load(); } }, label)),
  );
  if (managerView === 'forwarded') {
    root.replaceChildren(heading, views,
      forwardedIssues.length
        ? el('ul', { class: 'queue' }, forwardedIssues.map((issue) => issueCard(issue, forms, lookup)))
        : el('p', {}, 'No issues have been forwarded to development.'),
    );
    return;
  }

  root.replaceChildren(
    heading,
    views,
    el('div', { class: 'manager-board' },
      el('section', { class: 'manager-board__column', 'aria-labelledby': 'review-column-heading' },
        el('h2', { id: 'review-column-heading' }, 'Ready for review'),
        reviewIssues.length
          ? el('ul', { class: 'queue' }, reviewIssues.map((issue) => issueCard(issue, forms, lookup)))
          : el('p', {}, issues.length
              ? 'All submitted reports are currently awaiting more detail.'
              : 'Nothing to review yet. Reports from testers will appear here.'),
        !issues.length ? el('a', { class: 'button', href: '/' }, 'Add a test report') : null,
      ),
      el('section', { class: 'manager-board__column manager-board__column--detail',
        'aria-labelledby': 'detail-column-heading' },
        el('h2', { id: 'detail-column-heading' }, 'Needs more detail'),
        el('p', { class: 'issue__meta' }, 'Reports appear here only when you request more detail.'),
        needsDetail.length
          ? el('ul', { class: 'detail-request-list' }, needsDetail.map(({ issue, report, request }) =>
              detailRequestCard(issue, report, request, forms)))
          : el('p', {}, 'No reports need more detail.'),
      ),
    ),
  );
}

if (getRole() === 'manager') load();
else showGate();
