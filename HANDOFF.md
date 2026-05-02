# SHAWNDERMIND — Project Handoff & Status

**Date:** May 1, 2026
**Local path:** `C:\Dev\SHAWNDERMIND`
**Status:** v1 complete locally, pushed to GitHub branch only, **not yet deployed**.

---

## 1. What this project is

A DOS-flavored web app that turns a seed idea (text, voice, image, PDF, or audio)
into a brainstormed slate of candidate directions, picks a winner, and lets the
user refine any idea with feedback or re-brainstorm with that feedback baked in.

Built for iPhone + desktop. Public site. Single shared OpenAI key (held server-side).

### Look & feel
Phosphor green on black. VT323 monospace. CRT scanlines with subtle flicker.
Blinking cursor. Amber accents on the winning idea. ASCII logo. Old DOS terminal vibe.

### Core flow
```
seed idea (+ optional attachments)
    -> pick QUICK or DEEP mode
    -> AI brainstorms
    -> show #1 winner expanded + alternates as TLDR cards
    -> tap any card to expand
    -> per-card: ADD FEEDBACK -> "Refine This One" or "Brainstorm Again"
    -> per-card: SAVE PNG | SAVE PDF | SHARE
```

---

## 2. Decisions already locked in

| Decision | Choice | Why |
|----------|--------|-----|
| API key model | Server-side (single key in Render env var) | User said "use renderer" — so backend proxy holds the key, public users don't need their own |
| Hosting | Render (web service, Flask + gunicorn) | Same as Chess-Federation pattern |
| Modes | **2 modes**: Quick + Deep | User chose 2-mode |
| Quick mode | 1 OpenAI call, ~5s, 6 ideas + winner | Single structured-output call |
| Deep mode | 4 stages (diverge -> critique -> expand -> rank), ~30s | Adapted from Madison_AI_Suite's 10-stage pipeline |
| Tech stack | Flask backend + plain HTML/CSS/JS frontend, no build step | Simplest possible deploy |
| Default model | `gpt-4o-mini` (env: `OPENAI_MODEL`) | Cheap + fast + has vision |
| Audio | Whisper (`whisper-1`) for transcription | Server-side, attachment uploads |
| PDF | `pypdf` extracts text server-side, prepended as context | |
| Image | Sent as base64 data URL to GPT-4o vision | |
| Voice input | Web Speech API (iOS Safari + Chrome native) | Free, no extra API call |
| Export per idea | PNG (html2canvas), PDF (jsPDF multi-page), Web Share | |

### Reference source
Pulled inspiration from `C:\Users\shawn\ai-toolkit\Madison_AI_Suite\src\pubg_madison_ai_suite\api\routes\brainstorm.py`
and `C:\Users\shawn\ai-toolkit\frontend\src\lib\brainstorm\` (10-stage Gemini pipeline).
SHAWNDERMIND is a simplified, OpenAI-backed, standalone version.

---

## 3. NEW requirements added during build (already implemented)

1. **Per-idea refinement** — user wanted to add feedback to any idea after seeing it, then either rewrite just that one OR re-brainstorm with feedback as new context. Both are wired up via `/api/refine` (single rewrite) and the front-end re-uses `/api/brainstorm` with augmented seed (full re-pipeline).
2. **Multi-attachment input** — image, PDF, audio, text. All handled in `_process_attachments()` in [server/app.py](server/app.py).

---

## 4. What's built (file map)

```
C:\Dev\SHAWNDERMIND\
├── server/
│   ├── __init__.py
│   ├── app.py                # Flask app, routes, attachment handling, static serving
│   └── brainstorm.py         # OpenAI calls: quick/deep/refine/transcribe/PDF extract
├── public/
│   ├── index.html            # DOS terminal shell (boot header, input, results, loading)
│   ├── style.css             # Phosphor + scanlines + responsive (mobile-first)
│   └── app.js                # All UI logic (vanilla JS, no framework)
├── requirements.txt          # flask, flask-cors, openai, gunicorn, dotenv, pypdf
├── render.yaml               # Render blueprint (gunicorn, OPENAI_API_KEY env var)
├── .env.example              # Template for local OPENAI_API_KEY
├── .gitignore                # .venv, .env, __pycache__, etc.
├── README.md                 # Public-facing docs
└── HANDOFF.md                # This file
```

### Key files & what they do

- **[server/brainstorm.py](server/brainstorm.py)** — All OpenAI logic. Functions:
  - `brainstorm_quick(seed, context, images)` — 1 call, structured JSON
  - `brainstorm_deep(seed, context, images)` — 4 calls, returns same shape as quick
  - `refine_idea(idea, feedback, seed, context, images)` — single-idea rewrite
  - `transcribe_audio(bytes, filename)` — Whisper
  - `extract_pdf_text(bytes, max_chars=30000)` — pypdf
  - `file_to_data_url(bytes, mime)` — base64 image helper

- **[server/app.py](server/app.py)** — Flask routes:
  - `GET /` and `GET /<filename>` — serve `public/`
  - `GET /healthz` — `{ok, key_set}` for monitoring
  - `POST /api/brainstorm` — multipart form: `seed`, `mode`, `attachments[]`
  - `POST /api/refine` — JSON: `{idea, feedback, seed}`
  - `POST /api/transcribe` — multipart: `audio` (standalone Whisper endpoint)

- **[public/app.js](public/app.js)** — Frontend logic:
  - View switching (input / loading / results)
  - Attachment list management with kind detection
  - Web Speech API voice input (Chrome/Safari native)
  - Brainstorm fetch + loading animation
  - Idea card rendering, expand/collapse, refinement panel
  - Export: html2canvas + jsPDF + navigator.share
  - Cmd/Ctrl+Enter shortcut to submit

- **[public/style.css](public/style.css)** — Pure CSS, no framework. CRT effects via overlay div + repeating-linear-gradient + flicker animation.

---

## 5. Local smoke test results (already passed)

- App boots clean on port 5050 via `.venv\Scripts\python.exe -m server.app`
- `GET /` -> 200 (DOS UI)
- `GET /style.css`, `/app.js` -> 200
- `GET /healthz` -> `{"key_set": false, "ok": true}` (no key set locally)
- `POST /api/brainstorm` without key -> 500 with clean error: `"OPENAI_API_KEY is not set..."`
- `POST /api/refine` missing fields -> 400: `"idea and feedback required"`

OpenAI calls themselves were NOT live-tested — no key was set during smoke test.
First real test should be after deploy with the key in Render's env vars.

---

## 6. Git / GitHub status — IMPORTANT

**Local commits:** 1 commit on branch `v2-flask-rebuild` (`cfdf5f4`).

**Remote:** Pushed to existing repo `lydhndrxca/ShawnderMind` on a NEW branch `v2-flask-rebuild`:
- URL: https://github.com/lydhndrxca/ShawnderMind/tree/v2-flask-rebuild

**The complication:** `lydhndrxca/ShawnderMind` already had content on `main` from a previous attempt — React/Vite/Electron + governance docs (SPEC.md, TASKS.md, DECISIONS.md, ARCHITECTURE.md, AUDITS, etc.). I did NOT touch `main`. The old version is still there.

### Three paths forward (user has not yet chosen)

1. **Make my branch the new main on the existing repo.**
   - `gh repo edit lydhndrxca/ShawnderMind --default-branch v2-flask-rebuild`
   - Old `main` stays as a backup branch.
2. **Create a brand-new GitHub repo** (user asked about this last) — I'd need a name (suggested: `shawndermind`).
   - Then push the local code there as `main`
   - Then delete the `v2-flask-rebuild` branch I pushed earlier
3. **Open a PR** at https://github.com/lydhndrxca/ShawnderMind/pull/new/v2-flask-rebuild and merge through GitHub UI.

**Last user message in old chat:** "cant u just make it its own new project on my renderer accoutn" — they want option 2, a fresh standalone setup.

---

## 7. Render status — NOTHING DEPLOYED YET

No Render service exists for SHAWNDERMIND yet. The `render.yaml` is ready.

### Render API access
The agent has Render API access via Chess-Federation's `.cursor/rules/render-deploy.mdc`:
- API key in `C:\Dev\Chess-Federation\enoch_server\.env` as `RENDER_API_KEY`
- Endpoint: `https://api.render.com/v1`

### Deploy plan (next steps when user re-opens this folder in Cursor)

When user confirms repo name + path:

1. Create new GitHub repo (e.g. `gh repo create lydhndrxca/shawndermind --public --source=. --remote=origin --push`).
2. Use Render API to create a new web service:
   - `POST https://api.render.com/v1/services`
   - Type: `web_service`, runtime: `python`
   - Repo URL pointing at the new repo
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn server.app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - Health check: `/healthz`
3. Set env vars via `PUT /services/{id}/env-vars`:
   - `OPENAI_API_KEY` — required, ask user
   - `OPENAI_MODEL` — defaults to `gpt-4o-mini`
4. Trigger first deploy: `POST /services/{id}/deploys`.
5. Verify with `GET /healthz` -> should return `{"key_set": true}`.

---

## 8. To open in proper Cursor workspace

```
File -> Open Folder -> C:\Dev\SHAWNDERMIND
```

This `HANDOFF.md` should be the first file the next agent reads. The other docs to scan:
- [README.md](README.md) — public-facing usage
- [render.yaml](render.yaml) — deploy blueprint
- [server/brainstorm.py](server/brainstorm.py) — heart of the app

---

## 9. To run locally right now

```powershell
cd C:\Dev\SHAWNDERMIND
copy .env.example .env
# edit .env, paste your OPENAI_API_KEY
.venv\Scripts\python.exe -m server.app
# open http://localhost:5000
```

(`.venv` is already created and dependencies are installed.)

---

## 10. Critical guardrails for the next agent

- **Do NOT force-push to `lydhndrxca/ShawnderMind` `main`.** The user's old version is still there. Get explicit confirmation before destroying it.
- **Do NOT commit `.env`.** It's in `.gitignore` already.
- **The OpenAI key is sensitive.** Never log it, never echo it, never put it in a commit.
- **`OPENAI_API_KEY` must be set as a Render env var, NOT hardcoded.** Same pattern as Chess-Federation's `SECRET_KEY`.
- **The 25 MB upload limit** in `server/app.py` (`MAX_CONTENT_LENGTH`) is intentional — Whisper has a 25 MB hard cap.

---

## 11. Open questions waiting for user answer

1. **Repo name** for the brand-new GitHub repo (suggested: `shawndermind` or `shawnder-mind` — all-lowercase preferred for URLs).
2. **Delete the `v2-flask-rebuild` branch** on the old `ShawnderMind` repo after creating the new one? (Recommended: yes, to avoid confusion.)
3. **OpenAI API key** — needed to set as a Render env var on first deploy.
