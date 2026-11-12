"""Offline API/feed tests. Database RPCs are mocked; no network or AI calls."""
import copy
import sys
import types
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import DEMO_TESTER_ID
from app.models import TesterFeedbackSend

try:
    import app.db
except ModuleNotFoundError:
    module = types.ModuleType("app.db")
    module.get_supabase = lambda: None
    sys.modules["app.db"] = module

from app.routers import tester_updates as api

OTHER = "00000000-0000-0000-0000-000000000099"
NOW = "2026-11-12T11:00:00+00:00"


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.sorts = db, name, [], []
        self.window = (0, 100000)

    def select(self, *args):
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def or_(self, expression):
        self.filters.append(lambda row: row.get("tester_id") in (None, DEMO_TESTER_ID))
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def order(self, key, desc=False):
        self.sorts.append((key, desc))
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        if self.db.fail:
            raise RuntimeError("Simulated database outage")
        rows = [copy.deepcopy(row) for row in self.db.tables[self.name]
            if all(check(row) for check in self.filters)]
        for key, desc in reversed(self.sorts):
            rows.sort(key=lambda row: row[key], reverse=desc)
        start, end = self.window
        return types.SimpleNamespace(data=rows[start:end + 1])


class DB:
    def __init__(self):
        self.tables = {"reports": [], "tester_updates": []}
        self.calls, self.fail = [], False
        self.result = {"status": "saved", "update": {"id": 1}}

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        self.calls.append((name, params))
        db = self

        class Operation:
            def execute(self):
                if db.fail:
                    raise RuntimeError("Simulated RPC outage")
                return types.SimpleNamespace(data=copy.deepcopy(db.result))
        return Operation()

    def report(self, issue_id, title="My export report", owner=DEMO_TESTER_ID):
        row = dict(id=str(uuid4()), issue_id=issue_id, tester_id=owner,
            category="bug", answers={"actual": title}, created_at=NOW)
        self.tables["reports"].append(row)
        return row

    def event(self, issue_id, status="in_progress", message="Thanks for your help", reason=""):
        row = dict(id=len(self.tables["tester_updates"]) + 1, issue_id=issue_id,
            status=status, message=message, reason=reason, created_at=NOW)
        self.tables["tester_updates"].append(row)
        return row


class TesterUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        self.issue_id = str(uuid4())
        self.db.report(self.issue_id)
        patcher = patch.object(api, "get_supabase", return_value=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_untouched_reports_are_excluded(self):
        self.assertEqual(api.tester_updates(UUID(DEMO_TESTER_ID)), [])

    def test_only_own_reports_and_no_other_titles(self):
        self.db.report(self.issue_id, "PRIVATE OTHER REPORT", OTHER)
        other_issue = str(uuid4())
        self.db.report(other_issue, "ANOTHER PRIVATE TITLE", OTHER)
        self.db.event(self.issue_id)
        self.db.event(other_issue, message="PRIVATE MESSAGE")
        result = api.tester_updates(UUID(DEMO_TESTER_ID))
        self.assertEqual(len(result), 1)
        self.assertNotIn("PRIVATE", str(result))
        self.assertEqual(result[0]["reports"][0]["title"], "My export report")

    def test_grouped_reports_share_one_update_card(self):
        self.db.report(self.issue_id, "My second export wording")
        self.db.event(self.issue_id)
        result = api.tester_updates(UUID(DEMO_TESTER_ID))
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["reports"]), 2)

    def test_latest_event_wins_even_when_timestamps_match(self):
        self.db.event(self.issue_id, "in_progress")
        self.db.event(self.issue_id, "completed", "Checked and resolved")
        result = api.tester_updates(UUID(DEMO_TESTER_ID))
        self.assertEqual(result[0]["status"], "completed")
        self.assertEqual(result[0]["message"], "Checked and resolved")

    def test_explanation_reaches_tester(self):
        self.db.event(self.issue_id, "not_forwarded", "Thank you", "This relates to a feature outside this test scope.")
        result = api.tester_updates(UUID(DEMO_TESTER_ID))
        self.assertIn("outside this test scope", result[0]["reason"])

    def test_legacy_null_owner_is_demo_only(self):
        self.db.tables["reports"][0]["tester_id"] = None
        self.db.event(self.issue_id)
        self.assertEqual(len(api.tester_updates(UUID(DEMO_TESTER_ID))), 1)
        self.assertEqual(api.tester_updates(UUID(OTHER)), [])

    def test_latest_twenty_issues_newest_update_first(self):
        for number in range(22):
            parent = str(uuid4())
            self.db.report(parent, f"Report {number}")
            self.db.event(parent)
        rows = api.tester_updates(UUID(DEMO_TESTER_ID))
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]["id"], 22)

    def test_event_pagination_keeps_latest(self):
        for number in range(505):
            self.db.event(self.issue_id, message=f"Update {number}")
        self.assertEqual(api.tester_updates(UUID(DEMO_TESTER_ID))[0]["message"], "Update 504")

    def test_blank_message_rejected(self):
        with self.assertRaises(ValidationError):
            TesterFeedbackSend(action="send_update", message="   ")

    def test_not_forwarded_requires_explanation(self):
        with self.assertRaises(ValidationError):
            TesterFeedbackSend(action="not_forwarded", message="Thank you", reason="  ")

    def test_completion_requires_manager_confirmation(self):
        with self.assertRaises(ValidationError):
            TesterFeedbackSend(action="completed", message="Resolved")

    def test_manager_edits_and_confirmation_pass_to_rpc(self):
        payload = TesterFeedbackSend(action="completed", message="  Checked on mobile. Thank you.  ", checked_fix=True)
        api.send_feedback(UUID(self.issue_id), payload)
        name, params = self.db.calls[-1]
        self.assertEqual(name, "send_tester_feedback")
        self.assertEqual(params["p_message"], "Checked on mobile. Thank you.")
        self.assertTrue(params["p_checked_fix"])

    def test_options_provide_editable_templates(self):
        self.db.result = dict(status="ok", current_status="ready_for_retest", closed=False, can_complete=True)
        result = api.feedback_options(UUID(self.issue_id))
        self.assertTrue(result["can_complete"])
        self.assertIn("not_forwarded", result["suggestions"])
        self.assertNotIn("rejected", str(result["suggestions"]).lower())

    def test_rpc_errors_map_to_clear_http_errors(self):
        payload = TesterFeedbackSend(action="send_update", message="Thank you")
        for status, code in [("not_ready", 409), ("open_requests", 409), ("closed", 409),
                ("reason_required", 422), ("not_found", 404)]:
            self.db.result = {"status": status}
            with self.assertRaises(HTTPException) as exc:
                api.send_feedback(UUID(self.issue_id), payload)
            self.assertEqual(exc.exception.status_code, code)

    def test_database_failure_is_recoverable(self):
        self.db.fail = True
        with self.assertRaises(HTTPException) as exc:
            api.tester_updates(UUID(DEMO_TESTER_ID))
        self.assertEqual(exc.exception.status_code, 502)

    def test_http_request_validation_and_no_extra_tester_data(self):
        app = FastAPI()
        app.include_router(api.router)
        client = TestClient(app)
        url = f"/api/issues/{self.issue_id}/tester-feedback"
        self.assertEqual(client.post(url, json={"action": "not_forwarded", "message": "Thanks"}).status_code, 422)
        self.assertEqual(client.post(url, json={"action": "completed", "message": "Done"}).status_code, 422)
        self.assertEqual(client.post(url, json={"action": "send_update", "message": "Thanks"}).status_code, 200)
        self.assertEqual(client.get("/api/tester/updates").json(), [])


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    if result.wasSuccessful():
        print(f"PASS: all {result.testsRun} offline cases")
    sys.exit(0 if result.wasSuccessful() else 1)
