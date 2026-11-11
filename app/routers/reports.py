import logging

from fastapi import APIRouter, HTTPException

from app.config import DEMO_TESTER_ID
from app.db import get_supabase
from app.form_config import FORMS
from app.models import FollowUpAnswer, ReportCreate
from app.services.ai import check_report_quality, unavailable
from app.services.duplicates import PlacementError, handle_new_report

router = APIRouter(prefix="/api", tags=["reports"])
log = logging.getLogger("uat.reports")


def make_title(category: str, answers: dict[str, str]) -> str:
    """Use the first line of the most telling answer as the issue title."""
    preferred = FORMS[category]["title_field"]
    text = answers.get(preferred) or next(iter(answers.values()))
    first_line = " ".join(text.splitlines()[0].split())
    return first_line if len(first_line) <= 80 else first_line[:77].rstrip() + "..."


@router.post("/reports", status_code=201)
def create_report(payload: ReportCreate):
    """Save a report, group likely duplicates and run the optional quality check."""
    db = get_supabase()
    tester_id = str(payload.tester_id) if payload.tester_id else DEMO_TESTER_ID

    try:
        placement = handle_new_report(
            db,
            category=payload.category,
            title=make_title(payload.category, payload.answers),
            tester_id=tester_id,
            answers=payload.answers,
        )
    except PlacementError as exc:
        log.warning("Could not save report: stage=%s", exc.stage)
        raise HTTPException(
            status_code=502,
            detail="We couldn't save that just now. Please try again.",
        ) from exc

    # From here onward, AI failures cannot undo or block the saved report.
    try:
        quality = check_report_quality(payload.category, payload.answers)
        if isinstance(quality, dict):
            assessment = quality
            follow_up = None
        else:
            assessment = {"status": "ok", **quality.model_dump()}
            from app.services.ai import provider_details
            provider, model = provider_details()
            assessment.update({"provider": provider, "model": model})
            follow_up = quality.follow_up
    except Exception:
        log.exception("Unexpected AI quality failure")
        assessment = unavailable("unexpected_error")
        follow_up = None

    try:
        db.table("reports").update({
            "follow_up_question": follow_up,
            "ai_quality": assessment,
        }).eq("id", placement.report_id).execute()
    except Exception:
        log.exception("Could not store AI assessment for report %s", placement.report_id)
        # Do not offer a question if it could not be stored.
        follow_up = None

    return {
        "report_id": placement.report_id,
        "issue_id": placement.issue_id,
        "status": "Received",
        "message": "Thanks, we've got your report.",
        "follow_up": follow_up,
        "duplicate": placement.public_summary(),
    }


@router.post("/reports/{report_id}/follow-up")
def save_follow_up(report_id: str, payload: FollowUpAnswer):
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(status_code=422, detail="Type an answer, or use Skip")
    try:
        db = get_supabase()
        result = db.table("reports").select(
            "id, follow_up_question, follow_up_answer"
        ).eq("id", report_id).limit(1).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="We couldn't find that report.")
        report = result.data[0]
        if not report.get("follow_up_question"):
            raise HTTPException(status_code=409, detail="We didn't ask a question on this report")
        if report.get("follow_up_answer") is not None:
            raise HTTPException(status_code=409, detail="This question has already been answered.")
        updated = db.table("reports").update({"follow_up_answer": answer}).eq(
            "id", report_id
        ).is_("follow_up_answer", "null").execute()
        if not updated.data:
            raise HTTPException(status_code=409, detail="This question has already been answered.")
    except HTTPException:
        raise
    except Exception:
        log.exception("Could not save follow-up")
        raise HTTPException(status_code=502, detail="We couldn't save your answer just now. Please try again.")
    return {"status": "saved", "message": "Thanks, that helps."}


