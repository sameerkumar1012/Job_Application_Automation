import json
import mimetypes
from pathlib import Path
from typing import Optional

from server import config
from server.models import (
    ExtensionSettings,
    Profile,
    create_default_settings,
    create_empty_profile,
)


def _ensure_data_dirs() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    config.COVER_LETTERS_DIR.mkdir(parents=True, exist_ok=True)


def get_profile() -> Profile:
    _ensure_data_dirs()
    if not config.PROFILE_PATH.exists():
        return create_empty_profile()
    try:
        raw = json.loads(config.PROFILE_PATH.read_text())
        return Profile.model_validate(raw)
    except (json.JSONDecodeError, ValueError, OSError):
        return create_empty_profile()


def save_profile(profile: Profile) -> None:
    _ensure_data_dirs()
    config.PROFILE_PATH.write_text(
        json.dumps(profile.model_dump(by_alias=True), indent=2)
    )


def get_settings() -> ExtensionSettings:
    _ensure_data_dirs()
    if not config.SETTINGS_PATH.exists():
        settings = create_default_settings(config.NVIDIA_MODEL_DEFAULT)
        save_settings(settings)
        return settings
    try:
        raw = json.loads(config.SETTINGS_PATH.read_text())
        return ExtensionSettings.model_validate(raw)
    except (json.JSONDecodeError, ValueError, OSError):
        return create_default_settings(config.NVIDIA_MODEL_DEFAULT)


def save_settings(settings: ExtensionSettings) -> None:
    _ensure_data_dirs()
    config.SETTINGS_PATH.write_text(
        json.dumps(settings.model_dump(by_alias=True), indent=2)
    )


def save_resume_bytes(filename: str, data: bytes) -> Path:
    _ensure_data_dirs()
    path = config.RESUMES_DIR / filename
    path.write_bytes(data)
    return path


def save_cover_letter_bytes(filename: str, data: bytes) -> Path:
    _ensure_data_dirs()
    path = config.COVER_LETTERS_DIR / filename
    path.write_bytes(data)
    return path


def _latest_file(directory: Path) -> Optional[Path]:
    if not directory.exists():
        return None
    files = [p for p in directory.iterdir() if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def get_resume_file() -> Optional[tuple[bytes, str, str]]:
    path = _latest_file(config.RESUMES_DIR)
    if path is None:
        return None
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.read_bytes(), path.name, mimetype


def get_cover_letter_file() -> Optional[tuple[bytes, str, str]]:
    path = _latest_file(config.COVER_LETTERS_DIR)
    if path is None:
        return None
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.read_bytes(), path.name, mimetype
