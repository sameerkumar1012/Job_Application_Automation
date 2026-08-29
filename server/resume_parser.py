import io

import docx
from pypdf import PdfReader

from server.nemotron_client import call_nemotron_json

_SYSTEM_PROMPT = (
    "You extract structured data from resumes. Only use information present in the "
    "resume text; never invent employers, dates, or credentials. Leave fields blank "
    "if the resume does not state them.\n\n"
    "Return a JSON object with this exact shape:\n"
    "{\n"
    '  "fullName": string,\n'
    '  "email": string,\n'
    '  "phone": string (optional),\n'
    '  "location": string (optional),\n'
    '  "links": {"linkedin": string, "github": string, "portfolio": string} (optional fields),\n'
    '  "workExperience": [{"company": string, "title": string, "location": string, '
    '"startDate": "YYYY-MM", "endDate": "YYYY-MM (omit if current)", "current": bool, '
    '"description": string}],\n'
    '  "education": [{"school": string, "degree": string, "fieldOfStudy": string, '
    '"startDate": string, "endDate": string, "gpa": string}],\n'
    '  "skills": [string]\n'
    "}"
)


def extract_text_from_file(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_text(data)
    if lower.endswith(".docx"):
        return _extract_docx_text(data)
    # Plain text / .txt / .md fallback
    return data.decode("utf-8", errors="replace")


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _extract_docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def parse_resume_into_profile(resume_text: str) -> dict:
    """Parses raw resume text into structured profile fields via Nemotron.
    The result is meant to be reviewed/edited by the user, never trusted blindly."""
    parsed = call_nemotron_json(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=f"Extract structured profile data from this resume:\n\n{resume_text}",
        max_tokens=4096,
    )

    work_experience = parsed.get("workExperience") or []
    education = parsed.get("education") or []
    links = parsed.get("links") or {}

    return {
        "fullName": parsed.get("fullName", ""),
        "email": parsed.get("email", ""),
        "phone": parsed.get("phone"),
        "location": parsed.get("location"),
        "links": {
            "linkedin": links.get("linkedin"),
            "github": links.get("github"),
            "portfolio": links.get("portfolio"),
        },
        "workExperience": work_experience,
        "education": education,
        "skills": parsed.get("skills") or [],
        "resumeText": resume_text,
    }
