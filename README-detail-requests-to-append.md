## Manager requests for more detail

Managers can move individual reports into a **Needs more detail** column by clicking
**Request more detail** inside the report details. AI quality verdicts do not move
reports automatically. Other reports belonging to the same issue remain in review.
The issue's total report count continues to include all original reports.

A draft question is suggested by AI, or reuses the original unanswered AI question.
The manager can edit it before choosing **Send to tester**. When AI is unavailable,
a fallback question remains editable. Draft requests are visible only to managers.
Sending changes a request to pending and makes it appear under **Requests for more
detail** on the tester home page. The existing demo tester profile is used.

A tester's answer is stored in `detail_requests`, leaving the original report answers
and initial follow-up fields intact. The report returns to review even if the new
quality assessment still asks for more information. A manager can request another
round manually. Every answered question remains available in report history and
in the final report's source details. A draft or pending request can be cancelled
using **Return to review queue**.

Saving the reply and advancing its revision happen in one PostgreSQL transaction.
There can be only one active draft/pending request per report. Blank replies,
answers to draft/cancelled requests and duplicate answers are rejected. AI quality
and the final detailed report are refreshed after a reply is saved, including for
single-report issues. Refreshed log matching uses the added answers when the final
report is generated. AI or evidence failures do not undo a saved reply.

The browser role switch and shared demo profiles remain a demo workflow. Profile
filtering is included, but the application does not have real user authentication.
This feature sends requests inside the application, through the tester home page.

Install `sql/detail_requests.sql` after the existing log-evidence migration. It adds
`reports.detail_revision`, creates `detail_requests`, and updates the source-snapshot
check used when storing final reports and log evidence. It preserves existing report
and issue rows. The new table uses RLS, consistent with server-side service-key access.

Append `detail-request-styles-to-append.txt` to `static/css/styles.css`. Replace the
included application and frontend files, then restart Uvicorn and reload with Ctrl+F5.
The manager board displays two columns on wider screens and stacks them on narrower
screens. Category selection and the original submission/follow-up flow are retained.

Offline commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_detail_requests
.\.venv\Scripts\python.exe -m scripts.test_consolidated
.\.venv\Scripts\python.exe -m scripts.test_logs
.\.venv\Scripts\python.exe -m scripts.test_duplicates
.\.venv\Scripts\python.exe -m scripts.test_ai
```

The first four suites expect 25, 17, 25 and 28 passing cases. The existing AI suite
expects nine. Offline tests replace database and provider calls. Run the browser
round trip against Supabase to verify the live SQL, nested API responses and AI output.
