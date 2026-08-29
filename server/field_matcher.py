import re
from dataclasses import dataclass
from typing import Optional

from server.models import DetectedField, FilledField, Profile

_DECLINE_PATTERNS = re.compile(
    r"(decline|prefer not|do not wish|choose not|rather not)", re.IGNORECASE
)
_YES_PATTERNS = re.compile(r"^\s*yes\b", re.IGNORECASE)
_NO_PATTERNS = re.compile(r"^\s*no\b", re.IGNORECASE)

# (detector against the profile's free-text degree string, target to search for in
# the form's dropdown options) -- a profile degree like "B.S. Computer Science" won't
# literally substring-match an option like "Bachelor of Science", so common
# abbreviation/full-name pairs are bridged explicitly. Not an exhaustive list.
_DEGREE_GROUPS = [
    (re.compile(r"ph\.?d\.?|doctorate", re.IGNORECASE), re.compile(r"ph\.?d\.?|doctorate", re.IGNORECASE)),
    (re.compile(r"\bmba\b", re.IGNORECASE), re.compile(r"\bmba\b", re.IGNORECASE)),
    (re.compile(r"\bm\.?s\.?\b|master of science", re.IGNORECASE), re.compile(r"master of science|\bm\.?s\.?\b", re.IGNORECASE)),
    (re.compile(r"\bm\.?a\.?\b|master of arts", re.IGNORECASE), re.compile(r"master of arts|\bm\.?a\.?\b", re.IGNORECASE)),
    (re.compile(r"\bb\.?s\.?\b|bachelor of science", re.IGNORECASE), re.compile(r"bachelor of science|\bb\.?s\.?\b", re.IGNORECASE)),
    (re.compile(r"\bb\.?a\.?\b|bachelor of arts", re.IGNORECASE), re.compile(r"bachelor of arts|\bb\.?a\.?\b", re.IGNORECASE)),
]


@dataclass
class MatchResult:
    value: str
    confidence: str  # "high" | "medium"
    reasoning: Optional[str] = None


def _field_text(field: DetectedField) -> str:
    parts = [field.label, field.placeholder or "", field.name or "", field.id_attr or "", field.aria_label or ""]
    return " ".join(parts).lower()


def _looks_like(text: str, *keywords: str) -> bool:
    return any(kw in text for kw in keywords)


def _format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def match_field_to_profile(
    field: DetectedField, profile: Profile, row_counters: Optional[dict] = None
) -> Optional[MatchResult]:
    """Deterministic, no-LLM matching of a detected field to profile data.
    Returns None if no confident match is found, so the field can be routed
    to AI-answer generation or reported as unfilled.

    `row_counters` should be the *same* dict passed across every field in one
    fill request -- it's how repeatable work-experience/education row fields
    (which all share identical labels, e.g. every row says just "Position") get
    correlated to the right profile list entry, purely by occurrence order."""
    if row_counters is None:
        row_counters = {}
    text = _field_text(field)

    # Structured single-value fields (high confidence: name/email/phone/links).
    if _looks_like(text, "e-mail", "email") and profile.email:
        return MatchResult(profile.email, "high")

    if _looks_like(text, "phone", "mobile", "cell") and profile.phone:
        return MatchResult(profile.phone, "high")

    first, last = _split_name(profile.full_name)
    if _looks_like(text, "first name", "firstname", "given name") and first:
        return MatchResult(first, "medium", "Split from full name")
    if _looks_like(text, "last name", "lastname", "surname", "family name") and last:
        return MatchResult(last, "medium", "Split from full name")
    if _looks_like(text, "full name", "your name") and profile.full_name:
        return MatchResult(profile.full_name, "high")
    if field.name == "name" or field.id_attr == "name":
        if profile.full_name:
            return MatchResult(profile.full_name, "high")

    if _looks_like(text, "pronoun") and profile.pronouns:
        return MatchResult(profile.pronouns, "high")

    if _looks_like(text, "location", "city", "address") and profile.location:
        return MatchResult(profile.location, "medium")

    if _looks_like(text, "linkedin") and profile.links.linkedin:
        return MatchResult(profile.links.linkedin, "high")
    if _looks_like(text, "github") and profile.links.github:
        return MatchResult(profile.links.github, "high")
    if _looks_like(text, "portfolio", "website", "personal site") and profile.links.portfolio:
        return MatchResult(profile.links.portfolio, "high")

    if _looks_like(text, "skill") and profile.skills:
        return MatchResult(", ".join(profile.skills), "medium")

    if _looks_like(text, "salary") and (profile.desired_salary_min or profile.desired_salary_max):
        low = profile.desired_salary_min
        high = profile.desired_salary_max
        currency = profile.salary_currency or ""
        if low and high:
            return MatchResult(f"{currency} {_format_number(low)}-{_format_number(high)}".strip(), "medium")
        value = low or high
        if value:
            return MatchResult(f"{currency} {_format_number(value)}".strip(), "medium")

    if _looks_like(text, "current company", "current employer", "most recent employer") and profile.work_experience:
        return MatchResult(profile.work_experience[0].company, "medium", "Most recent employer from profile")

    # Work authorization: option-based fields.
    if profile.work_authorization and field.options:
        wa = profile.work_authorization
        if _looks_like(text, "authorized to work", "legally authorized", "eligible to work"):
            wants_yes = wa.authorized_to_work_in_country
            match = _pick_yes_no_option(field.options, wants_yes)
            if match:
                return match
        if _looks_like(text, "sponsorship", "visa sponsor"):
            wants_yes = wa.requires_sponsorship_now or wa.requires_sponsorship_future
            match = _pick_yes_no_option(field.options, wants_yes)
            if match:
                return match

    # EEO / voluntary self-identification: always prefer "decline to answer" when
    # the user has not opted in to disclosure, regardless of any stored EEO values.
    if profile.eeo is not None and field.options and _looks_like(
        text, "gender", "race", "ethnicity", "veteran", "disability", "eeo"
    ):
        if not profile.eeo.want_to_self_identify:
            decline = _pick_option_matching(field.options, _DECLINE_PATTERNS)
            if decline:
                return MatchResult(decline, "medium", "User opted out of voluntary disclosure")
        else:
            value = _match_eeo_value(text, profile.eeo)
            if value:
                option = _pick_option_matching(field.options, re.compile(re.escape(value), re.IGNORECASE))
                if option:
                    return MatchResult(option, "medium")

    row_match = _match_repeatable_row(field, profile, text, row_counters)
    if row_match is not None:
        return row_match

    return None


def _match_repeatable_row(
    field: DetectedField, profile: Profile, text: str, row_counters: dict
) -> Optional[MatchResult]:
    """Matches work-experience/education row fields (Position, Organization, Institution,
    ...) by occurrence order -- the Nth "Position" field on the page is work_experience[N],
    the Nth "Institution" field is education[N]. See match_field_to_profile's docstring."""
    reasoning = "Row-matched by position on page"

    if _looks_like(text, "position", "job title"):
        idx = row_counters.get("work_row", 0)
        row_counters["work_row"] = idx + 1
        if idx < len(profile.work_experience) and profile.work_experience[idx].title:
            return MatchResult(profile.work_experience[idx].title, "medium", reasoning)
        return None

    if _looks_like(text, "organization", "employer name", "company name"):
        idx = row_counters.get("work_company", 0)
        row_counters["work_company"] = idx + 1
        if idx < len(profile.work_experience) and profile.work_experience[idx].company:
            return MatchResult(profile.work_experience[idx].company, "medium", reasoning)
        return None

    if _looks_like(text, "current job", "currently work", "i currently work here"):
        idx = row_counters.get("work_current", 0)
        row_counters["work_current"] = idx + 1
        if idx < len(profile.work_experience) and field.options:
            return _pick_yes_no_option(field.options, profile.work_experience[idx].current)
        return None

    if _looks_like(text, "start date"):
        idx = row_counters.get("work_start", 0)
        row_counters["work_start"] = idx + 1
        if idx < len(profile.work_experience) and profile.work_experience[idx].start_date:
            return MatchResult(profile.work_experience[idx].start_date, "medium", reasoning)
        return None

    if _looks_like(text, "end date"):
        idx = row_counters.get("work_end", 0)
        row_counters["work_end"] = idx + 1
        if idx < len(profile.work_experience):
            entry = profile.work_experience[idx]
            if not entry.current and entry.end_date:
                return MatchResult(entry.end_date, "medium", reasoning)
        return None

    if _looks_like(text, "institution", "school name", "university name"):
        idx = row_counters.get("edu_row", 0)
        row_counters["edu_row"] = idx + 1
        if idx < len(profile.education) and profile.education[idx].school:
            return MatchResult(profile.education[idx].school, "medium", reasoning)
        return None

    if _looks_like(text, "major", "field of study"):
        idx = row_counters.get("edu_major", 0)
        row_counters["edu_major"] = idx + 1
        if idx < len(profile.education) and profile.education[idx].field_of_study:
            return MatchResult(profile.education[idx].field_of_study, "medium", reasoning)
        return None

    if _looks_like(text, "graduation date"):
        idx = row_counters.get("edu_end", 0)
        row_counters["edu_end"] = idx + 1
        if idx < len(profile.education) and profile.education[idx].end_date:
            return MatchResult(profile.education[idx].end_date, "medium", reasoning)
        return None

    if _looks_like(text, "degree"):
        idx = row_counters.get("edu_degree", 0)
        row_counters["edu_degree"] = idx + 1
        if idx < len(profile.education) and profile.education[idx].degree and field.options:
            option = _pick_degree_option(field.options, profile.education[idx].degree)
            if option:
                return MatchResult(option, "medium", reasoning)
        return None

    return None


def _pick_degree_option(options: list[str], degree_text: str) -> Optional[str]:
    direct = _pick_option_matching(options, re.compile(re.escape(degree_text), re.IGNORECASE))
    if direct:
        return direct
    for detector, target in _DEGREE_GROUPS:
        if detector.search(degree_text):
            match = _pick_option_matching(options, target)
            if match:
                return match
    return None


def _pick_yes_no_option(options: list[str], wants_yes: bool) -> Optional[MatchResult]:
    pattern = _YES_PATTERNS if wants_yes else _NO_PATTERNS
    for option in options:
        if pattern.match(option.strip()):
            # Unambiguous boolean yes/no pair -> high confidence.
            return MatchResult(option, "high")
    return None


def _pick_option_matching(options: list[str], pattern: re.Pattern) -> Optional[str]:
    for option in options:
        if pattern.search(option):
            return option
    return None


def _match_eeo_value(text: str, eeo) -> Optional[str]:
    if "gender" in text:
        return eeo.gender
    if "race" in text or "ethnicity" in text:
        return eeo.race
    if "veteran" in text:
        return eeo.veteran_status
    if "disability" in text:
        return eeo.disability_status
    return None


def to_filled_field(field: DetectedField, match: MatchResult, source: str = "profile") -> FilledField:
    # AI-generated and saved-answer values are never allowed to report "high" --
    # they're always a generated/reused guess and must stay flagged for review.
    confidence = match.confidence
    if source in ("ai-generated", "saved-answer") and confidence == "high":
        confidence = "medium"
    return FilledField(
        field_id=field.field_id,
        label=field.label or field.name or field.field_id,
        value=match.value,
        confidence=confidence,
        source=source,
        reasoning=match.reasoning,
    )
