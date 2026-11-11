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

function answersList(issue, forms, lookup) {
  const reports = issue.reports ?? [];

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
        reportAnswers(report, issue.category, forms),
        duplicateAssessment(report, issue, forms, lookup),
        followUpDetails(report),
        qualityAssessment(report),
      ),
    ),
  );
}

function issueCard(issue, forms, lookup) {
  const category = issue.category;

  return el('li', { class: `issue issue--${category}` },
    el('div', { class: 'issue__top' },
      el('span', { class: `chip chip--${category}` },
        forms[category]?.label ?? category,
      ),
      el('span', { class: 'chip chip--status' }, issue.status),
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
    el('details', {},
      el('summary', {}, 'See what was reported'),
      answersList(issue, forms, lookup),
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

  const heading = el('div', { class: 'toolbar' },
    el('div', {},
      el('h1', {}, 'Review queue'),
      el('p', { class: 'issue__meta' },
        plural(issues.length, 'issue') + ', most-noticed first',
      ),
    ),
    el('button', {
      class: 'button button--quiet',
      type: 'button',
      onclick: load,
    }, 'Refresh'),
  );

  if (!issues.length) {
    root.replaceChildren(
      heading,
      el('p', {},
        'Nothing to review yet. Reports from testers will appear here.',
      ),
      el('a', {
        class: 'button',
        href: '/',
      }, 'Add a test report'),
    );
    return;
  }

  root.replaceChildren(
    heading,
    el('ul', { class: 'queue' },
      issues.map((issue) => issueCard(issue, forms, lookup)),
    ),
  );
}

if (getRole() === 'manager') load();
else showGate();
