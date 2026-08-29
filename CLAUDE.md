# CLAUDE.md

## Project purpose

Job Apply Copilot fills out job application forms from a locally-stored profile,
using NVIDIA's Nemotron LLM for resume parsing and free-text answers. It never
submits an application itself — the user always reviews and clicks submit.

## Architecture

Two halves, deliberately split by what each language is forced/allowed to do:

- **`server/`** (Python/Flask) — owns everything: profile storage, resume
  parsing, field-matching heuristics, Nemotron API calls, the submit-safety
  heuristic, login-wall/CAPTCHA detection, and the server-rendered profile
  editor UI (Jinja2 templates in `server/templates/`, no build step).
- **`extension/`** (vanilla JS, MV3) — the irreducible minimum Chrome forces
  into JavaScript: reading the page DOM and applying values to it. It holds
  no business logic and no personal data. `background.js` is the only file
  that calls `fetch()` — it talks to the local server at `http://127.0.0.1:8765`.
  `content.js` calls `fetch()` **never**: it's a dumb scraper/applier, subject
  to the target page's CSP, so all network calls are relayed through the
  background service worker instead.

### Why the split this way
- Chrome cannot execute Python inside an extension context at all — the split
  isn't a preference, it's the actual constraint. Everything that *can* live in
  Python does.
- `content.js` never decides anything (which button is "Next," which field
  matches which profile attribute, whether a page is a login wall) — those
  decisions all happen in `server/fill_engine.py`, `field_matcher.py`, and
  `page_safety.py`. This keeps the safety-critical logic in one place, testable
  with pytest, instead of duplicated/drifted between two languages.

### Data flow for one "Fill this page" click
1. Popup sends `START_FILL` to `background.js`.
2. Background enumerates all frames (`chrome.webNavigation.getAllFrames`) and
   sends `SCAN_PAGE` to each; `content.js` in each frame returns detected
   fields/buttons/page signals.
3. Background aggregates into one `FillRequest`, `POST`s to
   `http://127.0.0.1:8765/api/fill`.
4. `fill_engine.run_fill()`: checks for CAPTCHA/login-wall first (short-circuits
   if blocked), then matches each field via `field_matcher` (deterministic) or
   `question_cache`/Nemotron (free-text questions), then decides at most one
   button to click via the submit-safety heuristic.
5. Background applies the returned fills to the matching frame(s) via
   `APPLY_FILLS`, clicks the one allowed button if any, and — if the response
   says to advance — loops back to step 2 (bounded at `MAX_STEPS = 20`).
6. Progress is written to `chrome.storage.session` per tab so the popup reflects
   live state even if closed and reopened mid-run.

## Privacy model

Everything lives in `data/` (gitignored JSON files) on the user's machine. The
extension itself stores nothing persistent — no `chrome.storage.local` profile
data, no API key in the browser at all. The only network call anywhere in the
system is the local server calling NVIDIA's API, and only when a fill pass
actually needs an AI-generated answer or a resume parse. The server binds to
`127.0.0.1` only (hardcoded in `server/config.py`, not env-overridable) since
the API has no auth of its own.

## Safety invariant: never auto-submit

Enforced in `server/fill_engine.py`'s `_choose_button()`:
- `SUBMIT_BLOCK_PATTERNS` (substring match) always wins — a button matching
  both "next" and "submit" patterns (e.g. "Next: Submit") is excluded, full stop.
- Among the remaining candidates, exactly one `NEXT_ALLOW_PATTERNS` match is
  required to click anything. Zero or multiple matches → click nothing.
- `content.js`'s `APPLY_FILLS` handler clicks at most one button per call, and
  only the exact `button_id` it's told — no fallback guessing on the JS side.

If you touch this logic, keep the tests in `tests/test_fill_engine.py` passing
and add cases for any new button-label pattern you introduce.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then paste your NVIDIA_API_KEY in
python run.py
```

Then load `extension/` as an unpacked extension in `chrome://extensions`
(enable Developer Mode). The server must be running for the popup's "Fill this
page" button and settings to work; the profile editor at `http://127.0.0.1:8765/`
works the same way. Everything except AI-generated answers and resume
auto-parsing works fine with `NVIDIA_API_KEY` left blank.

Run tests with `pytest` (all Nemotron calls are mocked — no real API key or
network access needed).

## Conventions for future work

- Keep matching/navigation *decisions* in `server/`, not in `extension/`.
  `content.js` and `background.js` should stay mechanical.
- Wire shapes (Pydantic models in `server/models.py`) use `alias_generator`
  to emit camelCase JSON — write Python in snake_case, don't hand-roll casing.
- New Nemotron use cases should go through `nemotron_client.call_nemotron_json()`
  rather than adding a second HTTP client — it already handles auth, model
  selection, and defensive JSON parsing.
- AI-generated and saved-answer values must never report `high` confidence —
  see the capping logic in `field_matcher.to_filled_field()`. This is a
  deliberate trust rule, not an oversight.
- `data/` and `.env` are gitignored — never commit real profile data or API keys.
