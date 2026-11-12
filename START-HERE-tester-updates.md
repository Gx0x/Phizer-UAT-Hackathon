# Friendly tester updates

This update builds on the developer handover ZIP already installed. It adds a side panel on the tester homepage, editable manager messages and a Closed manager view. It preserves reporting, detail requests, developer tickets, mock logs and consolidated reports.

## Installation

1. Stop Uvicorn with Ctrl+C. Keep a GitHub checkpoint of the version currently working on your computer.
2. Extract this ZIP into the project root, replacing the included files. These are complete files based on the latest developer handover version in this conversation. The homepage includes the fix for the stray `null` and replaces the removed long progress list with the new side panel.
3. Run **sql/tester_updates.sql** in Supabase SQL Editor. The earlier **developer_handoff.sql** and detail-request migrations must already be installed. This transaction adds `issues.tester_resolution`, an update-history table, functions and triggers. It does not delete reports or change existing report answers.
4. Run **sql/tester_updates_check.sql**. Expect the new issue column and update-history table. Issue and report counts should remain unchanged. Existing active developer tickets receive one update representing their current status; untouched reports awaiting first review receive none.
5. Append **tester-updates-styles-to-append.txt** to the bottom of **static/css/styles.css**, once. Keep all earlier CSS blocks. This provides the desktop side panel and a single-column mobile layout.
6. Run the checks from your project root in PowerShell.

```powershell
.\.venv\Scripts\python.exe -m scripts.test_tester_updates
.\.venv\Scripts\python.exe -m scripts.test_handoff
.\.venv\Scripts\python.exe -m scripts.test_detail_requests
.\.venv\Scripts\python.exe -m scripts.test_consolidated
.\.venv\Scripts\python.exe -m scripts.test_logs
.\.venv\Scripts\python.exe -m scripts.test_duplicates
.\.venv\Scripts\python.exe -m scripts.test_ai
```

Expected offline counts are 16, 26, 25, 17, 25, 28 and your existing nine AI cases. No new AI setting or application package is required. The new tests use FastAPI's TestClient and the `httpx` dependency already used by Supabase.

7. Start the server again and press Ctrl+F5 in the browser.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## First demo flow

1. Switch to **Tester**. The right-hand **Updates on your reports** panel shows only reviewed or development-updated issues, newest update first. If none exist, it shows a thank-you message. The panel moves below the reporting area on narrow screens. Requests for more detail remain in the main area.
2. Switch to **Manager**. On an issue, expand **Update testers / close issue**, then click **Prepare tester update**. Review and edit the suggested message, then click **Send update to testers**. Preparing or editing the message does not publish anything.
3. Switch to Tester and click **Refresh updates**. That issue should now appear as **Under review**, with the manager's message and the update date. Unreviewed reports stay out of the panel.
4. Approve and forward an issue using the existing handover flow. Refresh the tester panel to see **Forwarded to development**. Switch to Developer, change it to **In progress**, save, then refresh the tester panel to see **In development**.
5. Change the developer ticket to **Ready for retest**. This displays a friendly request to check the change. It does not mark the issue completed.
6. After checking the fix, the manager opens the tester-update form and chooses **Complete after checking the fix**. Edit the message, tick the confirmation and send. The issue moves to **Closed**, its active developer ticket is withdrawn, and the tester sees **Completed**.
7. On a different open issue, select **Not taking forward**. Edit the message and write the required explanation. Sending without an explanation is blocked. After sending, the issue moves to Closed and the tester sees both the message and the explanation.
8. In Manager → **Closed**, open the update form and choose **Reopen for review**. Send the suggested or edited message. The issue returns to Review. On refresh, the tester sees **Under review**. The manager must approve again before it returns to development.

Finish or cancel any draft/pending detail requests before closing an issue. The server blocks closing while those requests remain open.

## What is automatic

- Forwarding and developer status changes create friendly status updates automatically. Managers can use the message form to replace the latest displayed wording with their own message for the current status.
- Reopening a forwarded issue returns it to manager review and updates testers.
- New reports or changed source answers reopen completed/not-taking-forward issues for manager review. The original reports and prior update history are retained. AI quality metadata changes alone do not reopen an issue.
- Updates apply to the grouped issue. Each tester sees one update card containing only their own report titles, even when other testers contributed to the same group. A tester's original wording is preserved.
- The panel shows the latest update for up to 20 issues. Earlier updates remain in the database. It does not show every report or duplicate the previous long progress list.
- Nothing is emailed or pushed. Testers refresh the panel or reload the page.

## Hackathon boundaries

The existing shared demo tester profile is still in use. The API filters the selected tester's reports, but the browser role switch is not real authentication. A deployed public app would need authenticated ownership or a private report-tracking link.

Messages use editable templates and do not require an additional AI call. “Not taking forward” is a manager decision with an explanation, not an assertion that the report is invalid. Completed requires the ticket to be Ready for retest and explicit manager confirmation that the fix was checked. This update does not add an automated retest or deployment system.

## Validation

All 16 new offline API/feed tests and all 121 available existing offline tests passed. Simulated DOM checks covered the panel, empty state, safe rendering, the `null` fix, editable messages, required explanations, closing/reopening and confirmation of completion. Existing frontend regression checks passed. PostgreSQL SQL and PL/pgSQL syntax were checked with a parser.

The migration and triggers have not been run against a real Supabase/Postgres instance here. The automatic status changes, completion/reopening rules and database permissions need the first live demo flow above. Browser layout also needs checking on your machine because a real browser could not be launched in this environment. The existing nine AI tests were not available here; run your local copy using the command above.
