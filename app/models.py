from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.form_config import FORMS

Category = Literal["bug", "awkward", "suggestion", "extra"]


class ReportCreate(BaseModel):
    """What the browser sends when a tester submits a report."""

    category: Category
    # Keys are the field keys from form_config.py. Values are free text.
    answers: dict[str, str] = Field(default_factory=dict)
    tester_id: UUID | None = None
    occurred_at: AwareDatetime | None = None

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




class DetailRequestSend(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class DetailRequestAnswer(BaseModel):
    answer: str = Field(min_length=1)
    tester_id: UUID


class TechnicalContent(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    problem_summary: str = Field(min_length=1)
    expected_behaviour: str = ""
    actual_behaviour: str = ""
    reproduction_steps: str = ""
    environment: str = ""
    log_notes: str = ""
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    included_log_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def clean_technical_content(self):
        self.title = self.title.strip()
        self.problem_summary = self.problem_summary.strip()
        if not self.title or not self.problem_summary:
            raise ValueError("Add a title and problem summary before forwarding.")
        self.included_log_ids = list(dict.fromkeys(self.included_log_ids))
        return self


class TechnicalDraftUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    content: TechnicalContent


class DeveloperStatusUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    status: Literal["todo", "in_progress", "ready_for_retest"]


class TesterFeedbackSend(BaseModel):
    action: Literal["send_update", "completed", "not_forwarded", "reopen"]
    message: str = Field(min_length=1, max_length=3000)
    reason: str = Field(default="", max_length=2000)
    checked_fix: bool = False

    @model_validator(mode="after")
    def clean_feedback(self):
        self.message = self.message.strip()
        self.reason = self.reason.strip()
        if not self.message:
            raise ValueError("Write a message for the tester.")
        if self.action == "completed" and not self.checked_fix:
            raise ValueError("Confirm that you have checked the fix before completing this issue.")
        if self.action == "not_forwarded" and not self.reason:
            raise ValueError("Explain why this report is not being taken forward.")
        return self
