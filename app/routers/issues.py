import logging

from fastapi import APIRouter, HTTPException

from app.db import get_supabase

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
            .select("*, reports(id, answers, created_at, follow_up_question, follow_up_answer, ai_quality)")
            .order("report_count", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        log.exception("Could not load issues")
        raise HTTPException(status_code=502, detail="We couldn't load the issues just now.")
    return result.data
