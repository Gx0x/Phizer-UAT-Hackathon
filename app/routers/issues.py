import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.db import get_supabase
from app.services.consolidated import refresh_consolidated_report

router = APIRouter(prefix="/api", tags=["issues"])
log = logging.getLogger("uat.issues")


@router.get("/issues")
def list_issues():
    """The manager's review queue.

    Most-noticed issues first, then newest. Priority sorting arrives with the
    AI suggestions in a later slice. Each issue includes its tester reports.

    NOTE: there is no real authentication yet. The role switch is a demo
    convenience, so do not treat this endpoint as protected.
    """
    try:
        result = (
            get_supabase()
            .table("issues")
            .select(
                "*, reports(id, category, answers, created_at, occurred_at, follow_up_question, "
                "follow_up_answer, ai_quality, duplicate_check, detail_revision, "
                "detail_requests!detail_requests_report_id_fkey("
                "id, question, answer, status, suggestion_status, created_at, sent_at, answered_at), "
                "duplicate_matches!duplicate_matches_report_id_fkey("
                "id, confidence, reasoning, manager_decision, matched_issue_id))"
            )
            .order("report_count", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        log.exception("Could not load issues")
        raise HTTPException(status_code=502, detail="We couldn't load the issues just now.")
    return result.data




@router.post("/issues/{issue_id}/consolidated-report")
def regenerate_consolidated_report(issue_id: UUID):
    db = get_supabase()
    try:
        rows = db.table("issues").select("id").eq("id", str(issue_id)).execute().data
    except Exception as exc:
        log.warning("Could not find issue for synthesis: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not load this issue just now.") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="This issue could not be found.")
    assessment = refresh_consolidated_report(db, str(issue_id), allow_single=True)
    if assessment is None:
        return {"status": "unavailable", "message": "A final report could not be saved. The sources may have changed. Refresh and try again."}
    return {"status": assessment["status"], "report": assessment}
