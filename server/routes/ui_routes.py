from flask import Blueprint, redirect, render_template, request, url_for

from server import config, resume_parser, storage
from server.models import (
    Education,
    EeoDisclosure,
    ExtensionSettings,
    Profile,
    ProfileLinks,
    WorkAuthorization,
    WorkExperience,
)
from server.nemotron_client import NemotronConfigError, NemotronResponseError

ui_bp = Blueprint("ui", __name__)


def _yes_no(value: str | None) -> bool:
    return (value or "").strip().lower() in ("yes", "true", "on", "1")


def _parse_work_experience(form) -> list[WorkExperience]:
    companies = form.getlist("work_company[]")
    titles = form.getlist("work_title[]")
    locations = form.getlist("work_location[]")
    starts = form.getlist("work_start[]")
    ends = form.getlist("work_end[]")
    currents = form.getlist("work_current[]")
    descriptions = form.getlist("work_description[]")

    rows = []
    for i, company in enumerate(companies):
        if not company.strip():
            continue
        rows.append(
            WorkExperience(
                company=company.strip(),
                title=(titles[i] if i < len(titles) else "").strip(),
                location=(locations[i] if i < len(locations) else "").strip() or None,
                start_date=(starts[i] if i < len(starts) else "").strip(),
                end_date=(ends[i] if i < len(ends) else "").strip() or None,
                current=_yes_no(currents[i]) if i < len(currents) else False,
                description=(descriptions[i] if i < len(descriptions) else "").strip() or None,
            )
        )
    return rows


def _parse_education(form) -> list[Education]:
    schools = form.getlist("edu_school[]")
    degrees = form.getlist("edu_degree[]")
    fields = form.getlist("edu_field[]")
    starts = form.getlist("edu_start[]")
    ends = form.getlist("edu_end[]")
    gpas = form.getlist("edu_gpa[]")

    rows = []
    for i, school in enumerate(schools):
        if not school.strip():
            continue
        rows.append(
            Education(
                school=school.strip(),
                degree=(degrees[i] if i < len(degrees) else "").strip() or None,
                field_of_study=(fields[i] if i < len(fields) else "").strip() or None,
                start_date=(starts[i] if i < len(starts) else "").strip() or None,
                end_date=(ends[i] if i < len(ends) else "").strip() or None,
                gpa=(gpas[i] if i < len(gpas) else "").strip() or None,
            )
        )
    return rows


def _profile_from_form(form, existing: Profile) -> Profile:
    skills_raw = form.get("skills", "")
    skills = [s.strip() for s in skills_raw.split(",") if s.strip()]

    saved_answers = dict(existing.saved_answers)
    for signature in list(saved_answers.keys()):
        if _yes_no(form.get(f"delete_answer__{signature}")):
            saved_answers.pop(signature, None)
            continue
        updated = form.get(f"saved_answer__{signature}")
        if updated is not None:
            saved_answers[signature] = updated

    return Profile(
        full_name=form.get("full_name", "").strip(),
        preferred_name=form.get("preferred_name", "").strip() or None,
        pronouns=form.get("pronouns", "").strip() or None,
        email=form.get("email", "").strip(),
        phone=form.get("phone", "").strip() or None,
        location=form.get("location", "").strip() or None,
        links=ProfileLinks(
            linkedin=form.get("linkedin", "").strip() or None,
            github=form.get("github", "").strip() or None,
            portfolio=form.get("portfolio", "").strip() or None,
            other=form.get("other_link", "").strip() or None,
        ),
        work_experience=_parse_work_experience(form),
        education=_parse_education(form),
        skills=skills,
        work_authorization=WorkAuthorization(
            authorized_to_work_in_country=_yes_no(form.get("authorized_to_work")),
            requires_sponsorship_now=_yes_no(form.get("requires_sponsorship_now")),
            requires_sponsorship_future=_yes_no(form.get("requires_sponsorship_future")),
            country=form.get("work_auth_country", "").strip(),
        ),
        eeo=EeoDisclosure(
            want_to_self_identify=_yes_no(form.get("want_to_self_identify")),
            gender=form.get("eeo_gender", "").strip() or None,
            race=form.get("eeo_race", "").strip() or None,
            veteran_status=form.get("eeo_veteran", "").strip() or None,
            disability_status=form.get("eeo_disability", "").strip() or None,
        ),
        desired_salary_min=_to_float(form.get("salary_min")),
        desired_salary_max=_to_float(form.get("salary_max")),
        salary_currency=form.get("salary_currency", "").strip() or None,
        saved_answers=saved_answers,
        resume_file_name=existing.resume_file_name,
        resume_text=existing.resume_text,
        cover_letter_file_name=existing.cover_letter_file_name,
        cover_letter_text=existing.cover_letter_text,
    )


def _to_float(value: str | None):
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


@ui_bp.get("/")
def dashboard():
    profile = storage.get_profile()
    settings = storage.get_settings()
    return render_template(
        "dashboard.html",
        profile=profile,
        settings=settings,
        nemotron_configured=bool(config.NVIDIA_API_KEY),
    )


@ui_bp.get("/profile")
def profile_form():
    profile = storage.get_profile()
    return render_template("profile.html", profile=profile, draft=None)


@ui_bp.post("/profile")
def profile_save():
    existing = storage.get_profile()
    updated = _profile_from_form(request.form, existing)
    storage.save_profile(updated)
    return redirect(url_for("ui.profile_form"))


@ui_bp.get("/resume")
def resume_form():
    profile = storage.get_profile()
    return render_template("resume.html", profile=profile, error=None)


@ui_bp.post("/resume/upload")
def resume_upload():
    profile = storage.get_profile()
    upload = request.files.get("resume_file")
    if upload is None or not upload.filename:
        return render_template("resume.html", profile=profile, error="Please choose a file to upload.")

    data = upload.read()
    filename = upload.filename
    text = resume_parser.extract_text_from_file(filename, data)

    profile.resume_file_name = filename
    profile.resume_text = text
    storage.save_resume_bytes(filename, data)

    try:
        parsed = resume_parser.parse_resume_into_profile(text)
    except NemotronConfigError:
        storage.save_profile(profile)
        return render_template(
            "resume.html",
            profile=profile,
            error="Resume text was saved, but auto-parsing needs an NVIDIA_API_KEY in .env. "
            "Fill in the rest of your profile manually for now.",
        )
    except NemotronResponseError as exc:
        storage.save_profile(profile)
        return render_template(
            "resume.html",
            profile=profile,
            error=f"Resume text was saved, but auto-parsing failed: {exc}",
        )

    profile.full_name = parsed.get("fullName") or profile.full_name
    profile.email = parsed.get("email") or profile.email
    profile.phone = parsed.get("phone") or profile.phone
    profile.location = parsed.get("location") or profile.location
    links = parsed.get("links") or {}
    profile.links = ProfileLinks(
        linkedin=links.get("linkedin"),
        github=links.get("github"),
        portfolio=links.get("portfolio"),
    )
    profile.work_experience = [WorkExperience.model_validate(w) for w in parsed.get("workExperience", [])]
    profile.education = [Education.model_validate(e) for e in parsed.get("education", [])]
    profile.skills = parsed.get("skills") or []

    storage.save_profile(profile)
    return redirect(url_for("ui.profile_form"))


@ui_bp.get("/settings")
def settings_form():
    settings = storage.get_settings()
    return render_template(
        "settings.html", settings=settings, nemotron_configured=bool(config.NVIDIA_API_KEY)
    )


@ui_bp.post("/settings")
def settings_save():
    settings = ExtensionSettings(
        model=request.form.get("model", "").strip() or config.NVIDIA_MODEL_DEFAULT,
        auto_advance_steps=_yes_no(request.form.get("auto_advance_steps")),
    )
    storage.save_settings(settings)
    return redirect(url_for("ui.settings_form"))
