# SHAWNDERMIND

A DOS-flavored idea amplifier. Drop in a seed idea (or attach an image, PDF,
audio file, or text file) and SHAWNDERMIND brainstorms it into a slate of
candidate directions — picks a winner, shows the rest as TLDRs, and lets you
refine any of them with feedback.

Phosphor green. Scanlines. Blinking cursor. Voice input. Mobile-first.

## Modes

- **Quick** — one OpenAI call, ~5 seconds, 6 ideas + winner.
- **Deep** — four-stage pipeline (diverge → critique → expand → rank), ~30
  seconds. Wider divergence, sharper survivors.

## Refine after the brainstorm

Every idea card has an **Add Feedback** button. Type your feedback, then:

- **Refine This One** — rewrites just that single idea with your feedback.
- **Brainstorm Again** — re-runs the entire pipeline with the original seed
  + your prior direction + feedback as new context.

## Attachments

Supports per-brainstorm attachments:

| Type | How it's used |
|------|--------------|
| Image (jpg, png, gif, webp) | Sent to GPT-4o vision as part of the prompt |
| PDF | Server extracts text via `pypdf`, prepended as context |
| Audio (mp3, m4a, wav, webm, ogg) | Transcribed via Whisper, prepended as context |
| Text (txt, md, csv, json) | Read directly as context |

25 MB upload limit per request.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate # mac/linux
pip install -r requirements.txt

# Set your OpenAI key
copy .env.example .env     # then edit .env and paste your key
# or:  $env:OPENAI_API_KEY="sk-..."  (PowerShell)

# Boot
python -m server.app
```

Open http://localhost:5000.

## Deploy on Render

1. Push this repo to GitHub.
2. In Render → **New → Blueprint**, point at the repo (it auto-detects `render.yaml`).
3. Set the `OPENAI_API_KEY` environment variable in the Render dashboard.
4. Deploy. Done.

## Stack

- Backend: Flask + OpenAI Python SDK + pypdf + flask-cors
- Frontend: Plain HTML/CSS/JS — no build step, no framework
- Export: html2canvas (PNG), jsPDF (PDF), Web Share API
- Voice: Web Speech API (Chrome/Safari/iOS), Whisper fallback for audio uploads

## File map

```
SHAWNDERMIND/
├── server/
│   ├── app.py            # Flask app + API routes + static serving
│   └── brainstorm.py     # OpenAI calls (quick/deep/refine/transcribe/PDF)
├── public/
│   ├── index.html        # DOS terminal shell
│   ├── style.css         # Phosphor + scanlines + responsive
│   └── app.js            # All UI logic
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```
