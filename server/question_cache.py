import re
from typing import Optional

from server import storage
from server.models import JobContext, Profile
from server.nemotron_client import call_nemotron_json

# Canonical archetypes: recurring questions phrased differently across ATSs
# should collide into the same cache key. Order matters -- first match wins.
_ARCHETYPES: list[tuple[str, re.Pattern]] = [
    ("why_this_company", re.compile(r"why (do you want to work|are you interested|us\b)", re.IGNORECASE)),
    ("why_this_role", re.compile(r"why (are you (a )?(good )?fit|this role|this position)", re.IGNORECASE)),
    ("greatest_strength", re.compile(r"(greatest|biggest) strength", re.IGNORECASE)),
    ("greatest_weakness", re.compile(r"(greatest|biggest) weakness", re.IGNORECASE)),
    ("tell_us_about_yourself", re.compile(r"tell (us|me) about yourself", re.IGNORECASE)),
    ("why_hire_you", re.compile(r"why should (we|the company) hire you", re.IGNORECASE)),
]

# Archetypes whose substance is genuinely company-specific -- these get
# regenerated (anchored to the cached version) rather than reused verbatim.
_COMPANY_SPECIFIC_ARCHETYPES = {"why_this_company", "why_this_role"}

_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")

_ANSWER_SYSTEM_PROMPT = (
    "You write concise, first-person job application answers based on the "
    "candidate's profile and the job context provided. Be specific and grounded "
    "in the candidate's real background -- never invent employers, skills, or "
    "credentials that aren't in the profile. Keep answers focused and professional.\n\n"
    'Return a JSON object of this exact shape: {"answer": string}'
)


def normalize_question_signature(question_text: str, company: Optional[str] = None) -> str:
    for signature, pattern in _ARCHETYPES:
        if pattern.search(question_text):
            return signature

    cleaned = _PUNCT_RE.sub("", question_text.lower())
    cleaned = _WHITESPACE_RE.sub("_", cleaned.strip())
    return cleaned


def get_or_generate_answer(
    profile: Profile, question_text: str, job_context: Optional[JobContext] = None
) -> tuple[str, str, str]:
    """Returns (answer, confidence, source)."""
    company = job_context.company if job_context else None
    signature = normalize_question_signature(question_text, company)
    cached = profile.saved_answers.get(signature)

    if cached and signature not in _COMPANY_SPECIFIC_ARCHETYPES:
        return cached, "medium", "saved-answer"

    if cached and signature in _COMPANY_SPECIFIC_ARCHETYPES:
        answer = _generate_answer(
            profile,
            question_text,
            job_context,
            anchor=cached,
        )
    else:
        answer = _generate_answer(profile, question_text, job_context, anchor=None)

    profile.saved_answers[signature] = answer
    storage.save_profile(profile)
    return answer, "medium", "ai-generated"


def _generate_answer(
    profile: Profile,
    question_text: str,
    job_context: Optional[JobContext],
    anchor: Optional[str],
) -> str:
    profile_summary = (
        f"Name: {profile.full_name}\n"
        f"Skills: {', '.join(profile.skills)}\n"
        f"Recent experience: "
        + "; ".join(
            f"{w.title} at {w.company}" for w in profile.work_experience[:3]
        )
    )
    context_lines = [f"Question: {question_text}", profile_summary]
    if job_context:
        if job_context.company:
            context_lines.append(f"Company: {job_context.company}")
        if job_context.title:
            context_lines.append(f"Job title: {job_context.title}")
        if job_context.description_snippet:
            context_lines.append(f"Job description snippet: {job_context.description_snippet}")
    if anchor:
        context_lines.append(
            f"A previous answer to a similar question (adapt the same reasons and "
            f"tone, but correctly address the current company/context): {anchor}"
        )

    result = call_nemotron_json(
        system_prompt=_ANSWER_SYSTEM_PROMPT,
        user_prompt="\n".join(context_lines),
        max_tokens=512,
    )
    return result.get("answer", "").strip()
