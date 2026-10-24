# Job Apply Copilot

Fills out job application forms from a locally-stored profile, using NVIDIA's Nemotron LLM for resume parsing and free-text answers. **It never submits an application itself — the user always reviews and clicks submit.**

## What it does

- Upload a resume once; it's parsed into a structured profile (work history, education, skills) you can review and edit.
- Fill in what a resume doesn't cover: work authorization, EEO/voluntary disclosure preferences, salary expectations, pronouns, links.
- Click one button on a job application page to detect and fill every field the extension can handle.
- Handles multi-step application wizards, fields inside iframes/shadow DOM (e.g. Workday), and LinkedIn's native apply flow, including redirects to a company's own ATS.
- Auto-attaches a resume/cover letter to file-upload fields.
- Answers free-text questions (e.g. "why do you want to work here?") using the stored profile and the job posting's context, with similar recurring questions answered consistently.
- Flags each filled field with a confidence level, so the user knows exactly what to double-check before submitting.
- Detects login walls and CAPTCHAs and stops rather than failing silently or getting stuck.
- Only acts when explicitly triggered — never runs automatically on page load.

## Architecture

Two halves, split by what each language is forced to do:

- **`server/` (Python/Flask)** — owns everything: profile storage, resume parsing, field-matching heuristics, Nemotron API calls, the submit-safety heuristic, login-wall/CAPTCHA detection, and a server-rendered profile editor UI. All personal data stays local; nothing leaves the machine except the Nemotron API calls.
- **`extension/` (vanilla JS, Manifest V3)** — the irreducible minimum Chrome forces into JavaScript: reading the page DOM and applying values to it. It holds no business logic and no personal data. `background.js` is the only file that talks to the local server (`http://127.0.0.1:8765`); `content.js` never calls `fetch()` itself, so all network calls are relayed through the background service worker, keeping the safety-critical decisions (which field matches which profile attribute, whether a page is a login wall) entirely in Python where they can be tested with pytest.

This is a from-scratch rewrite of an earlier TypeScript/Claude-based design, switched to an NVIDIA Nemotron API key and to doing as much of the implementation as possible in Python.

## Tech stack

Python, Flask, Pydantic, NVIDIA Nemotron API, Chrome Extension (Manifest V3, vanilla JS), pytest
