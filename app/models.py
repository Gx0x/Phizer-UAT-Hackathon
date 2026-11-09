from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.form_config import FORMS

Category = Literal["bug", "awkward", "suggestion", "extra"]


class ReportCreate(BaseModel):
    """What the browser sends when a tester submits a report."""

    category: Category
    # Keys are the field keys from form_config.py. Values are free text.
    answers: dict[str, str] = Field(default_factory=dict)
    tester_id: UUID | None = None

    @model_validator(mode="after")
    def clean_answers(self):
        # Keep only known fields, trim whitespace and drop empty ones.
        # There is deliberately NO minimum or maximum length on any field.
        allowed = {field["key"] for field in FORMS[self.category]["fields"]}
        cleaned = {
            key: value.strip()
            for key, value in self.answers.items()
            if key in allowed and value and value.strip()
        }

        # The one thing we reject: a report with nothing in it at all.
        if not cleaned:
            raise ValueError("Add at least one detail so we know what you spotted.")

        self.answers = cleaned
        return self


class QualityResult(BaseModel):
    is_clear: bool
    missing: list[str]
    follow_up: str | None
    confidence: float
    reasoning: str


class FollowUpAnswer(BaseModel):
    answer: str
