"""Reviewed handover to the demo developer queue."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.config import DEMO_MANAGER_ID, DEMO_TESTER_ID
from app.db import get_supabase
from app.models import DeveloperStatusUpdate, TechnicalDraftUpdate
from app.routers.reports import make_title
from app.services.handoff import generate_content, prepare_context, validate_selected_logs

router = APIRouter(prefix="/api", tags=["developer handover"])
log = logging.getLogger("uat.handoff.router")

MESSAGES = {
    "not_found": (404, "This issue or ticket could not be found."),
    "no_draft": (409, "Generate a technical draft before forwarding."),
    "forwarded": (409, "This issue is already forwarded. Reopen it before editing."),
    "sources_changed": (409, "The reports have changed. Regenerate the draft and review it before approval."),
    "revision_changed": (409, "This draft or ticket changed in another view. Refresh and try again."),
    "open_requests": (409, "Answer or cancel open requests for more detail before forwarding."),
    "withdrawn": (409, "This ticket has returned to manager review. Refresh the developer queue."),
    "invalid_content": (422, "Check the title, summary, priority and selected log evidence."),
}


def checked_result(result):
    status = result.get("status") if isinstance(result, dict) else None
    if status in ("saved", "reopened") or (status == "forwarded" and result.get("ticket_id")):
        return result
    code, message = MESSAGES.get(status, (502, "Could not complete this action. Refresh and try again."))
    raise HTTPException(status_code=code, detail=message)


def load_draft(db, issue_id: str) -> dict | None:
    rows = db.table("technical_drafts").select("*").eq("issue_id", issue_id).limit(1).execute().data
    return rows[0] if rows else None


def stored_content(db, issue_id: str, payload: TechnicalDraftUpdate) -> dict:
    draft = load_draft(db, issue_id)
    if draft is None:
        raise HTTPException(status_code=409, detail=MESSAGES["no_draft"][1])
    content = payload.content.model_dump()
    try:
        validate_selected_logs(content, draft["source_snapshot"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return content


@router.get("/issues/{issue_id}/technical-draft")
def get_technical_draft(issue_id: UUID):
    try:
        db = get_supabase()
        issue, current = prepare_context(db, str(issue_id))
        if issue is None:
            raise HTTPException(status_code=404, detail=MESSAGES["not_found"][1])
        draft = load_draft(db, str(issue_id))
        return {"draft": draft,
            "source_is_current": bool(draft and draft["source_snapshot"]["reports"] == current["reports"]),
            "open_detail_requests": current["open_detail_requests"],
            "handoff_status": issue.get("handoff_status", "review")}
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not load technical draft: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not load the technical draft.") from exc


@router.post("/issues/{issue_id}/technical-draft")
def generate_technical_draft(issue_id: UUID):
    try:
        db = get_supabase()
        issue, context = prepare_context(db, str(issue_id))
        if issue is None:
            raise HTTPException(status_code=404, detail=MESSAGES["not_found"][1])
        if issue.get("handoff_status") == "forwarded":
            raise HTTPException(status_code=409, detail=MESSAGES["forwarded"][1])
        if not context["reports"]:
            raise HTTPException(status_code=409, detail="There are no source reports to draft from.")
        content, generation_status = generate_content(issue, context)
        result = checked_result(db.rpc("store_technical_draft", {
            "p_issue_id": str(issue_id), "p_context": context,
            "p_content": content, "p_generation_status": generation_status,
        }).execute().data)
        return {"draft": result["draft"], "source_is_current": True,
            "open_detail_requests": context["open_detail_requests"], "handoff_status": "review"}
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not generate technical draft: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not save the technical draft. Please try again.") from exc


@router.put("/issues/{issue_id}/technical-draft")
def save_technical_draft(issue_id: UUID, payload: TechnicalDraftUpdate):
    try:
        db = get_supabase()
        content = stored_content(db, str(issue_id), payload)
        return checked_result(db.rpc("save_technical_draft", {
            "p_issue_id": str(issue_id), "p_expected_revision": payload.expected_revision, "p_content": content,
        }).execute().data)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not save technical draft: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not save your draft changes.") from exc


@router.post("/issues/{issue_id}/approve-handoff", status_code=201)
def approve_handoff(issue_id: UUID, payload: TechnicalDraftUpdate):
    try:
        db = get_supabase()
        content = stored_content(db, str(issue_id), payload)
        return checked_result(db.rpc("approve_technical_handoff", {
            "p_issue_id": str(issue_id), "p_expected_revision": payload.expected_revision,
            "p_content": content, "p_manager_id": DEMO_MANAGER_ID,
        }).execute().data)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not approve technical handover: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not forward this issue. Your approval was not completed.") from exc


@router.post("/issues/{issue_id}/reopen-handoff")
def reopen_handoff(issue_id: UUID):
    try:
        return checked_result(get_supabase().rpc("reopen_technical_handoff", {"p_issue_id": str(issue_id)}).execute().data)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not reopen technical handover: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reopen this issue.") from exc


@router.get("/developer/tickets")
def list_developer_tickets():
    try:
        db = get_supabase()
        result = []
        offset = 0
        while True:
            rows = db.table("developer_tickets").select(
                "id, issue_id, content, source_snapshot, status, revision, approved_at, updated_at, issues!inner(handoff_status)"
            ).eq("active", True).eq("issues.handoff_status", "forwarded").order(
                "approved_at", desc=True
            ).order("id").range(offset, offset + 499).execute().data or []
            for row in rows:
                result.append({key: value for key, value in row.items() if key not in ("issues", "source_snapshot")} |
                    {"source_report_count": len(row["source_snapshot"].get("reports", []))})
            if len(rows) < 500:
                return result
            offset += 500
    except Exception as exc:
        log.warning("Could not load developer queue: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not load the developer tickets.") from exc


@router.patch("/developer/tickets/{ticket_id}/status")
def update_ticket_status(ticket_id: UUID, payload: DeveloperStatusUpdate):
    try:
        return checked_result(get_supabase().rpc("update_developer_ticket_status", {
            "p_ticket_id": str(ticket_id), "p_expected_revision": payload.expected_revision, "p_status": payload.status,
        }).execute().data)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not update developer status: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not save the ticket status.") from exc


@router.get("/tester/report-status")
def tester_report_status(tester_id: UUID = UUID(DEMO_TESTER_ID)):
    try:
        rows = []
        offset = 0
        db = get_supabase()
        while True:
            page = db.table("reports").select(
                "id, tester_id, category, answers, created_at, detail_requests(status), "
                "issues(handoff_status, developer_tickets(status, active))"
            ).order("created_at", desc=True).order("id").range(offset, offset + 499).execute().data or []
            rows.extend(page)
            if len(page) < 500:
                break
            offset += 500
        result = []
        for row in rows:
            if str(row.get("tester_id") or DEMO_TESTER_ID) != str(tester_id):
                continue
            issue = row.get("issues") or {}
            ticket = issue.get("developer_tickets") or {}
            if isinstance(ticket, list):
                ticket = ticket[0] if ticket else {}
            state = "manager_review"
            if issue.get("handoff_status") == "forwarded" and ticket.get("active"):
                state = {"todo": "forwarded", "in_progress": "in_progress", "ready_for_retest": "ready_for_retest"}.get(
                    ticket.get("status"), "forwarded")
            elif any(request.get("status") == "pending" for request in row.get("detail_requests", [])):
                state = "needs_detail"
            answers = row.get("answers") or {}
            result.append({"report_id": row["id"], "category": row["category"],
                "title": make_title(row["category"], answers) if answers else "Your report",
                "created_at": row["created_at"], "status": state})
        result.sort(key=lambda row: (row["status"] in ("forwarded", "in_progress", "ready_for_retest"), row["created_at"]), reverse=True)
        return result[:20]
    except Exception as exc:
        log.warning("Could not load tester report status: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not load your report progress.") from exc
