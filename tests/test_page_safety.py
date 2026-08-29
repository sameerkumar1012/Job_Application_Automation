from server.models import CandidateButton, FillRequest, PageSignals
from server.page_safety import classify_block, is_captcha, is_login_wall


def test_captcha_detected_via_iframe_src():
    signals = PageSignals(
        url="https://example.com/apply",
        title="Apply",
        visible_text_snippet="",
        password_field_count=0,
        iframe_src_list=["https://www.google.com/recaptcha/api2/anchor"],
    )
    assert is_captcha(signals) is True


def test_captcha_detected_via_text():
    signals = PageSignals(
        url="https://example.com/apply",
        title="Apply",
        visible_text_snippet="Please verify you are human before continuing.",
    )
    assert is_captcha(signals) is True


def test_no_false_positive_captcha_on_normal_page():
    signals = PageSignals(
        url="https://example.com/apply",
        title="Apply for Software Engineer",
        visible_text_snippet="Fill out your application below.",
        iframe_src_list=["https://example.com/tracking-pixel"],
    )
    assert is_captcha(signals) is False


def test_login_wall_detected_with_password_and_few_fields():
    signals = PageSignals(
        url="https://example.com/login",
        title="Sign in to continue",
        visible_text_snippet="Welcome back! Please log in.",
        password_field_count=1,
    )
    assert is_login_wall(signals, num_other_fields=2) is True


def test_login_wall_not_flagged_for_real_application_with_password_field():
    # ATS forms sometimes include an optional "create a password" field
    # alongside a real application -- must not false-positive here.
    signals = PageSignals(
        url="https://example.com/apply/step-2",
        title="Application - Personal Information",
        visible_text_snippet="Enter your work experience and create an account.",
        password_field_count=1,
    )
    assert is_login_wall(signals, num_other_fields=8) is False


def test_login_wall_not_flagged_without_login_text():
    signals = PageSignals(
        url="https://example.com/apply",
        title="Job Application",
        visible_text_snippet="Set a password to save your progress.",
        password_field_count=1,
    )
    assert is_login_wall(signals, num_other_fields=1) is False


def test_classify_block_prioritizes_captcha():
    request = FillRequest(
        page=PageSignals(
            url="https://example.com/apply",
            title="Apply",
            visible_text_snippet="verify you are human",
            password_field_count=1,
            iframe_src_list=["https://hcaptcha.com/frame"],
        ),
        fields=[],
        buttons=[],
    )
    result = classify_block(request)
    assert result is not None
    assert result.reason == "captcha"


def test_classify_block_returns_none_for_normal_form():
    request = FillRequest(
        page=PageSignals(
            url="https://example.com/apply",
            title="Job Application",
            visible_text_snippet="Fill out the form below.",
        ),
        fields=[],
        buttons=[CandidateButton(button_id="b1", text="Submit Application")],
    )
    assert classify_block(request) is None
