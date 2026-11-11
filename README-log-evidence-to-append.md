## Mock CloudWatch log evidence

Bug and Awkward issues can include supporting events from `app/data/logs.json`.
The file contains 40 fake events from **11 November 2026, 12:45–13:14:15 UTC**.
It is a reproducible demo dataset. There is no AWS connection or AWS key requirement.

Testers can supply an optional occurrence time in their local timezone. The browser
sends an ISO timestamp with a timezone. With no occurrence time, matching uses the
report submission time. Existing reports continue to work with a null occurrence time.

Evidence is searched when a final detailed report is generated or refreshed. A manager
can now generate a final report for a single-report issue. Existing automatic final-report
updates for grouped reports also refresh their evidence. Once a single-report issue has
a final report, subsequent follow-up answers refresh it too.

Matching compares terms and a small, explicit vocabulary of related concepts against
WARN/ERROR events inside each report's own time window. Routine INFO events are noise.
The displayed log relevance score combines text overlap and time proximity. It is a
ranking score, not a probability or proof of the cause. Each match keeps its original
message, timestamp, service, level and error code, plus the related source report IDs.

Default settings are available without adding environment variables:

```dotenv
LOG_WINDOW_MINUTES=30
LOG_MATCH_LIMIT=5
LOG_MIN_RELEVANCE=0.30
```

No-match results display exactly `No supporting logs found`. Source failures display
an unavailable message and preserve the submitted report and final-report workflow.

Run `sql/log_evidence.sql` after installing the files. The migration adds nullable
`reports.occurred_at` and updates `store_consolidated_report`. It stores the summary
and its evidence in one transaction after comparing the current source snapshot.
The existing `log_matches` table keeps one current match record per issue, replaced
on each successful refresh. Empty or unavailable results are recorded inside the
stored final report and clear the previous current match record.

For a demo, submit an export-hang bug with occurrence time **11 November 2026 at
13:00 UTC**. Generate or refresh its final report. The issue and the final report each
show supporting logs. A wording/layout issue with no matching event shows the exact
no-match message. Search results remain tied to the specified demo session even if
you run the demo on a different date.

The final-report prompt receives the selected fake events as well as report answers
and follow-ups. AI output is labelled for review. The raw evidence is calculated and
stored separately, so it remains visible even if the external AI provider fails.
Use fake data for this demo.

Offline checks:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_logs
.\.venv\Scripts\python.exe -m scripts.test_consolidated
.\.venv\Scripts\python.exe -m scripts.test_duplicates
.\.venv\Scripts\python.exe -m scripts.test_ai
```

`load_log_entries(start_time, end_time)` is the retrieval boundary for a future boto3
or CloudWatch Logs Insights implementation. Its replacement should return the same
normalized event fields. The matching code applies individual report windows after
retrieval so gaps between report times do not become search windows.
