# Developer handover

This update builds on the manager requests for more detail, mock logs and consolidated report features already installed. It adds an editable technical draft, individual manager approval, a Forwarded manager view, a Developer page and tester progress.

## Install

1. Stop Uvicorn with Ctrl+C. Keep your current GitHub commit as the checkpoint.
2. Extract this ZIP into the project root. Replace the included existing files. It does not replace `.env`, `app/config.py`, `app/services/ai.py`, `app/routers/reports.py` or the complete stylesheet. No new package or environment setting is needed.
3. In Supabase SQL Editor, run **sql/developer_handoff.sql**. It adds two tables, issue handover fields, functions and triggers in one transaction. Existing reports, replies and logs are retained. It depends on the earlier log and manager detail request migrations.
4. Run **sql/developer_handoff_check.sql**. Expect the two new tables, two issue columns and two triggers. The report and issue counts should match your counts before this installation. New technical draft and developer ticket counts should initially be zero.
5. Append **handoff-styles-to-append.txt** to the bottom of **static/css/styles.css**, once. Do not replace the stylesheet with this block.
6. Run these from the project root in PowerShell.

```powershell
.\.venv\Scripts\python.exe -m scripts.test_handoff
.\.venv\Scripts\python.exe -m scripts.test_detail_requests
.\.venv\Scripts\python.exe -m scripts.test_consolidated
.\.venv\Scripts\python.exe -m scripts.test_logs
.\.venv\Scripts\python.exe -m scripts.test_duplicates
.\.venv\Scripts\python.exe -m scripts.test_ai
```

Expected offline counts are 26, 25, 17, 25, 28 and your existing nine AI cases respectively. These are offline checks; they do not apply or verify the migration against Supabase.

7. Start the server again and refresh the browser with Ctrl+F5.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## First end-to-end check

1. Switch to **Manager**. Choose a grouped issue whose requests for more detail are all answered or cancelled.
2. Expand **Technical developer handover** and click **Prepare technical draft**. Check the combined reports and replies under **Source reports used for this draft**. Generating or saving a draft does not create a developer ticket.
3. Edit its title, summary, expected and actual behaviour, reported reproduction steps, environment, supporting log notes and suggested priority. Missing information and acceptance criteria are excluded. Select relevant raw mock log events; deselect unrelated matches such as export date formatting for a spinner issue. Log messages themselves cannot be rewritten.
4. Click **Save draft**, reload the queue, reopen the draft and confirm your edits remain.
5. Click **Approve and forward**. The issue moves from Review to **Forwarded**. Approval saves the content currently in the editor, even if you have not clicked Save draft separately.
6. Switch to **Developer**. Open **Read approved technical specification**. Confirm the edited wording and selected logs match what you approved. Update **To do → In progress → Ready for retest** using **Update status**.
7. Switch to **Tester**. Its home page has **Your report progress**. Click **Refresh progress** and confirm the status follows the developer ticket. Each original submission remains a separate tester report.
8. Switch to Manager, choose **Forwarded**, then **Reopen for manager review**. Refresh the Developer page and confirm the ticket is no longer active there. The reports remain in Review. Review and approve again to return the ticket to development, starting at To do.

## Behaviour

- Each approval forwards one grouped issue. There is no bulk approval or automatic developer ticket creation.
- Open draft or pending detail requests block approval. Answer or cancel them first. Reopen a forwarded issue before requesting more detail.
- If a new report joins a forwarded issue, or an existing report's source answers change, the issue automatically returns to manager review and its active developer ticket is withdrawn. Review the latest sources and regenerate the draft before approving again. AI quality metadata updates alone do not withdraw a ticket.
- Reopening preserves the previous technical content in the database. Reapproval updates the same ticket and starts it at To do. It does not create duplicate tickets.
- AI failure produces an editable assembled draft, labelled as a fallback. Managers can finish it manually. No unavailable AI response creates a ticket by itself.
- The approved technical ticket is a reviewed snapshot. Reports, original follow-ups and manager replies are preserved separately. Developer status changes do not alter those reports.
- The Developer role uses the existing browser demo switch. This update does not add authentication, external forwarding to GitHub/Jira, developer assignment or a retest submission workflow. Ready for retest is a visible status.
- All supporting logs remain explicitly labelled mock evidence and are investigation leads. Their relevance score is not a probability that a bug or cause is confirmed.
- Tester progress shows the latest 20 reports for the demo tester profile, with forwarded reports first. Progress changes appear on refresh.

## Validation performed here

The 26 new offline cases and 95 existing duplicate, consolidated-report, mock-log and detail-request cases passed using fake database operations and AI responses. Additional simulated DOM checks exercised manager editing/approval/reopening, blocked approval, developer status updates, tester progress, safe rendering and existing frontend behaviour. FastAPI HTTP checks exercised draft generation, approval, status validation and reopening with the same fake database.

The new SQL has not been executed against a real Postgres/Supabase instance here. Live Supabase RPCs, your Gemini configuration and the browser layout need the first end-to-end check above. Your existing nine-case AI suite is included in the commands but was not available to run here.

The main files are complete replacements for the latest version supplied in this conversation. If you have edited these files since installing the manager detail request ZIP, compare those edits before replacing them.
