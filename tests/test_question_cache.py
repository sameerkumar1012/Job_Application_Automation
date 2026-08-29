from unittest.mock import patch

from server.models import JobContext, Profile
from server.question_cache import get_or_generate_answer, normalize_question_signature


def test_why_this_company_variants_collide_to_same_signature():
    sig1 = normalize_question_signature("Why do you want to work at Acme?")
    sig2 = normalize_question_signature("Why are you interested in Acme Corp?")
    sig3 = normalize_question_signature("Why us?")
    assert sig1 == sig2 == sig3 == "why_this_company"


def test_generic_question_falls_back_to_cleaned_text():
    sig = normalize_question_signature("What is your favorite programming language?")
    assert sig == "what_is_your_favorite_programming_language"


def test_cached_generic_answer_reused_without_llm_call():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    profile.saved_answers["tell_us_about_yourself"] = "I'm a software engineer with 5 years of experience."

    with patch("server.question_cache.call_nemotron_json") as mock_call, \
         patch("server.question_cache.storage.save_profile"):
        answer, confidence, source = get_or_generate_answer(
            profile, "Tell us about yourself", None
        )
        mock_call.assert_not_called()
        assert answer == "I'm a software engineer with 5 years of experience."
        assert source == "saved-answer"
        assert confidence == "medium"


def test_company_specific_cache_hit_regenerates_anchored_answer():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")
    profile.saved_answers["why_this_company"] = "I admire Acme's engineering culture."

    with patch("server.question_cache.call_nemotron_json") as mock_call, \
         patch("server.question_cache.storage.save_profile"):
        mock_call.return_value = {"answer": "I admire Globex's engineering culture."}
        answer, confidence, source = get_or_generate_answer(
            profile,
            "Why do you want to work at Globex?",
            JobContext(company="Globex"),
        )
        mock_call.assert_called_once()
        assert answer == "I admire Globex's engineering culture."
        assert source == "ai-generated"
        # The anchor (previous answer) should have been passed into the prompt.
        user_prompt = mock_call.call_args.kwargs["user_prompt"]
        assert "admire Acme" in user_prompt


def test_cache_miss_generates_and_saves():
    profile = Profile(full_name="Ada Lovelace", email="ada@example.com")

    with patch("server.question_cache.call_nemotron_json") as mock_call, \
         patch("server.question_cache.storage.save_profile") as mock_save:
        mock_call.return_value = {"answer": "My greatest strength is problem solving."}
        answer, confidence, source = get_or_generate_answer(
            profile, "What is your greatest strength?", None
        )
        assert answer == "My greatest strength is problem solving."
        assert source == "ai-generated"
        assert profile.saved_answers["greatest_strength"] == answer
        mock_save.assert_called_once()
