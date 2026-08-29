from typing import Optional

from server.models import JobContext, Profile
from server.nemotron_client import call_nemotron_json

_SYSTEM_PROMPT = (
    "You pick the single best-fitting answer to a job application question from a fixed "
    "list of options, using only the candidate's profile and the job context provided. "
    "Never guess or invent a choice that isn't actually supported by the profile or "
    "context -- if nothing indicates the correct option, respond with \"none\" instead of "
    "picking one. Never explain your reasoning, just return the choice.\n\n"
    'Return a JSON object of this exact shape: {"choice": string}, where "choice" is '
    'copied verbatim from the option list, or the literal string "none".'
)


def pick_option(
    profile: Profile,
    question_text: str,
    options: list[str],
    job_context: Optional[JobContext] = None,
) -> Optional[str]:
    """Asks Nemotron to pick one literal option, or None if it can't confidently tell.

    The response is validated to be an exact member of `options` -- any other reply
    (including "none") is treated as no match, so this can never invent free text for a
    field that only accepts one of a fixed set of answers."""
    profile_summary = (
        f"Name: {profile.full_name}\n"
        f"Skills: {', '.join(profile.skills)}\n"
        f"Work authorization: {profile.work_authorization}\n"
        f"Location: {profile.location or 'unknown'}"
    )
    context_lines = [
        f"Question: {question_text}",
        f"Options: {options}",
        profile_summary,
    ]
    if job_context:
        if job_context.company:
            context_lines.append(f"Company: {job_context.company}")
        if job_context.title:
            context_lines.append(f"Job title: {job_context.title}")

    result = call_nemotron_json(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt="\n".join(context_lines),
        max_tokens=64,
    )
    choice = (result.get("choice") or "").strip()
    if choice in options:
        return choice
    return None
