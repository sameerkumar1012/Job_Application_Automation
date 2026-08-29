# User Stories — Job Application Auto-Fill Extension

## Profile setup
- As a job seeker, I want to upload my resume once and have it parsed into a structured profile automatically, so I don't have to manually type out my work history, education, and skills.
- As a job seeker, I want to review and edit the parsed profile, so I can correct anything Claude got wrong and fill in what a resume doesn't cover (work authorization, EEO/voluntary disclosure preferences, salary expectations, pronouns, links).
- As a job seeker, I want my resume, profile data, and API key stored only on my machine, so my personal data isn't sent anywhere I don't control.

## Filling applications
- As a job seeker, I want to click a single button on a job application page and have the extension detect and fill every field it can, so I don't have to manually re-enter the same information for every application.
- As a job seeker applying on Workday, I want the extension to handle multi-step wizards and fields buried in iframes/shadow DOM, so I'm not stuck manually filling the hardest ATS.
- As a job seeker applying on LinkedIn, I want the extension to work with LinkedIn's native apply flow, including when it redirects to a company's own ATS.
- As a job seeker, I want my resume/cover-letter file automatically attached to file-upload fields, so I don't have to manually browse and select them every time.
- As a job seeker filling out a multi-step application, I want the extension to automatically fill each page and advance to the next one on its own, so I only need to step in at the final review/submit page instead of clicking "Next" through every step myself.

## Handling hard questions
- As a job seeker, I want the AI to answer free-text questions like "why do you want to work here?" using my profile and the job posting's context, so I'm not blocked by questions a plain autofill tool can't handle.
- As a job seeker, I want similar recurring questions (e.g. "why this company") answered consistently across applications, so my application history doesn't read as contradictory if compared.

## Trust and control
- As a job seeker, I want to see which fields were filled with high vs. low confidence, so I know exactly what to double-check before submitting.
- As a job seeker, I want the extension to never submit the application on its own, so a bad AI guess can never become an application I didn't actually review.
- As a job seeker, I want the extension to only act when I explicitly trigger it (not automatically on every page load), so it doesn't burn API calls or touch pages I didn't ask it to.
- As a job seeker, I want the extension to bail out gracefully and tell me when it hits a login wall or CAPTCHA, rather than failing silently or getting stuck.
