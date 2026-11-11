"""Offline checks for above-threshold merging and final detailed reports.
Run python -m scripts.test_consolidated. No network, database or model download.
"""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import config
from app.services import consolidated as final, duplicates
from scripts.test_duplicates import FakeDB, FakeTable, Result, BASE, vec


CONTENT = {
    "title": "Mobile detail section cannot be edited",
    "summary": "Two reports describe being unable to type into the detail section on page 1 using a mobile device.",
    "expected_behaviour": ["The detail section should accept text."],
    "actual_behaviour": ["Typing does not add text."],
    "steps_to_reproduce": ["Report 1: Open page 1 and try typing into the detail section."],
    "affected_pages": ["Page 1, supplied in a follow-up answer."],
    "browsers_devices": ["Mobile device; browser unspecified."],
    "impact": [], "conflicts": [], "missing_information": ["Browser and operating system are unspecified."],
}


class SourceTable(FakeTable):
    def order(self, column, **kwargs):
        self.sort_column = column
        return self
    def range(self, start, end):
        self.window = (start, end)
        return self
    def limit(self, count):
        return self.range(0, count - 1)
    def is_(self, column, value):
        self.filters.append((column, None if value == "null" else value))
        return self
    def execute(self):
        result = super().execute()
        if self.op == "select":
            if hasattr(self, "sort_column"):
                result.data.sort(key=lambda row: str(row[self.sort_column]))
            if hasattr(self, "window"):
                start, end = self.window
                result.data = result.data[start:end + 1]
        return result


class SourceDB(FakeDB):
    def table(self, name):
        return SourceTable(self, name)
    def rpc(self, name, params):
        if name != "store_consolidated_report":
            return super().rpc(name, params)
        self.rpc_calls.append((name, params))
        db = self
        class Save:
            def execute(self):
                db.maybe_fail("rpc", name)
                rows = [r for r in db.tables["reports"] if r["issue_id"] == params["target_issue_id"]]
                if final.source_snapshot(rows) != params["expected_sources"]:
                    return Result(False)
                db.issue(params["target_issue_id"])["consolidated_report"] = copy.deepcopy(params["assessment"])
                return Result(True)
        return Save()


class FinalReportTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(config, AUTO_MERGE_THRESHOLD=.70,
            EMBEDDING_DIM=4, EMBEDDING_MODEL="test-model")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.db = SourceDB()
        self.issue, self.first = self.db.seed_issue("Details cannot be edited", "bug", BASE,
            answers={"actual": "Cannot type in details", "expected": "It should accept text", "browser": "mobile"})
        self.first.update(follow_up_question="Which page?", follow_up_answer="page 1")
        self.second = self.db.seed_report(self.issue["id"], "bug", vec(.80),
            answers={"actual": "Detail section does not accept text", "steps": "Try to type in details"})
        self.second.update(follow_up_question="Which page?", follow_up_answer="page 1")
        self.issue["report_count"] = 2
        self.llm = lambda system, user, **kwargs: json.dumps(CONTENT)

    def test_strict_above_seventy_boundary(self):
        for score, outcome in [(.6999,"new"),(.70,"new"),(.7001,"likely"),(.80,"likely"),(1.0,"likely")]:
            self.assertEqual(duplicates.classify(score), outcome)

    def test_new_threshold_joins_and_counts(self):
        placement = duplicates.handle_new_report(self.db, category="bug", title="Same",
            tester_id="tester", answers={"actual":"Cannot type"},
            embed=lambda text: vec(.71,axis=2), llm=lambda *args:'{"reasoning":"Both describe editing problems."}')
        self.assertEqual(placement.outcome,"likely")
        self.assertEqual(placement.issue_id,self.issue["id"])
        self.assertEqual(self.db.issue(self.issue["id"])["report_count"],3)

    def test_categories_still_isolated(self):
        check = duplicates.check_duplicates(self.db,"awkward",{"felt_wrong":"Cannot type"},embed=lambda text:BASE)
        self.assertEqual(check.outcome,"new")

    def test_snapshot_is_stable_and_keeps_followups(self):
        source = final.source_snapshot([self.second,self.first])
        self.assertEqual(source,final.source_snapshot([self.first,self.second]))
        self.assertEqual(source[0]["follow_up_answer"],"page 1")
        self.assertEqual({row["id"] for row in source},{self.first["id"],self.second["id"]})

    def test_prompt_includes_originals_followups_labels_and_source_numbers(self):
        seen=[]
        def llm(system,user):
            seen.append((system,json.loads(user)))
            return json.dumps(CONTENT)
        final.refresh_consolidated_report(self.db,self.issue["id"],llm=llm)
        self.assertEqual(len(seen),1)
        self.assertIn("Never invent",seen[0][0])
        self.assertEqual(seen[0][1]["reports"][0]["follow_up_answer"],"page 1")
        self.assertIn("actual",seen[0][1]["field_labels"])
        self.assertEqual(seen[0][1]["reports"][0]["report_number"],1)

    def test_valid_summary_stores_and_preserves_originals(self):
        originals=copy.deepcopy(self.db.tables["reports"])
        result=final.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm)
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["content"],CONTENT)
        self.assertEqual(result["report_count"],2)
        self.assertEqual(self.db.tables["reports"],originals)
        self.assertEqual(self.db.issue(self.issue["id"])["consolidated_report"],result)

    def test_bad_json_missing_fields_and_whitespace_use_fallback(self):
        for raw in ['banana','{}','[]',json.dumps({**CONTENT,"summary":"   "})]:
            with self.subTest(raw=raw):
                result=final.refresh_consolidated_report(self.db,self.issue["id"],llm=lambda *args:raw)
                self.assertEqual(result["status"],"fallback")
                self.assertIn("Cannot type",str(result["content"]))
                self.assertEqual(result["source_reports"][0]["follow_up_answer"],"page 1")

    def test_provider_failure_does_not_lose_details(self):
        def broken(*args): raise TimeoutError()
        result=final.refresh_consolidated_report(self.db,self.issue["id"],llm=broken)
        self.assertEqual(result["status"],"fallback")
        self.assertEqual(len(result["source_reports"]),2)
        self.assertIn("Try to type",str(result["content"]))

    def test_changed_sources_cannot_store_stale_output(self):
        def changing(*args):
            self.first["follow_up_answer"]="page 2"
            return json.dumps(CONTENT)
        self.assertIsNone(final.refresh_consolidated_report(self.db,self.issue["id"],llm=changing))
        self.assertNotIn("consolidated_report",self.issue)

    def test_database_store_failure_is_non_blocking(self):
        self.db.fail("rpc","store_consolidated_report")
        self.assertIsNone(final.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm))
        self.assertEqual(len(self.db.tables["reports"]),2)

    def test_single_report_skips_external_call(self):
        self.db.tables["reports"]=[self.first]
        def must_not_run(*args): raise AssertionError("Unexpected model call")
        self.assertIsNone(final.refresh_consolidated_report(self.db,self.issue["id"],llm=must_not_run))

    def test_pagination_keeps_every_report(self):
        for index in range(501):
            self.db.seed_report(self.issue["id"],"bug",BASE,answers={"actual":f"Detail {index}"})
        result=final.refresh_consolidated_report(self.db,self.issue["id"],llm=self.llm)
        self.assertEqual(result["report_count"],503)

    def test_fenced_json_is_accepted(self):
        result=final.refresh_consolidated_report(self.db,self.issue["id"],llm=lambda *args:'```json\n'+json.dumps(CONTENT)+'\n```')
        self.assertEqual(result["status"],"ok")


class RouterTests(unittest.TestCase):
    setUp = FinalReportTests.setUp

    def load_routers(self):
        # Replace only the connection module when supabase-py is unavailable.
        try:
            import app.db
        except ModuleNotFoundError:
            module=types.ModuleType("app.db")
            module.get_supabase=lambda:None
            sys.modules["app.db"]=module
        from app.routers import reports,issues
        return reports,issues

    def test_submission_generates_after_quality_is_saved(self):
        reports,_=self.load_routers()
        from app.models import ReportCreate
        with patch.object(reports,"get_supabase",return_value=self.db), \
             patch.object(duplicates.embeddings,"embed_text",return_value=BASE), \
             patch.object(duplicates,"call_llm",return_value='{"reasoning":"Same detail issue."}'), \
             patch.object(reports,"check_report_quality",return_value={"status":"unavailable"}), \
             patch.object(final,"call_llm",side_effect=self.llm):
            result=reports.create_report(ReportCreate(category="bug",answers={"actual":"Cannot edit details"}))
        self.assertEqual(result["duplicate"]["outcome"],"likely")
        self.assertEqual(self.db.issue(self.issue["id"])["consolidated_report"]["report_count"],3)
        self.assertEqual(self.db.tables["reports"][-1]["ai_quality"]["status"],"unavailable")

    def test_followup_regenerates_using_new_answer(self):
        reports,_=self.load_routers()
        from app.models import FollowUpAnswer
        self.first["follow_up_answer"]=None
        with patch.object(reports,"get_supabase",return_value=self.db),patch.object(final,"call_llm",side_effect=self.llm):
            result=reports.save_follow_up(self.first["id"],FollowUpAnswer(answer="page 1"))
        self.assertEqual(result["status"],"saved")
        sources=self.db.issue(self.issue["id"])["consolidated_report"]["source_reports"]
        self.assertEqual(next(row for row in sources if row["id"]==self.first["id"])["follow_up_answer"],"page 1")

    def test_manager_can_generate_existing_group(self):
        _,issues=self.load_routers()
        with patch.object(issues,"get_supabase",return_value=self.db),patch.object(final,"call_llm",side_effect=self.llm):
            result=issues.regenerate_consolidated_report(self.issue["id"])
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["report"]["report_count"],2)

    def test_saved_followup_survives_summary_database_failure(self):
        reports,_=self.load_routers()
        from app.models import FollowUpAnswer
        self.first["follow_up_answer"]=None
        self.db.fail("rpc","store_consolidated_report")
        with patch.object(reports,"get_supabase",return_value=self.db),patch.object(final,"call_llm",side_effect=self.llm):
            result=reports.save_follow_up(self.first["id"],FollowUpAnswer(answer="page 1"))
        self.assertEqual(result["status"],"saved")
        self.assertEqual(self.first["follow_up_answer"],"page 1")


def main():
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(FinalReportTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(RouterTests)])
    count=suite.countTestCases()
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"PASS: all {count} offline cases")
    return 0 if result.wasSuccessful() else 1

if __name__=="__main__":
    sys.exit(main())
