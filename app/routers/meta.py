import logging

from fastapi import APIRouter, HTTPException

from app.db import get_supabase
from app.form_config import FORMS

router = APIRouter(prefix="/api", tags=["meta"])
log = logging.getLogger("uat.meta")


@router.get("/forms")
def get_forms():
    """The guided form definitions, so the frontend can render them."""
    return FORMS


@router.get("/profiles")
def list_profiles():
    """Demo profiles. The role switch uses these to know who is who."""
    try:
        result = get_supabase().table("profiles").select("id, name, role").execute()
    except Exception:
        log.exception("Could not load profiles")
        raise HTTPException(status_code=502, detail="We couldn't load the demo profiles.")
    return result.data
