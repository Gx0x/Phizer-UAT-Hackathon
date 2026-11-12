# UAT Clarif-AI

**AI-assisted feedback, human-led decisions.**

UAT Clarif-AI is a hackathon prototype that helps testers describe problems, helps UAT managers review the evidence, and turns approved feedback into developer-ready technical drafts. Testers can then see what happened to their reports.

It addresses common problems in user acceptance testing: the same issue being reported in different ways, feedback lacking actionable detail, evidence spread across submissions, and testers receiving no response after reporting something.

## Features

### Tester

- Guided forms for **Bug**, **Awkward**, **Suggestion** and **Extra** feedback.
- AI-generated follow-up questions when an initial report needs clarification.
- Optional occurrence time to help match a report with mock log events.
- A **Requests for more detail** section for manager questions. Answers are appended without overwriting the original submission.
- An **Updates on your reports** side panel showing only issues with a manager or development update, newest update first. The panel moves below the reporting area on smaller screens.
- Friendly messages for review, forwarding, development, retesting, completion and decisions not to take feedback forward.

### UAT manager

- A review queue with grouped issues and access to original reports, follow-up answers and manager clarification history.
- Separate **Review**, **Forwarded** and **Closed** views.
- A **Needs more detail** column populated only when the manager requests clarification on an individual report.
- Editable suggested questions that are sent to testers only when the manager chooses to send them.
- Duplicate similarity scores, generated explanations and source-report comparisons.
- Combined detailed reports with supplied evidence and remaining uncertainty.
- An editable technical draft with title, problem summary, expected and actual behaviour, reproduction steps, environment, log notes and suggested priority.
- Selection of relevant raw log events before **Approve and forward**. Missing-information and acceptance-criteria sections are excluded from the technical draft.
- Editable tester messages, completion after checking a fix, and **Not taking forward** with a required explanation.
- Reopening of forwarded or closed issues for further review.

### Developer

- A separate page containing individually approved technical specifications.
- The manager-reviewed wording and selected log evidence.
- Status updates through **To do → In progress → Ready for retest**.

The developer status does not mark an issue completed. The manager checks the fix and explicitly confirms completion.

## How AI is used

| Feature | Role of AI |
| --- | --- |
| Report quality check | Identifies missing detail and returns an explanation and confidence assessment. |
| Initial tester clarification | Generates a relevant follow-up question when the report needs more detail. |
| Manager clarification | Suggests a question for the manager to edit and send. |
| Duplicate detection | A local embedding model represents report meaning as vectors; pgvector compares their similarity. |
| Duplicate explanation | A language model explains why a matched pair may describe the same issue. |
| Combined detailed report | Synthesises original reports, follow-up answers, manager replies and supplied mock evidence. |
| Technical draft | Produces a developer-facing draft and suggested priority for manager review. |

Quality checking and initial clarification can be produced by the same AI assessment. These are workflow capabilities, not seven independent model calls for every submission.

Mock log matching uses keyword/concept overlap and timing rules. Tester status messages use editable templates and workflow events. Neither requires an additional language-model call.

## Human control and evidence

- Each developer handover requires individual manager approval. Generating or saving a draft does not create an active developer ticket.
- Original reports and clarification answers remain available alongside AI output.
- Similarity scores measure text similarity; they are not probabilities that reports describe the same bug. Automatic grouping can be wrong and must be reviewed before handover.
- Log relevance scores rank investigation leads. Matching events do not establish the cause of a tester's problem.
- Log messages remain unchanged. Managers select which events to include in a technical ticket.
- An unavailable AI provider does not intentionally block report submission. Technical drafting has an editable fallback assembled from supplied facts.
- “Not taking forward” requires a manager explanation and preserves the report for future review.

## Technology

| Component | Technology |
| --- | --- |
| Backend | Python and FastAPI |
| Frontend | HTML, CSS and JavaScript ES modules |
| Database | Supabase PostgreSQL with pgvector |
| Local embeddings | FastEmbed with `BAAI/bge-small-en-v1.5`, 384 dimensions |
| Generative AI | Configurable Gemini provider; optional Anthropic support |
| Log evidence | Local JSON mock dataset; no AWS connection |

The backend accesses Supabase with a server-only service key. Frontend text is rendered using DOM helpers rather than inserting tester content as HTML.

## Run locally

These instructions use Windows PowerShell from the project root. For a database already configured for this project, skip the initial migration steps.

### 1. Create the Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Using the virtual environment's Python directly avoids needing to activate it in PowerShell.

### 2. Configure environment variables

For a new checkout, copy the example file. Keep an existing working `.env` file.

```powershell
Copy-Item .env.example .env
```

Fill in the credentials locally. Never commit `.env` or put the Supabase service key in frontend code.

Example configuration, with placeholders for credentials and the available language model:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_KEY=YOUR_SERVER_ONLY_SERVICE_KEY

LLM_PROVIDER=gemini
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_MODEL=YOUR_AVAILABLE_GEMINI_MODEL
LLM_TIMEOUT_SECONDS=15

EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384
EMBEDDING_CACHE_DIR=

AUTO_MERGE_THRESHOLD=0.70
DUP_POSSIBLE_THRESHOLD=0.78
DUP_LIKELY_THRESHOLD=0.83

LOG_WINDOW_MINUTES=30
LOG_MATCH_LIMIT=5
LOG_MIN_RELEVANCE=0.30
```

Keep each variable once. Use a language-model identifier available to your account. Model names and credentials live in configuration rather than application code.

When using the optional Anthropic provider, configure `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and `CLAUDE_MODEL`, and install its optional SDK:

```powershell
.\.venv\Scripts\python.exe -m pip install anthropic
```

### 3. Initialise a new Supabase database

For a **fresh database**, run these files individually in Supabase SQL Editor, in this order:

| Order | Migration | Purpose |
| --- | --- | --- |
| 1 | `sql/schema.sql` | Base schema and vector support. |
| 2 | `sql/slice4.sql` | AI quality data. |
| 3 | `sql/slice5.sql` | 384-dimensional embeddings and duplicate matching. |
| 4 | `sql/consolidated_reports.sql` | Stored combined reports. |
| 5 | `sql/log_evidence.sql` | Occurrence timestamps and stored log evidence. |
| 6 | `sql/detail_requests.sql` | Manager questions, tester replies and source revisions. |
| 7 | `sql/developer_handoff.sql` | Technical drafts, approved tickets and handover states. |
| 8 | `sql/tester_updates.sql` | Tester update history and completion decisions. |

For an existing project, apply only migrations that have not already been installed. Do not rerun the base schema as a reset. In particular, `slice5.sql` changes the embedding column and deliberately aborts if embeddings are already present.

Available read-only checks:

- `sql/slice5_check.sql`
- `sql/developer_handoff_check.sql`
- `sql/tester_updates_check.sql`

Review the results and any migration error before continuing. The check files are not substitutes for the migrations.

### 4. Seed demo profiles and check connectivity

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_profiles
.\.venv\Scripts\python.exe -m app.db
```

The application uses shared demo tester and manager profiles. Developer is an additional browser view and does not require a separate developer profile seed.

### 5. Start the application

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- Application: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Manager: [http://127.0.0.1:8000/static/manager.html](http://127.0.0.1:8000/static/manager.html)
- Developer: [http://127.0.0.1:8000/static/developer.html](http://127.0.0.1:8000/static/developer.html)
- API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

Use the header to switch between Tester, Manager and Developer. After frontend changes, refresh with Ctrl+F5. Restart the server after changing `.env`.

## Duplicate matching and calibration

Duplicate matching operates within the same category for Bug and Awkward reports. Suggestion and Extra submissions skip this duplicate-checking path.

With `AUTO_MERGE_THRESHOLD=0.70`, scores **strictly above** 0.70 are eligible for automatic grouping. Exactly 0.70 is not above the threshold. Leave this setting blank to retain the earlier possible/likely rules controlled by `DUP_POSSIBLE_THRESHOLD` and `DUP_LIKELY_THRESHOLD`.

The example 0.78/0.83 thresholds were starting points from eight fake reports, not a reliable boundary between all duplicate and unrelated problems. Related and unrelated text can receive high scores. Grouping does not constitute approval to create a developer ticket.

Run the embedding calibration with the actual local model:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_embeddings
```

The first run downloads the model and can take longer. The expected vector length is 384. Keep the model, configured dimension and database vector column consistent. Changing the embedding model requires recalibration and consideration of existing stored vectors.

## Mock CloudWatch evidence

`app/data/logs.json` contains 40 fake events for **11 November 2026, 12:45:00–13:14:15 UTC**. This fixed session makes demonstrations reproducible. No AWS credentials are required.

For each report, the matcher searches WARN/ERROR events within 30 minutes before or after its occurrence time. If the occurrence time is blank, submission time is used. The browser accepts local time and sends a timestamp with timezone information. Matching considers each report's individual window, not the entire gap between reports.

Events are ranked using shared terms, explicitly related concepts and time proximity. Each match retains its raw timestamp, service, level, error code and message, together with its related source reports.

If no events match, the interface displays exactly:

> No supporting logs found

This does not mean the reported issue is invalid. Wording, layout and usability problems may never produce an error event.

Evidence refreshes with the combined detailed report and is available to technical drafting. `load_log_entries(start_time, end_time)` is the retrieval boundary for a future CloudWatch Logs Insights or boto3 integration.

For the demo session, use an export-hang report with occurrence time **11 November 2026, 13:00 UTC**, converted to the browser's local timezone if necessary. Reports submitted on another date will not match this fixed dataset unless an appropriate occurrence time is supplied.

## Review and lifecycle rules

### Requests for detail

Requests apply to individual tester reports. AI quality assessments do not automatically move reports into Needs more detail. A manager prepares and edits a question, then explicitly sends it. Draft questions stay manager-side; sent questions appear on the tester homepage.

The tester's reply is appended to request history. It does not overwrite the original submission or initial AI follow-up. Saving a reply refreshes its quality assessment and combined report, including for single-report issues. AI or evidence failure does not undo the saved reply. The report returns to review; further questions require another manager action.

Only one draft/pending request is allowed per report. Answer or cancel open requests before forwarding or closing an issue.

### Approval and development

Managers review the technical draft, priority and selected log events before clicking **Approve and forward**. Approval uses the current editor contents, including edits not separately saved with Save draft.

Forwarded issues leave the active review queue. Developers update their approved ticket's status. Ready for retest requests another check; it does not automatically complete the issue.

If source reports change or a new report joins a forwarded issue, it returns to manager review and the active developer ticket is withdrawn. Regenerate the draft when its sources have changed, then review and approve it again. Reapproval updates the existing ticket and starts it at To do. AI quality metadata changes alone do not withdraw a ticket.

### Tester updates and closure

Forwarding and developer status changes create friendly updates automatically. Managers can send edited messages for the current status. Untouched reports awaiting their first review do not populate the tester updates panel.

The panel shows the latest update for up to 20 issues, with only the selected tester's original report titles. Multiple reports from that tester in one issue share a card. Earlier update history remains stored. Updates appear on refresh; the prototype does not send email or push notifications.

To complete an issue, the developer ticket must be Ready for retest and the manager must confirm that the fix was checked. **Not taking forward** requires an explanation. Both decisions move the issue to Closed and withdraw its active developer ticket, while preserving reports and evidence.

Managers can reopen closed issues with an editable message. New or changed source feedback also reopens closed decisions for review. Reopening does not automatically publish a developer ticket.

## Testing

Run the offline suites from the project root:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_ai
.\.venv\Scripts\python.exe -m scripts.test_duplicates
.\.venv\Scripts\python.exe -m scripts.test_consolidated
.\.venv\Scripts\python.exe -m scripts.test_logs
.\.venv\Scripts\python.exe -m scripts.test_detail_requests
.\.venv\Scripts\python.exe -m scripts.test_handoff
.\.venv\Scripts\python.exe -m scripts.test_tester_updates
```

| Suite | Expected cases |
| --- | ---: |
| AI quality | 9 |
| Duplicate handling | 28 |
| Combined reports | 17 |
| Mock log matching | 25 |
| Manager detail requests | 25 |
| Developer handover | 26 |
| Tester updates | 16 |
| **Total** | **146** |

Offline suites substitute database operations and external model responses. They cover failure handling, validation and workflow behaviour, but do not prove that the real Supabase RPCs, database triggers, provider configuration or browser layout work correctly.

Additional checks:

```powershell
# Downloads/uses the real embedding model and prints calibration results.
.\.venv\Scripts\python.exe -m scripts.test_embeddings

# Makes real AI-provider requests with fake report content.
.\.venv\Scripts\python.exe -m scripts.test_ai --live

# Asks the real language model to explain fake duplicate pairs.
.\.venv\Scripts\python.exe -m scripts.test_duplicates --live
```

Live AI checks make provider requests; they do not replace a database integration check. Seed scripts write test data. Use the demo database and fake content. Verify the browser round trip after migrations, including nested report responses, approval, automatic tester updates and reopening.

## Suggested end-to-end demonstration

1. Submit a vague report as Tester and answer its clarification question.
2. Submit a differently worded report for the same issue and inspect grouping, similarity and source reports as Manager.
3. Request more detail from one report, edit the suggested question, then answer it from the tester homepage.
4. Generate or refresh the combined report and inspect its mock log evidence. Use the fixed occurrence time above when demonstrating log matches.
5. Prepare a technical draft, edit it, deselect unrelated log events and approve the issue individually.
6. Switch to Developer and update the status to In progress, then Ready for retest.
7. Refresh the tester panel to show the feedback loop. After checking the fix, complete it as Manager and show the completed message.
8. Briefly demonstrate Not taking forward with a respectful explanation and reopening from Closed.

Optional fake seed reports can be previewed before insertion:

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_duplicates_demo --dry-run
.\.venv\Scripts\python.exe -m scripts.seed_duplicates_demo
```

Run the server first for insertion. The seed creates fake submissions through the API; rerunning adds more reports. Its reports use the shared demo tester, so counts describe submissions rather than unique people. Different phrasings are not guaranteed to form one group.

## Repository layout

| Path | Contents |
| --- | --- |
| `app/main.py` | FastAPI application, route registration and static serving. |
| `app/config.py` | Server-side environment configuration. |
| `app/models.py` | Request and response validation models. |
| `app/routers/` | Report, issue, clarification, handover and tester-update APIs. |
| `app/services/` | AI calls, embeddings, duplicates, synthesis and evidence logic. |
| `app/data/logs.json` | Fake log events for the demonstration. |
| `static/` | Pages, JavaScript modules and stylesheet. |
| `scripts/` | Demo seeds, calibration and tests. |
| `sql/` | Ordered database migrations and verification queries. |
| `.env.example` | Configuration template containing no real credentials. |
| `requirements.txt` | Python dependencies. |

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing Python package | Install requirements using `.\.venv\Scripts\python.exe` and run the app with the same interpreter. |
| Missing demo profile | Run `scripts.seed_profiles` against the configured database. |
| AI check unavailable | Verify provider, key, model and timeout settings; check backend output. Reports should still be saved. |
| Embedding model unavailable | Run `scripts.test_embeddings`; check `fastembed`, model download access, cache and configured vector dimension. |
| No supporting logs | Check occurrence time and the fixed mock session. A no-match result is valid. |
| Missing table/function/column | Check that the required migrations were applied in order to the project configured in `.env`. |
| Cannot forward or close | Answer or cancel open detail requests. Regenerate a stale draft before approval. Completion also requires Ready for retest and manager confirmation. |
| Old branding or layout | Confirm files were saved and hard-refresh with Ctrl+F5. |

## Prototype scope

This is a hackathon demonstration using **fake data only**. Do not submit patient information, confidential company material or real credentials as report content. Review provider data-handling terms before using external AI with other data.

The browser role switch changes views; it is not authentication or authorisation. Shared demo profiles are used, and selecting a tester ID is not proof of identity. A deployed app would need authenticated ownership, access controls and an appropriate data-handling design.

CloudWatch evidence is mocked. Developer handover stays inside this application; it does not create GitHub or Jira tickets, deploy fixes or run automated retests. AI-generated confidence and explanations can be wrong. The low automatic-grouping threshold is a demo configuration, and grouping requires manager scrutiny before approval.
