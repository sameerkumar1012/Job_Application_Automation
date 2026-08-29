from unittest.mock import patch

from server.models import Profile
from server.option_picker import pick_option


def _profile():
    return Profile(full_name="Ada Lovelace", email="ada@example.com", location="Bangalore, India")


def test_returns_literal_option_when_ai_matches_one():
    with patch("server.option_picker.call_nemotron_json", return_value={"choice": "Yes, Pune"}):
        result = pick_option(_profile(), "Are you open for relocation?", ["No", "Yes, Pune", "Yes, Mumbai"])
    assert result == "Yes, Pune"


def test_returns_none_when_ai_says_none():
    with patch("server.option_picker.call_nemotron_json", return_value={"choice": "none"}):
        result = pick_option(_profile(), "Have you previously applied here?", ["Yes", "No"])
    assert result is None


def test_returns_none_when_ai_response_is_not_a_literal_option():
    # Defensive: a full-sentence or hallucinated response must never be treated as
    # a valid pick -- only an exact, literal member of the option list counts.
    with patch(
        "server.option_picker.call_nemotron_json",
        return_value={"choice": "No, I have not previously applied to this company."},
    ):
        result = pick_option(_profile(), "Have you previously applied here?", ["Yes", "No"])
    assert result is None


def test_returns_none_when_choice_key_missing():
    with patch("server.option_picker.call_nemotron_json", return_value={}):
        result = pick_option(_profile(), "Notice period?", ["0-15 days", "15-30 days"])
    assert result is None
