from server.field_matcher import match_field_to_profile, to_filled_field
from server.models import (
    DetectedField,
    EeoDisclosure,
    Education,
    Profile,
    WorkAuthorization,
    WorkExperience,
)


def _field(**kwargs):
    defaults = dict(field_id="f1", tag="input", input_type="text", label="", options=[])
    defaults.update(kwargs)
    return DetectedField(**defaults)


def test_matches_email_high_confidence():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="Email address", input_type="email")
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "ada@example.com"
    assert match.confidence == "high"


def test_matches_first_last_name_split():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="First Name")
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "Ada"


def test_no_match_returns_none():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="Favorite color")
    match = match_field_to_profile(field, profile)
    assert match is None


def test_work_authorization_yes_no_high_confidence():
    profile = Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        work_authorization=WorkAuthorization(authorized_to_work_in_country=True, country="US"),
    )
    field = _field(label="Are you authorized to work in this country?", options=["Yes", "No"])
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "Yes"
    assert match.confidence == "high"


def test_eeo_prefers_decline_when_not_opted_in():
    profile = Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        eeo=EeoDisclosure(want_to_self_identify=False, gender="Female"),
    )
    field = _field(
        label="Gender",
        options=["Male", "Female", "Non-binary", "Decline to answer"],
    )
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "Decline to answer"


def test_eeo_uses_stored_value_when_opted_in():
    profile = Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        eeo=EeoDisclosure(want_to_self_identify=True, gender="Female"),
    )
    field = _field(
        label="Gender",
        options=["Male", "Female", "Non-binary", "Decline to answer"],
    )
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "Female"


def test_ai_generated_confidence_capped_at_medium():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="Email address", input_type="email")
    match = match_field_to_profile(field, profile)
    filled = to_filled_field(field, match, source="ai-generated")
    assert filled.confidence == "medium"


def test_saved_answer_confidence_capped_at_medium():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="Email address", input_type="email")
    match = match_field_to_profile(field, profile)
    filled = to_filled_field(field, match, source="saved-answer")
    assert filled.confidence == "medium"


def test_profile_source_keeps_high_confidence():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="Email address", input_type="email")
    match = match_field_to_profile(field, profile)
    filled = to_filled_field(field, match, source="profile")
    assert filled.confidence == "high"


def test_current_company_matches_most_recent_work_experience():
    profile = Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        work_experience=[
            WorkExperience(company="Acme Corp", title="Engineer", start_date="2020-01", current=True),
            WorkExperience(company="Old Co", title="Junior Engineer", start_date="2017-01", current=False),
        ],
    )
    field = _field(label="Current Company Name:", tag="textarea")
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "Acme Corp"
    assert match.confidence == "medium"


def test_current_company_no_match_without_work_experience():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    field = _field(label="Current Company Name:", tag="textarea")
    match = match_field_to_profile(field, profile)
    assert match is None


def test_salary_whole_number_has_no_trailing_decimal():
    profile = Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        desired_salary_min=600000.0,
        salary_currency="INR",
    )
    field = _field(label="Desired Annual Salary:")
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "INR 600000"


def test_salary_fractional_value_keeps_decimal():
    profile = Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        desired_salary_min=60000.5,
    )
    field = _field(label="Desired Annual Salary:")
    match = match_field_to_profile(field, profile)
    assert match is not None
    assert match.value == "60000.5"


def _two_row_profile():
    return Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        work_experience=[
            WorkExperience(company="Acme Corp", title="Engineer", start_date="2022-01", current=True),
            WorkExperience(
                company="Old Co", title="Junior Engineer", start_date="2018-01", end_date="2021-12", current=False
            ),
        ],
        education=[
            Education(school="State University", degree="B.S.", field_of_study="Computer Science", end_date="2018"),
        ],
    )


def test_row_fields_matched_by_occurrence_order():
    profile = _two_row_profile()
    row_counters: dict = {}

    row0_position = match_field_to_profile(_field(label="Position"), profile, row_counters)
    row0_org = match_field_to_profile(_field(label="Organization"), profile, row_counters)
    row1_position = match_field_to_profile(_field(field_id="f2", label="Position"), profile, row_counters)
    row1_org = match_field_to_profile(_field(field_id="f3", label="Organization"), profile, row_counters)

    assert row0_position.value == "Engineer"
    assert row0_org.value == "Acme Corp"
    assert row1_position.value == "Junior Engineer"
    assert row1_org.value == "Old Co"


def test_row_index_beyond_profile_length_is_unmatched():
    profile = _two_row_profile()
    row_counters: dict = {"work_row": 2}  # two rows already consumed
    match = match_field_to_profile(_field(label="Position"), profile, row_counters)
    assert match is None


def test_current_job_checkbox_matches_row():
    profile = _two_row_profile()
    row_counters: dict = {}
    field = _field(label="Current Job", options=["Yes", "No"])
    match = match_field_to_profile(field, profile, row_counters)
    assert match is not None
    assert match.value == "Yes"


def test_end_date_skipped_for_current_job():
    profile = _two_row_profile()
    row_counters: dict = {}
    field = _field(label="End Date")
    match = match_field_to_profile(field, profile, row_counters)
    assert match is None  # row 0 is the current job -- no end date to fill


def test_education_row_matches_institution_major_and_degree():
    profile = _two_row_profile()
    row_counters: dict = {}

    institution = match_field_to_profile(_field(label="Institution"), profile, row_counters)
    major = match_field_to_profile(_field(field_id="f2", label="Major"), profile, row_counters)
    degree = match_field_to_profile(
        _field(field_id="f3", label="Degree", options=["High School", "Bachelor of Science", "Master of Science"]),
        profile,
        row_counters,
    )

    assert institution.value == "State University"
    assert major.value == "Computer Science"
    assert degree.value == "Bachelor of Science"
