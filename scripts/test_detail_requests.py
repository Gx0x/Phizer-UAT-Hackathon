"""Offline manager/tester request workflow tests. No network or AI provider calls."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException

from app import config
from app.models import DetailRequestAnswer, DetailRequestSend, QualityResult
from app.services import detail_requests as service, consolidated, logs
from scripts.test_consolidated import SourceDB, SourceTable, CONTENT, BASE

NOW = "2026-11-11T13:00:00+00:00"
TESTER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000099"


class DetailTable(SourceTable):
    def execute(self):
        result = super().execute()
        for row in self.db.tables.get("detail_requests", []):
            row.setdefault("created_at", NOW)
            row.setdefault("answer", None)
            row.setdefault("sent_at", None)
            row.setdefault("answered_at", None)
        if self.op == "select" and self.name == "reports":
            for row in result.data:
                row["detail_requests"] = self.db.history(row["id"])
        if self.op == "select" and self.name == "detail_requests":
            for row in result.data:
                row["reports"] = copy.deepcopy(self.db.report(row["report_id"]))
        return result


class DetailDB(SourceDB):
    def __init__(self):
        super().__init__()
        self.tables["detail_requests"] = []
    def table(self, name):
        return DetailTable(self, name)
    def report(self, id):
        return next(row for row in self.tables["reports"] if row["id"] == id)
    def history(self, id):
        return copy.deepcopy([row for row in self.tables["detail_requests"] if row["report_id"] == id])
    def rpc(self, name, params):
        db = self
        if name == "answer_detail_request":
            class Answer:
                def execute(self):
                    db.maybe_fail("rpc", name)
                    item = next((row for row in db.tables["detail_requests"] if row["id"] == params["request_id"]), None)
                    if not item:
                        return types.SimpleNamespace(data={"status":"not_found"})
                    report = db.report(item["report_id"])
                    if (report.get("tester_id") or TESTER) != params["respondent"]:
                        status = "not_owner"
                    elif item["status"] == "answered":
                        status = "already_answered"
                    elif item["status"] != "pending":
                        status = "not_pending"
                    else:
                        item.update(status="answered", answer=params["new_answer"], answered_at=NOW)
                        report["detail_revision"] += 1
                        return types.SimpleNamespace(data={"status":"saved", "report_id":report["id"],
                            "issue_id":report["issue_id"], "detail_revision":report["detail_revision"]})
                    return types.SimpleNamespace(data={"status":status})
            return Answer()
        if name == "store_consolidated_report":
            class Store:
                def execute(self):
                    db.maybe_fail("rpc", name)
                    rows = [{**row,"detail_requests":db.history(row["id"])} for row in db.tables["reports"]
                        if row["issue_id"] == params["target_issue_id"]]
                    if consolidated.source_snapshot(rows) != params["expected_sources"]:
                        return types.SimpleNamespace(data=False)
                    db.issue(params["target_issue_id"])["consolidated_report"] = copy.deepcopy(params["assessment"])
                    return types.SimpleNamespace(data=True)
            return Store()
        return super().rpc(name, params)


class DetailRequestTests(unittest.TestCase):
    def setUp(self):
        try:
            import app.db
        except ModuleNotFoundError:
            module=types.ModuleType("app.db")
            module.get_supabase=lambda:None
            sys.modules["app.db"]=module
        from app.routers import detail_requests as router
        self.router=router
        self.db=DetailDB()
        self.issue,self.report=self.db.seed_issue("Mobile editing fails","bug",BASE,
            answers={"actual":"Cannot edit the detail section", "browser":"mobile"})
        self.report.update(tester_id=TESTER,created_at=NOW,occurred_at=None,detail_revision=0,
            follow_up_question=None,follow_up_answer=None)
        quality=QualityResult(is_clear=True,missing=[],follow_up=None,confidence=.95,
            reasoning="Page and reproduction detail are supplied.")
        patches=[patch.object(router,"get_supabase",return_value=self.db),
            patch.object(service,"call_llm",return_value='{"question":"Which page were you on?"}'),
            patch.object(service,"check_report_quality",return_value=quality),
            patch.object(consolidated,"call_llm",return_value=json.dumps(CONTENT)),
            patch.object(logs,"load_log_entries",return_value=[])]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def mark(self):
        return self.router.mark_needs_detail(UUID(self.report["id"]))
    def send(self, request, question="Which page were you on?"):
        return self.router.send_request(UUID(request["id"]),DetailRequestSend(question=question))
    def answer(self, request, answer="Page 1. Tap the details box and type text.", tester=TESTER):
        return self.router.answer_request(UUID(request["id"]),DetailRequestAnswer(answer=answer,tester_id=tester))
    def row(self, request):
        return next(item for item in self.db.tables["detail_requests"] if item["id"]==request["id"])

    def test_marking_is_manual_and_creates_an_editable_draft(self):
        self.assertEqual(self.db.tables["detail_requests"],[])
        item=self.mark()
        self.assertEqual(item["status"],"draft")
        self.assertEqual(item["question"],"Which page were you on?")
        self.assertEqual(self.report["detail_revision"],0)

    def test_draft_is_hidden_from_tester(self):
        self.mark()
        self.assertEqual(self.router.tester_requests(UUID(TESTER)),[])

    def test_repeated_mark_returns_one_active_request(self):
        a,b=self.mark(),self.mark()
        self.assertEqual(a["id"],b["id"])
        self.assertEqual(len(self.db.tables["detail_requests"]),1)

    def test_manager_can_edit_before_sending(self):
        item=self.mark()
        self.send(item,"Which screen and device did you use?")
        row=self.row(item)
        self.assertEqual(row["status"],"pending")
        self.assertEqual(row["question"],"Which screen and device did you use?")
        self.assertIsNotNone(row["sent_at"])

    def test_blank_question_is_rejected(self):
        item=self.mark()
        with self.assertRaises(HTTPException) as caught:
            self.send(item,"   ")
        self.assertEqual(caught.exception.status_code,422)
        self.assertEqual(self.row(item)["status"],"draft")

    def test_pending_question_cannot_be_rewritten_or_sent_twice(self):
        item=self.mark()
        self.send(item)
        with self.assertRaises(HTTPException) as caught:
            self.send(item,"A different question")
        self.assertEqual(caught.exception.status_code,409)

    def test_only_own_sent_requests_are_returned(self):
        item=self.mark()
        self.send(item)
        self.assertEqual(len(self.router.tester_requests(UUID(TESTER))),1)
        self.assertEqual(self.router.tester_requests(UUID(OTHER)),[])

    def test_missing_report_returns_404(self):
        with self.assertRaises(HTTPException) as caught:
            self.router.mark_needs_detail(uuid4())
        self.assertEqual(caught.exception.status_code,404)

    def test_cancel_draft_returns_it_without_sending(self):
        item=self.mark()
        self.router.cancel_request(UUID(item["id"]))
        self.assertEqual(self.row(item)["status"],"cancelled")
        self.assertEqual(self.router.tester_requests(UUID(TESTER)),[])

    def test_cancel_pending_hides_request_from_tester(self):
        item=self.mark()
        self.send(item)
        self.router.cancel_request(UUID(item["id"]))
        self.assertEqual(self.router.tester_requests(UUID(TESTER)),[])
        with self.assertRaises(HTTPException) as caught:
            self.answer(item)
        self.assertEqual(caught.exception.status_code,409)

    def test_reply_preserves_original_fields_and_counts(self):
        original=copy.deepcopy(self.report["answers"])
        item=self.mark()
        self.send(item)
        result=self.answer(item)
        self.assertEqual(result["status"],"saved")
        self.assertEqual(self.row(item)["status"],"answered")
        self.assertIn("Page 1",self.row(item)["answer"])
        self.assertEqual(self.report["answers"],original)
        self.assertEqual(self.issue["report_count"],1)
        self.assertEqual(len(self.db.tables["reports"]),1)
        self.assertEqual(self.router.tester_requests(UUID(TESTER)),[])

    def test_reply_refreshes_quality_and_final_report(self):
        item=self.mark()
        self.send(item)
        self.answer(item)
        self.assertTrue(self.report["ai_quality"]["is_clear"])
        summary=self.issue["consolidated_report"]
        self.assertEqual(summary["source_reports"][0]["manager_clarifications"][0]["answer"],self.row(item)["answer"])
        self.assertEqual(self.report["detail_revision"],1)

    def test_reply_keeps_original_followup(self):
        self.report.update(follow_up_question="Which browser?",follow_up_answer="Chrome")
        item=self.mark()
        self.send(item)
        self.answer(item)
        self.assertEqual(self.report["follow_up_question"],"Which browser?")
        self.assertEqual(self.report["follow_up_answer"],"Chrome")

    def test_duplicate_reply_does_not_append_twice(self):
        item=self.mark()
        self.send(item)
        self.answer(item)
        with self.assertRaises(HTTPException) as caught:
            self.answer(item)
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.report["detail_revision"],1)

    def test_wrong_tester_cannot_answer(self):
        item=self.mark()
        self.send(item)
        with self.assertRaises(HTTPException) as caught:
            self.answer(item,tester=OTHER)
        self.assertEqual(caught.exception.status_code,403)
        self.assertEqual(self.row(item)["status"],"pending")

    def test_draft_cannot_be_answered(self):
        item=self.mark()
        with self.assertRaises(HTTPException) as caught:
            self.answer(item)
        self.assertEqual(caught.exception.status_code,409)

    def test_blank_answer_is_rejected(self):
        item=self.mark()
        self.send(item)
        with self.assertRaises(HTTPException) as caught:
            self.answer(item,"   ")
        self.assertEqual(caught.exception.status_code,422)

    def test_answer_storage_failure_keeps_request_pending(self):
        item=self.mark()
        self.send(item)
        self.db.fail("rpc","answer_detail_request")
        with self.assertRaises(HTTPException) as caught:
            self.answer(item)
        self.assertEqual(caught.exception.status_code,502)
        self.assertEqual(self.row(item)["status"],"pending")

    def test_ai_failure_does_not_fail_a_saved_reply(self):
        item=self.mark()
        self.send(item)
        with patch.object(service,"check_report_quality",side_effect=TimeoutError()), \
             patch.object(consolidated,"call_llm",side_effect=TimeoutError()):
            self.assertEqual(self.answer(item)["status"],"saved")
        self.assertEqual(self.row(item)["status"],"answered")
        self.assertEqual(self.report["ai_quality"]["status"],"unavailable")
        self.assertEqual(self.issue["consolidated_report"]["status"],"fallback")

    def test_more_than_one_round_keeps_both_answers(self):
        first=self.mark()
        self.send(first)
        self.answer(first,"Page 1")
        second=self.mark()
        self.send(second,"Which steps did you take?")
        self.answer(second,"Tap details then type text")
        history=service.answered_clarifications(self.db.history(self.report["id"]))
        self.assertEqual(len(history),2)
        self.assertEqual({item["answer"] for item in history},{"Page 1","Tap details then type text"})
        self.assertEqual(self.report["detail_revision"],2)

    def test_quality_prompt_contains_all_supplied_details(self):
        self.report.update(follow_up_question="Browser?",follow_up_answer="Chrome")
        item=self.mark()
        self.send(item)
        with patch.object(service,"check_report_quality",wraps=service.check_report_quality) as quality:
            self.answer(item,"Page 1")
        enriched=quality.call_args.args[1]
        self.assertIn("Chrome",enriched["Additional details supplied after submission"])
        self.assertIn("Page 1",enriched["Additional details supplied after submission"])
        self.assertNotIn("Additional details supplied after submission",self.report["answers"])

    def test_question_fallback_remains_editable(self):
        with patch.object(service,"call_llm",side_effect=TimeoutError()):
            item=self.mark()
        self.assertEqual(item["suggestion_status"],"unavailable")
        self.send(item,"Please tell me which page.")
        self.assertEqual(self.row(item)["question"],"Please tell me which page.")

    def test_existing_unanswered_ai_question_is_reused(self):
        self.report["follow_up_question"]="Which page?"
        with patch.object(service,"call_llm",side_effect=AssertionError("Should not run")):
            item=self.mark()
        self.assertEqual(item["question"],"Which page?")

    def test_malformed_question_json_uses_fallback(self):
        for raw in ["banana","{}",'{"question":"  "}']:
            with patch.object(service,"call_llm",return_value=raw):
                question,status=service.suggest_question(self.report,[])
            self.assertEqual(status,"unavailable")
            self.assertTrue(question.strip())

    def test_newer_reply_revision_prevents_stale_quality_write(self):
        item=self.mark()
        self.send(item)
        def changing(category,answers):
            self.report["detail_revision"] += 1
            return QualityResult(is_clear=True,missing=[],follow_up=None,confidence=.9,reasoning="old")
        with patch.object(service,"check_report_quality",side_effect=changing):
            self.answer(item)
        self.assertNotIn("ai_quality",self.report)


def main():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(DetailRequestTests)
    count=suite.countTestCases()
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"PASS: all {count} offline cases")
    return 0 if result.wasSuccessful() else 1

if __name__=="__main__":
    sys.exit(main())
