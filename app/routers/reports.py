import logging

from fastapi import APIRouter, HTTPException

from app.config import DEMO_TESTER_ID
from app.db import get_supabase
from app.form_config import FORMS
from app.models import ReportCreate

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
    """Save a report and create its issue.

    Slice 3 has no AI and no duplicate detection, so every report becomes its
    own issue with report_count = 1. Slice 5 will group similar reports.
    """
    db = get_supabase()
    tester_id = str(payload.tester_id) if payload.tester_id else DEMO_TESTER_ID

    try:
        issue = (
            db.table("issues")
            .insert(
                {
                    "title": make_title(payload.category, payload.answers),
                    "category": payload.category,
                    "status": "new",
                    "report_count": 1,
                }
            )
            .execute()
            .data[0]
        )
    except Exception:
        log.exception("Could not create issue")
        raise HTTPException(status_code=502, detail="We couldn't save that just now. Please try again.")

    try:
        report = (
            db.table("reports")
            .insert(
                {
                    "issue_id": issue["id"],
                    "tester_id": tester_id,
                    "category": payload.category,
                    "answers": payload.answers,
                }
            )
            .execute()
            .data[0]
        )
    except Exception:
        log.exception("Could not create report")
        # Tidy up so we never leave an issue with no report behind it.
        try:
            db.table("issues").delete().eq("id", issue["id"]).execute()
        except Exception:
            log.exception("Could not remove the orphaned issue %s", issue["id"])
        raise HTTPException(status_code=502, detail="We couldn't save that just now. Please try again.")

    return {
        "report_id": report["id"],
        "issue_id": issue["id"],
        "status": "Received",
        "message": "Thanks, we've got your report.",
    }
