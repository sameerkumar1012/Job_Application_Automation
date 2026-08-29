# Not in the original plan's four-file test list, but the submit-vs-next
# button classification actually lives in fill_engine.py (not field_matcher.py),
# so its safety-critical tests belong here rather than shoehorned elsewhere.

from unittest.mock import patch

from server.fill_engine import _looks_like_free_text_question, run_fill, _choose_button
from server.models import CandidateButton, DetectedField, FillRequest, PageSignals, Profile, WorkExperience


def _btn(button_id, text):
    return CandidateButton(button_id=button_id, text=text)


def test_single_next_button_is_chosen():
    buttons = [_btn("b1", "Next"), _btn("b2", "Back")]
    click_id, reached_final = _choose_button(buttons)
    assert click_id == "b1"
    assert reached_final is False


def test_submit_button_never_clicked():
    buttons = [_btn("b1", "Submit Application")]
    click_id, reached_final = _choose_button(buttons)
    assert click_id is None
    assert reached_final is True


def test_ambiguous_next_submit_label_excluded_from_next_and_never_clicked():
    # A button literally labeled "Next: Submit" must be excluded by the
    # submit-block filter, which always wins over the next-allow filter.
    buttons = [_btn("b1", "Next: Submit")]
    click_id, reached_final = _choose_button(buttons)
    assert click_id is None
    assert reached_final is True


def test_multiple_next_candidates_is_ambiguous_and_does_nothing():
    buttons = [_btn("b1", "Next"), _btn("b2", "Continue")]
    click_id, reached_final = _choose_button(buttons)
    assert click_id is None
    assert reached_final is False


def test_no_buttons_at_all_does_nothing():
    click_id, reached_final = _choose_button([])
    assert click_id is None
    assert reached_final is False


def test_next_and_submit_together_only_clicks_next():
    buttons = [_btn("b1", "Next"), _btn("b2", "Submit Application")]
    click_id, reached_final = _choose_button(buttons)
    assert click_id == "b1"
    assert reached_final is False


def test_save_and_continue_is_recognized_as_next():
    buttons = [_btn("b1", "Save and Continue")]
    click_id, reached_final = _choose_button(buttons)
    assert click_id == "b1"
    assert reached_final is False


def _field(**kwargs):
    defaults = dict(field_id="f1", tag="input", input_type="radio", label="", options=[])
    defaults.update(kwargs)
    return DetectedField(**defaults)


def test_question_shaped_field_with_options_is_never_free_text():
    # A "?"-ending label used to be enough to route a field into the essay-writing
    # AI path, even for a radio/select/checkbox-group with a fixed option set.
    field = _field(label="Have you previously applied to this company?", options=["Yes", "No"])
    assert _looks_like_free_text_question(field) is False


def test_textarea_without_options_still_uses_existing_heuristic():
    # Unchanged by design: a plain textarea with no fixed option set still routes
    # through the free-text path (the real-world "Current Company Name:" case is
    # instead intercepted earlier by field_matcher's deterministic company rule,
    # via match_field_to_profile, before this check is ever reached).
    field = _field(tag="textarea", input_type="textarea", label="Current Company Name:", options=[])
    assert _looks_like_free_text_question(field) is True


def test_textarea_with_question_shape_and_no_options_is_free_text():
    field = _field(tag="textarea", input_type="textarea", label="Why do you want this job?", options=[])
    assert _looks_like_free_text_question(field) is True


def _fill_request(fields):
    return FillRequest(page=PageSignals(url="https://example.com", password_field_count=0), fields=fields)


def test_options_bearing_field_uses_constrained_choice_not_essay():
    field = _field(label="Are you open for Relocation?", options=["No", "Yes, Mumbai", "Yes, Pune"])
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")

    with patch("server.fill_engine.storage.get_profile", return_value=profile), \
         patch("server.fill_engine.pick_option", return_value="Yes, Pune") as mock_pick, \
         patch("server.fill_engine.get_or_generate_answer") as mock_essay:
        result = run_fill(_fill_request([field]))

    mock_pick.assert_called_once()
    mock_essay.assert_not_called()
    assert len(result.filled_fields) == 1
    assert result.filled_fields[0].value == "Yes, Pune"
    assert result.filled_fields[0].confidence == "medium"
    assert result.filled_fields[0].source == "ai-generated"


def test_constrained_choice_none_leaves_field_unfilled():
    field = _field(label="Have you previously applied here?", options=["Yes", "No"])
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")

    with patch("server.fill_engine.storage.get_profile", return_value=profile), \
         patch("server.fill_engine.pick_option", return_value=None):
        result = run_fill(_fill_request([field]))

    assert result.filled_fields == []
    assert len(result.unfilled_fields) == 1
    assert result.unfilled_fields[0].field_id == "f1"


def _two_job_profile():
    return Profile(
        full_name="Ada Lovelace",
        email="ada@example.com",
        work_experience=[
            WorkExperience(company="Acme Corp", title="Engineer", start_date="2022-01", current=True),
            WorkExperience(company="Old Co", title="Junior Engineer", start_date="2018-01", current=False),
        ],
    )


def test_add_row_button_prioritized_over_next_when_rows_still_needed():
    # Only one "Position" field on the page -> one row visible, but the profile
    # has two work-experience entries, so the add-row link must be clicked before
    # any Next button, or the second entry would never get a row to be filled into.
    position_field = _field(field_id="f1", tag="input", input_type="text", label="Position", options=[])
    request = FillRequest(
        page=PageSignals(url="https://example.com"),
        fields=[position_field],
        buttons=[
            CandidateButton(button_id="b1", text="Next"),
            CandidateButton(button_id="b2", text="Add Company Experience"),
        ],
    )

    with patch("server.fill_engine.storage.get_profile", return_value=_two_job_profile()):
        result = run_fill(request)

    assert result.click_button_id == "b2"
    assert result.reached_final_step is False


def test_next_resumes_once_row_count_satisfies_profile():
    # Two "Position" fields already on the page (rows for both profile entries) ->
    # no more rows needed, normal Next selection should take over.
    fields = [
        _field(field_id="f1", tag="input", input_type="text", label="Position", options=[]),
        _field(field_id="f2", tag="input", input_type="text", label="Position", options=[]),
    ]
    request = FillRequest(
        page=PageSignals(url="https://example.com"),
        fields=fields,
        buttons=[
            CandidateButton(button_id="b1", text="Next"),
            CandidateButton(button_id="b2", text="Add Company Experience"),
        ],
    )

    with patch("server.fill_engine.storage.get_profile", return_value=_two_job_profile()):
        result = run_fill(request)

    assert result.click_button_id == "b1"
