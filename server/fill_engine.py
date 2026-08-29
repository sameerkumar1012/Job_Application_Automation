import re

from server import field_matcher, page_safety, storage
from server.models import (
    CandidateButton,
    DetectedField,
    FillRequest,
    FillStepResult,
    FilledField,
    UnfilledField,
)
from server.nemotron_client import NemotronConfigError, NemotronResponseError
from server.option_picker import pick_option
from server.question_cache import get_or_generate_answer

# Substring match anywhere in button text -- always wins over any "next" match,
# even for an ambiguous label like "Next: Submit". This filter runs first and
# permanently excludes matching buttons from consideration.
SUBMIT_BLOCK_PATTERNS = [
    "submit",
    "apply now",
    "finish",
    "complete application",
    "send application",
    "place application",
    "review and submit",
]

# Whole-phrase match only, evaluated on the remaining (non-blocked) candidates.
NEXT_ALLOW_PATTERNS = [
    "next",
    "continue",
    "save and continue",
    "next step",
]

# Substring match for the "add another row" links in repeatable work-experience/
# education sections (e.g. Cornerstone's "Add Company Experience"). These are
# usually plain <a href="javascript:void(0)"> links, not real <button> elements.
ADD_WORK_ROW_PATTERNS = ["add company experience", "add work experience", "add another position", "add experience"]
ADD_EDUCATION_ROW_PATTERNS = ["add education", "add another education"]

_QUESTION_SHAPE_RE = re.compile(r"\?\s*$")
_FREE_TEXT_TAGS = {"textarea"}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _is_submit_labeled(text: str) -> bool:
    normalized = _normalize(text)
    return any(pattern in normalized for pattern in SUBMIT_BLOCK_PATTERNS)


def _is_next_labeled(text: str) -> bool:
    normalized = _normalize(text)
    return any(normalized == pattern or normalized.startswith(pattern + " ") or pattern in normalized
               for pattern in NEXT_ALLOW_PATTERNS)


def _find_button_matching(buttons: list[CandidateButton], patterns: list[str]) -> str | None:
    for button in buttons:
        normalized = _normalize(button.text)
        if any(pattern in normalized for pattern in patterns):
            return button.button_id
    return None


def _choose_button(buttons: list[CandidateButton]) -> tuple[str | None, bool]:
    """Returns (click_button_id, reached_final_step)."""
    non_submit = [b for b in buttons if not _is_submit_labeled(b.text)]
    saw_submit = len(non_submit) != len(buttons)

    next_candidates = [b for b in non_submit if _is_next_labeled(b.text)]

    if len(next_candidates) == 1:
        click_id = next_candidates[0].button_id
        reached_final = False
        return click_id, reached_final

    # Zero or ambiguous (more than one) -> do nothing, never guess.
    reached_final = saw_submit and len(next_candidates) == 0
    return None, reached_final


def _looks_like_free_text_question(field: DetectedField) -> bool:
    # A field with a fixed option set (radio/select/checkbox-group) is never an open
    # essay prompt, no matter what its label looks like -- it always needs one of its
    # own options, handled separately by the constrained-choice path below.
    if field.options:
        return False
    if field.tag.lower() in _FREE_TEXT_TAGS:
        return True
    label = field.label or field.placeholder or ""
    return bool(_QUESTION_SHAPE_RE.search(label.strip()))


def run_fill(request: FillRequest) -> FillStepResult:
    blocked = page_safety.classify_block(request)
    if blocked is not None:
        return FillStepResult(blocked=blocked)

    profile = storage.get_profile()

    filled_fields: list[FilledField] = []
    unfilled_fields: list[UnfilledField] = []
    row_counters: dict = {}

    for field in request.fields:
        match = field_matcher.match_field_to_profile(field, profile, row_counters)
        if match is not None:
            filled_fields.append(field_matcher.to_filled_field(field, match, source="profile"))
            continue

        if _looks_like_free_text_question(field):
            question_text = field.label or field.placeholder or ""
            try:
                answer, confidence, source = get_or_generate_answer(
                    profile, question_text, request.job_context
                )
                if answer:
                    filled_fields.append(
                        FilledField(
                            field_id=field.field_id,
                            label=field.label or field.field_id,
                            value=answer,
                            confidence=confidence,
                            source=source,
                        )
                    )
                    continue
                unfilled_fields.append(
                    UnfilledField(
                        field_id=field.field_id,
                        label=field.label or field.field_id,
                        reason="AI did not produce an answer.",
                    )
                )
                continue
            except NemotronConfigError:
                unfilled_fields.append(
                    UnfilledField(
                        field_id=field.field_id,
                        label=field.label or field.field_id,
                        reason="Needs an AI-generated answer -- add your NVIDIA_API_KEY in .env to enable this.",
                    )
                )
                continue
            except NemotronResponseError as exc:
                unfilled_fields.append(
                    UnfilledField(
                        field_id=field.field_id,
                        label=field.label or field.field_id,
                        reason=f"AI answer generation failed: {exc}",
                    )
                )
                continue

        if field.options:
            question_text = field.label or field.placeholder or ""
            try:
                choice = pick_option(profile, question_text, field.options, request.job_context)
            except NemotronConfigError:
                unfilled_fields.append(
                    UnfilledField(
                        field_id=field.field_id,
                        label=field.label or field.field_id,
                        reason="Needs an AI-assisted choice -- add your NVIDIA_API_KEY in .env to enable this.",
                    )
                )
                continue
            except NemotronResponseError as exc:
                unfilled_fields.append(
                    UnfilledField(
                        field_id=field.field_id,
                        label=field.label or field.field_id,
                        reason=f"AI option selection failed: {exc}",
                    )
                )
                continue

            if choice is not None:
                filled_fields.append(
                    FilledField(
                        field_id=field.field_id,
                        label=field.label or field.field_id,
                        value=choice,
                        confidence="medium",
                        source="ai-generated",
                    )
                )
                continue

            unfilled_fields.append(
                UnfilledField(
                    field_id=field.field_id,
                    label=field.label or field.field_id,
                    reason="No option in the profile or job context confidently answers this question.",
                )
            )
            continue

        if field.tag.lower() == "input" and (field.input_type or "").lower() == "file":
            unfilled_fields.append(
                UnfilledField(
                    field_id=field.field_id,
                    label=field.label or field.field_id,
                    reason="File upload -- attach your resume/cover letter manually or via the popup's attach action.",
                )
            )
            continue

        unfilled_fields.append(
            UnfilledField(
                field_id=field.field_id,
                label=field.label or field.field_id,
                reason="No matching profile data found for this field.",
            )
        )

    # If a repeatable section still has fewer rows on the page than the profile has
    # entries, add another row *before* considering Next/Submit -- otherwise the
    # extension would advance past a section it hasn't finished filling.
    add_row_button_id = None
    if row_counters.get("work_row", 0) < len(profile.work_experience):
        add_row_button_id = _find_button_matching(request.buttons, ADD_WORK_ROW_PATTERNS)
    if add_row_button_id is None and row_counters.get("edu_row", 0) < len(profile.education):
        add_row_button_id = _find_button_matching(request.buttons, ADD_EDUCATION_ROW_PATTERNS)

    if add_row_button_id is not None:
        click_button_id, reached_final_step = add_row_button_id, False
    else:
        click_button_id, reached_final_step = _choose_button(request.buttons)

    return FillStepResult(
        filled_fields=filled_fields,
        unfilled_fields=unfilled_fields,
        advanced_to_next_step=click_button_id is not None,
        reached_final_step=reached_final_step,
        click_button_id=click_button_id,
        blocked=None,
    )
