import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY") or None
NVIDIA_MODEL_DEFAULT = os.environ.get("NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1")
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

PORT = int(os.environ.get("PORT", "8765"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")

# Hardcoded, never env-overridable: the API has no auth of its own, so it must
# never be reachable from outside this machine.
HOST = "127.0.0.1"

DATA_DIR = BASE_DIR / "data"
RESUMES_DIR = DATA_DIR / "resumes"
COVER_LETTERS_DIR = DATA_DIR / "cover_letters"
PROFILE_PATH = DATA_DIR / "profile.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
