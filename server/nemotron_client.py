import json
import re

import requests

from server import config, storage

_JSON_INSTRUCTION = (
    "\n\nRespond with ONLY a single valid JSON object. No markdown code fences, "
    "no prose before or after the JSON."
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

# A 49B model doing a multi-thousand-token structured extraction can legitimately
# take longer than a "quick API call" timeout would allow.
_REQUEST_TIMEOUT_SECONDS = 90


class NemotronConfigError(Exception):
    """Raised only when a call is actually attempted with no API key configured."""


class NemotronResponseError(Exception):
    """Raised when the model's response can't be coerced into JSON."""

    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.raw_text = raw_text


def _parse_json_response(content: str) -> dict:
    stripped = _FENCE_RE.sub("", content).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise NemotronResponseError(
        "Nemotron did not return valid JSON.", raw_text=content
    )


def call_nemotron_json(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> dict:
    if not config.NVIDIA_API_KEY:
        raise NemotronConfigError(
            "No NVIDIA API key configured. Add NVIDIA_API_KEY to your .env file."
        )

    settings = storage.get_settings()

    try:
        response = requests.post(
            config.NVIDIA_API_URL,
            headers={
                "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": system_prompt + _JSON_INSTRUCTION},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise NemotronResponseError(
            f"Could not reach NVIDIA Nemotron API: {exc}"
        ) from exc

    if not response.ok:
        raise NemotronResponseError(
            f"Nemotron API error {response.status_code}: {response.text}",
            raw_text=response.text,
        )

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise NemotronResponseError(
            f"Unexpected Nemotron response shape: {data}", raw_text=str(data)
        ) from exc

    return _parse_json_response(content)
