# Strategy — Job Apply Copilot

## Overview

Job Apply Copilot auto-fills job applications from a locally-stored profile, using
NVIDIA's Nemotron LLM API for resume parsing and free-text question answers. It
never submits an application on its own — the user always reviews and clicks
submit themselves.

**Architecture**: a local Python (Flask) server owns all data and logic (profile
storage, resume parsing, field matching, Nemotron calls, safety heuristics), paired
with a minimal, framework-free Chrome extension that only does what Chrome forces
into JavaScript — reading the page DOM and applying values to it. The extension
holds no business logic and no personal data; the browser never talks to Nemotron
directly.

This is a rewrite of an earlier TypeScript/Claude-based design. That approach was
scrapped in favor of: (1) an NVIDIA Nemotron API key instead of Anthropic's, and
(2) doing as much of the implementation as possible in Python rather than
TypeScript/React.

## Completed (current state)

**Python backend (`server/`)**
- `models.py` — Pydantic domain model (Profile, WorkExperience, Education, EEO,
  WorkAuthorization, FillStepResult, etc.), camelCase on the wire.
- `storage.py` — local JSON-file persistence under `data/` (profile, settings,
  raw resume/cover-letter bytes). Nothing leaves the machine except Nemotron calls.
- `nemotron_client.py` — calls NVIDIA's OpenAI-compatible Nemotron endpoint,
  forces JSON-only responses via prompt instructions, with a defensive parser
  that handles fenced, unfenced, and prose-wrapped JSON.
- `resume_parser.py` — PDF (`pypdf`) / DOCX (`python-docx`) text extraction,
  then Nemotron-based structuring into profile fields.
- `field_matcher.py` — deterministic (no-LLM) matching of detected page fields
  to profile data: name/email/phone/links, work authorization, EEO (respects
  the user's opt-in/opt-out for voluntary disclosure), salary, skills.
- `question_cache.py` — normalizes recurring free-text questions ("why this
  company," "greatest strength," etc.) to canonical signatures so answers stay
  consistent across applications; company-specific questions are regenerated
  but anchored to the previous answer's substance and tone.
- `page_safety.py` — rule-based CAPTCHA and login-wall detection, conservative
  by design (defaults to *not* blocking on ambiguous signals).
- `fill_engine.py` — orchestrates a fill pass: block-check first, then per-field
  matching/AI-answering, then the submit-safety heuristic (see below).
- `routes/api_routes.py` — JSON API the extension calls (`/api/health`,
  `/api/settings`, `/api/fill`, `/api/resume-file`, `/api/cover-letter-file`).
- `routes/ui_routes.py` + `templates/` — server-rendered profile editor, resume
  upload, and settings pages (plain HTML forms, no build step, no framework).

**Chrome extension (`extension/`)**
- `manifest.json` — MV3, hand-written, no build step.
- `background.js` — the only file that calls `fetch()` (avoids target-page CSP
  restrictions on `localhost` calls from a content script); enumerates frames,
  aggregates scan results, drives the bounded multi-step-wizard loop, relays
  resume/cover-letter file bytes for auto-attach.
- `content.js` — dumb DOM scanner/applier: detects fillable fields (incl. open
  shadow roots) and buttons, applies values it's told to, clicks at most one
  button per step. Makes no matching or navigation decisions itself.
- `popup.html`/`popup.js`/`popup.css` — "Fill this page" button, confidence-badged
  results, blocked-state banner, auto-advance toggle, link to the profile editor.

**Safety invariants enforced**
- Nothing runs until the user clicks "Fill this page" in the popup.
- Every filled value carries a confidence level (high/medium/low); AI-generated
  and saved-answer values are always capped at `medium`, never `high`.
- The submit-vs-next button heuristic (`fill_engine.py`) excludes anything that
  looks like a final Submit/Apply button *before* considering Next-style
  candidates, and does nothing at all when the Next candidate is ambiguous
  (zero or multiple matches) — it never guesses.
- Login-wall/CAPTCHA detection short-circuits a fill pass before any field
  matching or Nemotron call happens.
- `NVIDIA_API_KEY` lives only in `.env` on the user's machine; the server binds
  to `127.0.0.1` only, never externally reachable.

**Tests**: `tests/` covers the safety-critical paths — submit/next button
classification (including the ambiguous "Next: Submit" label), login-wall
false-positive avoidance, Nemotron's defensive JSON parsing, question-signature
normalization, and deterministic field matching (including EEO opt-out behavior).
All Nemotron calls are mocked; no real network access or API key needed to test.

## Tech stack

- **Backend**: Python 3, Flask, Flask-CORS, Pydantic, `python-dotenv`, `requests`,
  `pypdf`, `python-docx`, Jinja2 (via Flask), pytest.
- **LLM**: NVIDIA NIM Nemotron models via the OpenAI-compatible
  `https://integrate.api.nvidia.com/v1/chat/completions` endpoint.
- **Extension**: Manifest V3, vanilla JavaScript (no TypeScript, no React, no
  build tooling) — `background.js`, `content.js`, `popup.*`.
- **Storage**: local JSON files under `data/` (gitignored); no database, no cloud.
- **Config**: `.env` / `.env.example` for `NVIDIA_API_KEY`, `NVIDIA_MODEL`,
  `PORT`, `FLASK_DEBUG`.

## Roadmap

**Phase 1 — Foundation (done)**: backend skeleton, extension shell, profile
editor, resume parsing, deterministic field matching, submit-safety heuristic,
login-wall/CAPTCHA detection, tests.

**Phase 2 — Real-world field coverage**
- Multi-row repeatable sections (Workday's "Add Another Position") — currently
  only the most recent single work/education entry is matched.
- Broader field-matching heuristics as real ATS forms surface edge cases
  (autocomplete-attribute matching, split-address fields, phone-format
  normalization).
- LinkedIn's native apply flow and its redirect-to-company-ATS behavior.

**Phase 3 — File attachment robustness**
- Resume/cover-letter auto-attach is wired (background.js fetches the stored
  bytes and reconstructs a `File` for the target input) but only triggers on
  label-keyword matches ("resume", "cv", "cover letter") — broaden detection
  and add a cover-letter upload/edit page (currently text/bytes are stored but
  there's no dedicated UI for it, unlike resume).

**Phase 4 — Trust & UX polish**
- Wizard step-advance currently waits a fixed ~1s for the page to settle between
  steps; replace with a MutationObserver-based real settle-detector.
- Popup result list could use per-field "accept/edit" controls instead of a
  read-only summary.
- Surface a live progress indicator during multi-step runs (popup already
  reflects `chrome.storage.session` state, but a step counter would help).

**Explicitly out of scope for now (documented limitations, not bugs)**
- Closed shadow roots are inaccessible to content scripts — no workaround exists.
- Legacy `.doc` (pre-2007 Word binary format) resumes are unsupported.
- Saved-answer matching uses a fixed regex archetype list, not semantic/embedding
  similarity — good enough for common recurring questions, not exhaustive.
