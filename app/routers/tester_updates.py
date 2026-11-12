"""Friendly, issue-level updates delivered through each tester's own reports."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.config import DEMO_TESTER_ID
from app.db import get_supabase
from app.models import TesterFeedbackSend
from app.routers.reports import make_title

router = APIRouter(prefix="/api", tags=["tester updates"])
log = logging.getLogger("uat.tester_updates")

SUGGESTIONS = {
    "under_review": "Thanks for flagging this. Your report is being reviewed. We appreciate you helping us improve the app.",
    "forwarded": "Your feedback has helped identify an issue. It has been approved for the development team to work on. Thank you for reporting it.",
    "in_progress": "The development team is working on this issue. Thank you for helping us identify it.",
    "ready_for_retest": "A change is ready to check. Could you try the steps again and let the UAT manager know whether the issue still happens? Thank you for your help.",
    "completed": "The fix has been checked and this issue is now resolved. Thank you for helping us improve the app.",
    "not_forwarded": "Thank you for taking the time to share this. We are not taking this report forward at the moment. Your feedback has been kept and can be reviewed again.",
    "reopen": "We have reopened this issue for another review. Your original feedback has been kept. Thank you for helping us look into it.",
}


def pages(query_factory):
    rows, offset = [], 0
    while True:
        page = query_factory().range(offset, offset + 499).execute().data or []
        rows.extend(page)
        if len(page) < 500:
            return rows
        offset += 500


@router.get("/issues/{issue_id}/tester-feedback")
def feedback_options(issue_id: UUID):
    try:
        result = get_supabase().rpc("tester_feedback_context", {"p_issue_id": str(issue_id)}).execute().data
        if not result or result.get("status") == "not_found":
            raise HTTPException(404, "This issue could not be found.")
        return {**result, "suggestions": SUGGESTIONS}
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not prepare tester update: %s", type(exc).__name__)
        raise HTTPException(502, "Could not load the tester update options.") from exc


@router.post("/issues/{issue_id}/tester-feedback")
def send_feedback(issue_id: UUID, payload: TesterFeedbackSend):
    try:
        result = get_supabase().rpc("send_tester_feedback", {
            "p_issue_id": str(issue_id), "p_action": payload.action,
            "p_message": payload.message, "p_reason": payload.reason, "p_checked_fix": payload.checked_fix,
        }).execute().data
        state = result.get("status") if isinstance(result, dict) else None
        if state == "saved":
            return result
        errors = {
            "not_found": (404, "This issue could not be found."),
            "reason_required": (422, "Explain why this report is not being taken forward."),
            "invalid_message": (422, "Write a message for the tester."),
            "not_ready": (409, "Mark the developer ticket Ready for retest and check the fix before completing it."),
            "open_requests": (409, "Answer or cancel open requests for more detail before closing this issue."),
            "closed": (409, "Reopen this issue before sending another progress update."),
            "not_closed": (409, "This issue is already open. Refresh the queue."),
        }
        code, message = errors.get(state, (502, "Could not save the tester update."))
        raise HTTPException(code, message)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not send tester update: %s", type(exc).__name__)
        raise HTTPException(502, "Could not save the tester update. Please try again.") from exc


@router.get("/tester/updates")
def tester_updates(tester_id: UUID = UUID(DEMO_TESTER_ID)):
    try:
        db = get_supabase()
        # Filter ownership before selecting event details. Legacy null owners belong
        # to the demo profile, matching the existing detail-request workflow.
        def reports_query():
            query = db.table("reports").select("id, issue_id, tester_id, category, answers, created_at")
            if str(tester_id) == DEMO_TESTER_ID:
                query = query.or_(f"tester_id.eq.{tester_id},tester_id.is.null")
            else:
                query = query.eq("tester_id", str(tester_id))
            return query.order("created_at", desc=True).order("id")
        reports = pages(reports_query)
        owned = {}
        for report in reports:
            if str(report.get("tester_id") or DEMO_TESTER_ID) == str(tester_id) and report.get("issue_id"):
                owned.setdefault(report["issue_id"], []).append(report)
        events = []
        ids = list(owned)
        for start in range(0, len(ids), 100):
            events.extend(pages(lambda: db.table("tester_updates").select("id, issue_id, status, message, reason, created_at")
                .in_("issue_id", ids[start:start + 100]).order("id", desc=True)))
        latest = {}
        for event in sorted(events, key=lambda item: int(item["id"]), reverse=True):
            latest.setdefault(event["issue_id"], event)
        result = []
        for issue_id, event in latest.items():
            own_reports = owned[issue_id]
            result.append({"id": event["id"], "status": event["status"], "message": event["message"],
                "reason": event.get("reason"), "updated_at": event["created_at"],
                "reports": [{"id": row["id"], "title": make_title(row["category"], row.get("answers") or {})}
                    for row in own_reports]})
        return sorted(result, key=lambda item: int(item["id"]), reverse=True)[:20]
    except Exception as exc:
        log.warning("Could not load tester updates: %s", type(exc).__name__)
        raise HTTPException(502, "Could not load your report updates. Please try again.") from exc
