"""Slice 5 demo seed: posts about a dozen FAKE reports to the running app so you
can see duplicate detection work.

Run (with Uvicorn already running) from the project root:
    .\\.venv\\Scripts\\python.exe -m scripts.seed_duplicates_demo
Options:
    --pause 6        seconds to wait between reports (the free Gemini tier rate-limits)
    --timeout 90     seconds to wait for each report (a report can take a while: it
                     runs the duplicate check, an explanation and the quality check)
    --base-url URL   default http://127.0.0.1:8000
    --dry-run        print what would be sent, without sending anything

IMPORTANT
  * This does NOT delete anything. Running it again adds another dozen reports.
    To start clean first, run this in the Supabase SQL Editor (it leaves your
    profiles alone):
        delete from public.reports;
        delete from public.issues;
  * "intended" below is only a label so YOU can read the results. The server
    never sees it, and nothing in the app uses it to decide anything.
  * The grouping you see depends on the real model and your thresholds. Read the
    results honestly: if the export reports don't all group together, the
    thresholds in .env need tuning. Don't claim a grouping you didn't get.

Standard library only. FAKE data only.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# Written the way different testers would describe things. The five "export
# hang" reports describe one problem in different words. "export dates" is a
# related but different export problem that should NOT be merged with them.
SAMPLES = [
    {"intended": "export hang", "category": "bug", "answers": {
        "expected": "A PDF of the monthly report downloads",
        "actual": "Export hangs",
        "page": "Export page"}},
    {"intended": "login", "category": "bug", "answers": {
        "actual": "I couldn't log in. After entering my password the page went back to the sign in form with no error message",
        "steps": "Typed my email and password, pressed Sign in"}},
    {"intended": "export hang", "category": "bug", "answers": {
        "actual": "The report download never finishes. I clicked Export and waited about ten minutes.",
        "steps": "Reports > Monthly > Export"}},
    {"intended": "save", "category": "bug", "answers": {
        "actual": "Clicking Save on the settings page does nothing and my changes are lost",
        "page": "Settings"}},
    {"intended": "export hang", "category": "bug", "answers": {
        "actual": "There's a spinner on the Export screen that never goes away",
        "browser": "Chrome on a work laptop"}},
    {"intended": "export dates (related, different)", "category": "bug", "answers": {
        "expected": "Dates shown as day/month/year",
        "actual": "The exported file opens fine but the dates are in the wrong format, with month and day swapped",
        "page": "Export page"}},
    {"intended": "vague", "category": "bug", "answers": {"actual": "It didn't work"}},
    {"intended": "export hang", "category": "bug", "answers": {
        "actual": "The export button just sits there loading and nothing is ever downloaded"}},
    {"intended": "awkward: tabs", "category": "awkward", "answers": {
        "trying": "Find last month's invoices",
        "felt_wrong": "I couldn't tell which tab holds the invoices because the tab names are confusing"}},
    {"intended": "vague", "category": "bug", "answers": {"actual": "Something is wrong with the report"}},
    {"intended": "export hang", "category": "bug", "answers": {
        "actual": "Tried to export the quarterly numbers and the page froze on 'Preparing your file'",
        "page": "Export page"}},
    {"intended": "awkward: save feedback", "category": "awkward", "answers": {
        "trying": "Save my settings",
        "felt_wrong": "I wasn't sure whether the Save button had worked because nothing changes on screen"}},
]


def post(url: str, payload: dict, timeout: float):
    """Returns (http_status, parsed_body_or_None, error_text_or_None)."""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = ""
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        return error.code, None, str(detail) or error.reason
    except urllib.error.URLError as error:
        return None, None, f"could not connect ({error.reason})"
    except TimeoutError:
        return None, None, f"no reply within {timeout:.0f}s"
    except Exception as error:  # a malformed body, a dropped connection...
        return None, None, f"{type(error).__name__}"


def short(value) -> str:
    return str(value)[:8] if value else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description="Post fake reports to demo duplicate detection.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--pause", type=float, default=6.0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    url = args.base_url.rstrip("/") + "/api/reports"

    if args.dry_run:
        for number, sample in enumerate(SAMPLES, 1):
            print(f"{number:>2}. [{sample['category']}] {sample['intended']}: {json.dumps(sample['answers'])}")
        print(f"\nDry run: would post {len(SAMPLES)} reports to {url}. Nothing was sent.")
        return 0

    print(f"Posting {len(SAMPLES)} FAKE reports to {url}")
    print(f"Pausing {args.pause:g}s between reports, waiting up to {args.timeout:g}s for each.\n")
    print(f"{'#':>2}  {'intended':<34} {'HTTP':<5} {'duplicate outcome':<18} {'others':<7} {'issue':<9} report")

    results, problems = [], 0
    for number, sample in enumerate(SAMPLES, 1):
        payload = {"category": sample["category"], "answers": sample["answers"]}
        status, body, error = post(url, payload, args.timeout)

        if body is not None:
            info = body.get("duplicate") or {}
            outcome = info.get("outcome") or "(none)"
            others = info.get("others_noticed")
            print(f"{number:>2}  {sample['intended']:<34} {status:<5} {outcome:<18} "
                  f"{'-' if others is None else others:<7} {short(body.get('issue_id')):<9} {short(body.get('report_id'))}")
            results.append((sample["intended"], body.get("issue_id"), outcome))
        else:
            problems += 1
            print(f"{number:>2}  {sample['intended']:<34} {status or 'ERR':<5} FAILED: {error}")
            if number == 1 and status is None:
                print("\nThe first request could not reach the app. Is Uvicorn running at "
                      f"{args.base_url}? Stopping.")
                return 1

        if number < len(SAMPLES):
            time.sleep(args.pause)

    print("\nWhere the reports ended up (reports per issue):")
    by_issue = {}
    for intended, issue_id, outcome in results:
        by_issue.setdefault(issue_id, []).append(intended)
    for issue_id, labels in sorted(by_issue.items(), key=lambda kv: -len(kv[1])):
        print(f"  issue {short(issue_id)}  {len(labels)} report(s): {', '.join(labels)}")

    counts = {}
    for _, _, outcome in results:
        counts[outcome] = counts.get(outcome, 0) + 1
    print("\nOutcomes: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if problems:
        print(f"{problems} report(s) failed to send. Re-run only if you wipe the data first, "
              "otherwise you will create duplicates of the ones that worked.")

    export_issues = {iid for intended, iid, _ in results if intended == "export hang"}
    if len(export_issues) == 1:
        print("\nAll the export-hang reports share one issue.")
    else:
        print(f"\nThe export-hang reports landed in {len(export_issues)} different issues. "
              "That is a real result, not a bug in this script: some phrasings scored below "
              "DUP_LIKELY_THRESHOLD. Check the scores in Supabase before changing anything.")
    print("Remember: every report uses the one demo tester, so 'noticed by N' counts reports, "
          "not different people.")
    return 0 if problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
