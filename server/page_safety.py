import re

from server.models import BlockedInfo, FillRequest, PageSignals

_CAPTCHA_IFRAME_PATTERNS = re.compile(r"(recaptcha|hcaptcha|turnstile)", re.IGNORECASE)
_CAPTCHA_TEXT_PATTERNS = re.compile(
    r"(verify you are human|i'?m not a robot|prove you'?re human)", re.IGNORECASE
)
_LOGIN_TEXT_PATTERNS = re.compile(r"(log ?in|sign ?in|welcome back)", re.IGNORECASE)


def is_captcha(signals: PageSignals) -> bool:
    if any(_CAPTCHA_IFRAME_PATTERNS.search(src) for src in signals.iframe_src_list):
        return True
    if _CAPTCHA_TEXT_PATTERNS.search(signals.visible_text_snippet):
        return True
    return False


def is_login_wall(signals: PageSignals, num_other_fields: int) -> bool:
    """Conservative in both directions: requires a password field, few other
    fields, and login-ish page text/title -- avoids false-flagging ATS forms
    that also offer an optional 'create an account' field."""
    if signals.password_field_count < 1:
        return False
    if num_other_fields >= 3:
        return False
    combined = f"{signals.url} {signals.title} {signals.visible_text_snippet}"
    if not _LOGIN_TEXT_PATTERNS.search(combined):
        return False
    return True


def classify_block(request: FillRequest) -> BlockedInfo | None:
    if is_captcha(request.page):
        return BlockedInfo(
            reason="captcha",
            message="This page appears to have a CAPTCHA challenge. Please solve it manually before filling.",
        )

    num_other_fields = len(request.fields)
    if is_login_wall(request.page, num_other_fields):
        return BlockedInfo(
            reason="login-wall",
            message="This looks like a login page, not an application form. Please log in manually first.",
        )

    return None
