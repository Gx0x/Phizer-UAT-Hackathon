"""Demo manager/tester workflow. Browser role switching is not authentication."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.config import DEMO_MANAGER_ID, DEMO_TESTER_ID
from app.db import get_supabase
from app.models import DetailRequestAnswer, DetailRequestSend
from app.services.consolidated import refresh_consolidated_report
from app.services.detail_requests import (
    REQUEST_FIELDS, get_history, get_report, refresh_quality, suggest_question,
)

router = APIRouter(prefix="/api", tags=["detail requests"])
log = logging.getLogger("uat.detail_requests.router")


def load_request(db, request_id: str) -> dict:
    rows = db.table("detail_requests").select(REQUEST_FIELDS).eq("id", request_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="This request could not be found.")
    return rows[0]


@router.post("/reports/{report_id}/detail-request", status_code=201)
def mark_needs_detail(report_id: UUID):
    db = get_supabase()
    try:
        report = get_report(db, str(report_id))
        if report is None:
            raise HTTPException(status_code=404, detail="This report could not be found.")
        issues = db.table("issues").select("handoff_status").eq("id", report["issue_id"]).limit(1).execute().data
        if issues and issues[0].get("handoff_status") == "forwarded":
            raise HTTPException(status_code=409, detail="Reopen this issue before requesting more detail.")
        history = get_history(db, str(report_id))
        active = next((item for item in history if item["status"] in ("draft", "pending")), None)
        if active:
            return active
        question, suggestion_status = suggest_question(report, history)
        try:
            rows = db.table("detail_requests").insert({
                "report_id": str(report_id), "manager_id": DEMO_MANAGER_ID,
                "status": "draft", "question": question, "suggestion_status": suggestion_status,
            }).execute().data
        except Exception:
            # A concurrent click may have created the same active request.
            existing = get_history(db, str(report_id))
            active = next((item for item in existing if item["status"] in ("draft", "pending")), None)
            if active:
                return active
            raise
        if not rows:
            raise RuntimeError("No request row returned")
        return rows[0]
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not mark report for detail: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not move this report. Refresh and try again.") from exc


@router.post("/detail-requests/{request_id}/send")
def send_request(request_id: UUID, payload: DetailRequestSend):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Write a question before sending.")
    try:
        db = get_supabase()
        request = load_request(db, str(request_id))
        if request["status"] != "draft":
            raise HTTPException(status_code=409, detail="This request has already been sent or closed. Refresh the queue.")
        rows = db.table("detail_requests").update({
            "question": question, "status": "pending", "sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", str(request_id)).eq("status", "draft").execute().data
        if not rows:
            raise HTTPException(status_code=409, detail="This request changed. Refresh the queue.")
        return {"status": "pending", "message": "Question sent to the tester home page."}
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not send detail request: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not send the question. Please try again.") from exc


@router.post("/detail-requests/{request_id}/cancel")
def cancel_request(request_id: UUID):
    try:
        db = get_supabase()
        request = load_request(db, str(request_id))
        if request["status"] not in ("draft", "pending"):
            raise HTTPException(status_code=409, detail="This request is already closed. Refresh the queue.")
        rows = db.table("detail_requests").update({"status": "cancelled"}).eq(
            "id", str(request_id)
        ).eq("status", request["status"]).execute().data
        if not rows:
            raise HTTPException(status_code=409, detail="This request changed. Refresh the queue.")
        return {"status": "cancelled", "message": "Report returned to the review queue."}
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not cancel detail request: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not return the report. Please try again.") from exc


@router.get("/detail-requests")
def tester_requests(tester_id: UUID = UUID(DEMO_TESTER_ID)):
    """Only sent requests for the selected demo tester profile are returned."""
    try:
        db = get_supabase()
        visible = []
        offset = 0
        while True:
            rows = db.table("detail_requests").select(
                REQUEST_FIELDS + ", reports!inner(id, tester_id, category, answers)"
            ).eq("status", "pending").order("created_at").range(offset, offset + 499).execute().data or []
            for request in rows:
                report = request.get("reports") or {}
                if str(report.get("tester_id") or DEMO_TESTER_ID) == str(tester_id):
                    visible.append(request)
            if len(rows) < 500:
                break
            offset += 500
        return visible
    except Exception as exc:
        log.warning("Could not load tester requests: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not load requests for more detail. Please try again.") from exc


@router.post("/detail-requests/{request_id}/answer")
def answer_request(request_id: UUID, payload: DetailRequestAnswer):
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(status_code=422, detail="Add some detail before sending your answer.")
    try:
        db = get_supabase()
        result = db.rpc("answer_detail_request", {
            "request_id": str(request_id), "respondent": str(payload.tester_id), "new_answer": answer,
        }).execute().data
        status = result.get("status") if isinstance(result, dict) else None
        if status == "not_found":
            raise HTTPException(status_code=404, detail="This request could not be found.")
        if status == "not_owner":
            raise HTTPException(status_code=403, detail="This request belongs to a different tester profile.")
        if status == "invalid_answer":
            raise HTTPException(status_code=422, detail="Add some detail before sending your answer.")
        if status in ("not_pending", "already_answered"):
            raise HTTPException(status_code=409, detail="This request is already closed. Refresh your requests.")
        if status != "saved":
            raise RuntimeError("Unexpected answer result")
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not save detail reply: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not save your answer. Please try again.") from exc
    # The reply is already durable. AI failures cannot turn it into a failed submission.
    refresh_quality(db, result["report_id"])
    if result.get("issue_id"):
        refresh_consolidated_report(db, result["issue_id"], allow_single=True)
    return {"status": "saved", "message": "Thanks. Your answer has been returned to the manager."}
