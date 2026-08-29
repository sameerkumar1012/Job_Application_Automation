import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CamelModel(BaseModel):
    """Base model: Python code stays snake_case, JSON on the wire stays camelCase
    to match the original domain shape exactly."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ProfileLinks(CamelModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: Optional[str] = None


class WorkExperience(CamelModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company: str
    title: str
    location: Optional[str] = None
    start_date: str = ""  # YYYY-MM
    end_date: Optional[str] = None  # YYYY-MM, empty/None = current
    current: bool = False
    description: Optional[str] = None


class Education(CamelModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    school: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None


class EeoDisclosure(CamelModel):
    gender: Optional[str] = None
    race: Optional[str] = None
    veteran_status: Optional[str] = None
    disability_status: Optional[str] = None
    want_to_self_identify: bool = False


class WorkAuthorization(CamelModel):
    authorized_to_work_in_country: bool = False
    requires_sponsorship_now: bool = False
    requires_sponsorship_future: bool = False
    country: str = ""


class Profile(CamelModel):
    full_name: str = ""
    preferred_name: Optional[str] = None
    pronouns: Optional[str] = None
    email: str = ""
    phone: Optional[str] = None
    location: Optional[str] = None
    links: ProfileLinks = Field(default_factory=ProfileLinks)

    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

    work_authorization: Optional[WorkAuthorization] = None
    eeo: Optional[EeoDisclosure] = None
    desired_salary_min: Optional[float] = None
    desired_salary_max: Optional[float] = None
    salary_currency: Optional[str] = None

    # Freeform answers to recurring questions, keyed by a normalized question
    # signature, so similar questions get consistent answers across applications.
    saved_answers: dict[str, str] = Field(default_factory=dict)

    resume_file_name: Optional[str] = None
    resume_text: Optional[str] = None
    cover_letter_file_name: Optional[str] = None
    cover_letter_text: Optional[str] = None

    updated_at: str = Field(default_factory=_now_iso)


def create_empty_profile() -> Profile:
    return Profile()


FieldConfidence = Literal["high", "medium", "low"]
FieldSource = Literal["profile", "ai-generated", "saved-answer"]


class FilledField(CamelModel):
    field_id: str
    label: str
    value: str
    confidence: FieldConfidence
    source: FieldSource
    reasoning: Optional[str] = None


class UnfilledField(CamelModel):
    field_id: str
    label: str
    reason: str


class BlockedInfo(CamelModel):
    reason: Literal["login-wall", "captcha", "unknown"]
    message: str


class FillStepResult(CamelModel):
    filled_fields: list[FilledField] = Field(default_factory=list)
    unfilled_fields: list[UnfilledField] = Field(default_factory=list)
    advanced_to_next_step: bool = False
    reached_final_step: bool = False
    click_button_id: Optional[str] = None
    blocked: Optional[BlockedInfo] = None


class ExtensionSettings(CamelModel):
    model: str = "nvidia/llama-3.1-nemotron-70b-instruct"
    auto_advance_steps: bool = True


def create_default_settings(model: str) -> ExtensionSettings:
    return ExtensionSettings(model=model, auto_advance_steps=True)


# --- Extension <-> server fill-request contract (new, not part of the original
# TS domain model, required by the background.js/content.js scan-then-fill flow) ---


class DetectedField(CamelModel):
    field_id: str
    frame_id: int = 0
    tag: str
    input_type: Optional[str] = None
    label: str = ""
    placeholder: Optional[str] = None
    name: Optional[str] = None
    id_attr: Optional[str] = None
    aria_label: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    current_value: Optional[str] = None
    is_required: bool = False


class CandidateButton(CamelModel):
    button_id: str
    frame_id: int = 0
    text: str = ""
    tag: str = ""
    type_attr: Optional[str] = None
    aria_label: Optional[str] = None


class PageSignals(CamelModel):
    url: str = ""
    title: str = ""
    visible_text_snippet: str = ""
    password_field_count: int = 0
    iframe_src_list: list[str] = Field(default_factory=list)


class JobContext(CamelModel):
    title: Optional[str] = None
    company: Optional[str] = None
    description_snippet: Optional[str] = None


class FillRequest(CamelModel):
    page: PageSignals
    fields: list[DetectedField] = Field(default_factory=list)
    buttons: list[CandidateButton] = Field(default_factory=list)
    job_context: Optional[JobContext] = None
