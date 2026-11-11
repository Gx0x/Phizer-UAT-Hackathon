"""Offline mock CloudWatch evidence checks. No network, AWS or model download."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import config
from app.models import ReportCreate
from app.services import logs, consolidated
from scripts.test_consolidated import SourceDB, CONTENT, BASE

TIME = "2026-11-11T13:00:00+00:00"


def report(text="Export download hangs", *, occurred_at=TIME, created_at=TIME, id="r1"):
    return {"id": id, "category": "bug", "answers": {"actual": text},
        "occurred_at": occurred_at, "created_at": created_at,
        "follow_up_question": None, "follow_up_answer": None}


def event(message="ExportService timeout after 30s while preparing download", *,
          at=TIME, service="ExportService", level="ERROR", code="EXPORT_TIMEOUT"):
    return dict(timestamp=at, level=level, service=service, message=message, error_code=code)


class LogMatchingTests(unittest.TestCase):
    def setUp(self):
        self.settings=patch.multiple(config, LOG_WINDOW_MINUTES=30, LOG_MATCH_LIMIT=5,
            LOG_MIN_RELEVANCE=.30)
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_sample_data_has_forty_valid_events(self):
        entries=json.loads(config.MOCK_LOGS_PATH.read_text())
        self.assertEqual(len(entries),40)
        for entry in entries:
            self.assertEqual(set(entry),{"timestamp","level","service","message","error_code"})
            logs._normalize(entry)

    def test_keywords_split_service_names_and_expand_terms(self):
        self.assertIn("export",logs.keywords("ExportService download"))
        self.assertIn("timeout",logs.keywords("The spinner kept spinning"))
        self.assertNotIn("report",logs.keywords("The report is wrong"))

    def test_occurrence_time_overrides_submission_time(self):
        result=logs.find_supporting_logs([report(created_at="2027-01-01T12:00:00Z")],"bug",entries=[event()])
        self.assertEqual(len(result["matches"]),1)
        self.assertEqual(result["time_references"][0]["basis"],"occurrence")

    def test_submission_time_is_used_when_occurrence_blank(self):
        result=logs.find_supporting_logs([report(occurred_at=None)],"bug",entries=[event()])
        self.assertEqual(len(result["matches"]),1)
        self.assertEqual(result["time_references"][0]["basis"],"submission")

    def test_timezone_offsets_are_respected(self):
        result=logs.find_supporting_logs([report(occurred_at="2026-11-11T15:00:00+02:00")],"bug",entries=[event()])
        self.assertEqual(len(result["matches"]),1)

    def test_time_window_boundaries_are_inclusive(self):
        for at in ["2026-11-11T12:30:00Z","2026-11-11T13:30:00Z"]:
            result=logs.find_supporting_logs([report()],"bug",entries=[event(at=at)])
            self.assertEqual(len(result["matches"]),1)
        result=logs.find_supporting_logs([report()],"bug",entries=[event(at="2026-11-11T13:30:01Z")])
        self.assertEqual(result["matches"],[])

    def test_matching_does_not_fill_gaps_between_report_windows(self):
        reports=[report(occurred_at="2026-11-11T10:00:00Z"),report(occurred_at="2026-11-11T16:00:00Z",id="r2")]
        result=logs.find_supporting_logs(reports,"bug",entries=[event()])
        self.assertEqual(result["matches"],[])

    def test_irrelevant_event_is_not_matched(self):
        result=logs.find_supporting_logs([report()],"bug",entries=[event("Password rejected",service="AuthService",code="AUTH_401")])
        self.assertEqual(result["message"],"No supporting logs found")
        self.assertEqual(result["matches"],[])

    def test_routine_success_is_noise(self):
        result=logs.find_supporting_logs([report()],"bug",entries=[event(level="INFO")])
        self.assertEqual(result["message"],"No supporting logs found")

    def test_generic_timeout_alone_does_not_match_another_service(self):
        result=logs.find_supporting_logs([report()],"bug",entries=[event("Database timeout",service="UnrelatedService",code="DB_TIMEOUT")])
        self.assertEqual(result["matches"],[])

    def test_awkward_is_checked_and_other_categories_are_skipped(self):
        self.assertEqual(len(logs.find_supporting_logs([report()],"awkward",entries=[event()])["matches"]),1)
        for category in ["suggestion","extra"]:
            with patch.object(logs,"load_log_entries",side_effect=AssertionError("Should not load")):
                self.assertEqual(logs.find_supporting_logs([report()],category)["status"],"skipped")

    def test_score_is_calculated_deterministically_and_has_reasoning(self):
        a=logs.find_supporting_logs([report()],"bug",entries=[event()])["matches"][0]
        b=logs.find_supporting_logs([report()],"bug",entries=[event()])["matches"][0]
        self.assertEqual(a,b)
        self.assertTrue(0 <= a["relevance_score"] <= 1)
        self.assertIn("export",a["reasoning"])
        self.assertIn("occurrence",a["reasoning"])
        self.assertEqual(a["report_ids"],["r1"])

    def test_duplicates_are_removed_and_limit_is_applied(self):
        entries=[event(),event(),event(at="2026-11-11T13:01:00Z"),event(at="2026-11-11T13:02:00Z")]
        result=logs.find_supporting_logs([report()],"bug",entries=entries,limit=2)
        self.assertEqual(len(result["matches"]),2)
        self.assertEqual(result["matches"][0]["timestamp"],TIME)

    def test_empty_logs_and_layout_feedback_use_exact_empty_message(self):
        for reports,entries in [([report()],[]),([report("The label wording is confusing")],[event()])]:
            result=logs.find_supporting_logs(reports,"bug",entries=entries)
            self.assertEqual(result["message"],"No supporting logs found")
            self.assertNotIn("unconfirmed",str(result).lower())

    def test_missing_log_file_and_bad_events_are_controlled(self):
        with patch.object(logs,"load_log_entries",side_effect=FileNotFoundError()):
            self.assertEqual(logs.find_supporting_logs([report()],"bug")["status"],"unavailable")
        for bad in [{},event(at="not a date"),event(at="2026-11-11T13:00:00")]:
            self.assertEqual(logs.find_supporting_logs([report()],"bug",entries=[bad])["status"],"unavailable")

    def test_missing_report_time_is_unavailable(self):
        result=logs.find_supporting_logs([report(occurred_at=None,created_at=None)],"bug",entries=[event()])
        self.assertEqual(result["status"],"unavailable")

    def test_followup_answer_can_add_search_terms(self):
        row=report("Something went wrong")
        row["follow_up_answer"]="The export download hangs"
        self.assertEqual(len(logs.find_supporting_logs([row],"bug",entries=[event()])["matches"]),1)

    def test_optional_input_accepts_aware_time_and_rejects_naive_time(self):
        self.assertIsNone(ReportCreate(category="bug",answers={"actual":"x"}).occurred_at)
        value=ReportCreate(category="bug",answers={"actual":"x"},occurred_at=TIME)
        self.assertEqual(value.occurred_at.hour,13)
        with self.assertRaises(ValueError):
            ReportCreate(category="bug",answers={"actual":"x"},occurred_at="2026-11-11T13:00:00")

    def test_no_model_is_used_for_log_scoring(self):
        with patch.object(consolidated,"call_llm",side_effect=AssertionError("Should not run")):
            self.assertEqual(logs.find_supporting_logs([report()],"bug",entries=[event()])["status"],"ok")


class LogIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db=SourceDB()
        self.issue,self.row=self.db.seed_issue("Export hangs","bug",BASE,answers={"actual":"Export download hangs"})
        self.row.update(created_at=TIME,occurred_at=TIME)
        self.llm=lambda *args,**kwargs:json.dumps(CONTENT)

    def test_single_report_manager_generation_includes_evidence(self):
        with patch.object(logs,"load_log_entries",return_value=[event()]):
            result=consolidated.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm,allow_single=True)
        self.assertEqual(result["report_count"],1)
        self.assertEqual(len(result["log_evidence"]["matches"]),1)
        self.assertEqual(result["source_reports"][0]["occurred_at"],TIME)

    def test_logs_are_only_searched_when_a_final_report_is_generated(self):
        with patch.object(consolidated,"find_supporting_logs",side_effect=AssertionError("Should not run")):
            self.assertIsNone(consolidated.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm))

    def test_evidence_is_passed_as_data_and_preserved_separately(self):
        seen=[]
        def llm(system,user):
            seen.append((system,json.loads(user)))
            return json.dumps(CONTENT)
        with patch.object(logs,"load_log_entries",return_value=[event()]):
            result=consolidated.refresh_consolidated_report(self.db,self.issue["id"],llm=llm,allow_single=True)
        self.assertEqual(seen[0][1]["mock_log_evidence"]["matches"][0]["log_number"],1)
        self.assertIn("do not prove",seen[0][0])
        self.assertEqual(result["log_evidence"]["matches"][0]["message"],event()["message"])

    def test_ai_failure_keeps_log_evidence(self):
        def broken(*args):raise TimeoutError()
        with patch.object(logs,"load_log_entries",return_value=[event()]):
            result=consolidated.refresh_consolidated_report(self.db,self.issue["id"],llm=broken,allow_single=True)
        self.assertEqual(result["status"],"fallback")
        self.assertEqual(result["log_evidence"]["status"],"ok")

    def test_log_failure_does_not_prevent_summary(self):
        with patch.object(logs,"load_log_entries",side_effect=FileNotFoundError()):
            result=consolidated.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm,allow_single=True)
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["log_evidence"]["status"],"unavailable")

    def test_existing_single_report_summary_is_refreshed_after_followup(self):
        self.issue["consolidated_report"]={"status":"ok"}
        self.row["follow_up_answer"]="Export page"
        with patch.object(logs,"load_log_entries",return_value=[event()]):
            result=consolidated.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm)
        self.assertEqual(result["source_reports"][0]["follow_up_answer"],"Export page")


def main():
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(LogMatchingTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(LogIntegrationTests)])
    count=suite.countTestCases()
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"PASS: all {count} offline cases")
    return 0 if result.wasSuccessful() else 1

if __name__=="__main__":
    sys.exit(main())
