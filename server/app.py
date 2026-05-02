"""The Idea Graveyard Flask app — serves static frontend + brainstorm API."""
from __future__ import annotations

import os
import re
import traceback
from html.parser import HTMLParser
from urllib.request import urlopen, Request
from urllib.error import URLError

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

load_dotenv()

from . import brainstorm

PUBLIC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "public")
)

app = Flask(__name__, static_folder=None)
CORS(app)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


# ---------- Health check ----------

@app.route("/healthz")
def healthz():
    return jsonify(ok=True, key_set=bool(os.environ.get("OPENAI_API_KEY")))


# ---------- API ----------

_IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}
_AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/x-m4a",
    "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg",
}
_PDF_MIMES = {"application/pdf"}
_TEXT_MIMES = {"text/plain", "text/markdown", "text/csv", "application/json"}


def _process_attachments(files) -> tuple[str, list[dict]]:
    """Convert uploaded files into (context_text, images_list).

    - Images become data URLs for vision
    - PDFs become extracted text appended to context
    - Audio becomes Whisper-transcribed text appended to context
    - Text files appended to context as-is
    """
    context_parts: list[str] = []
    images: list[dict] = []
    for f in files:
        if not f or not f.filename:
            continue
        data = f.read()
        if not data:
            continue
        mime = (f.mimetype or "").lower()
        name = f.filename
        if mime in _IMAGE_MIMES or name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            url = brainstorm.file_to_data_url(data, mime or "image/png")
            images.append({"name": name, "data_url": url})
        elif mime in _PDF_MIMES or name.lower().endswith(".pdf"):
            try:
                text = brainstorm.extract_pdf_text(data)
                if text:
                    context_parts.append(f"[PDF: {name}]\n{text}")
            except Exception as e:
                context_parts.append(f"[PDF: {name}] (failed to read: {e})")
        elif mime in _AUDIO_MIMES or name.lower().endswith((".mp3", ".m4a", ".wav", ".webm", ".ogg", ".mp4")):
            try:
                transcript = brainstorm.transcribe_audio(data, name)
                if transcript:
                    context_parts.append(f"[Audio: {name}]\nTranscript: {transcript}")
            except Exception as e:
                context_parts.append(f"[Audio: {name}] (transcription failed: {e})")
        elif mime in _TEXT_MIMES or name.lower().endswith((".txt", ".md", ".csv", ".json")):
            try:
                context_parts.append(f"[File: {name}]\n{data.decode('utf-8', errors='replace')[:30_000]}")
            except Exception:
                pass
        else:
            context_parts.append(f"[Skipped unsupported file: {name} ({mime})]")
    return ("\n\n".join(context_parts), images)


_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')
_MAX_URL_CHARS = 12_000


class _TextExtractor(HTMLParser):
    """Strips HTML tags, keeps text."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, _):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _fetch_url_text(url: str) -> str | None:
    """Fetch a URL and return its text content (HTML stripped)."""
    try:
        req = Request(url, headers={"User-Agent": "IdeaGraveyard/1.0"})
        with urlopen(req, timeout=8) as resp:
            ct = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ct and "text" not in ct:
                return None
            raw = resp.read(200_000).decode("utf-8", errors="replace")
        ex = _TextExtractor()
        ex.feed(raw)
        text = ex.get_text().strip()
        text = re.sub(r'\s+', ' ', text)
        return text[:_MAX_URL_CHARS] if text else None
    except (URLError, OSError, ValueError):
        return None


def _extract_urls_as_context(seed: str) -> str:
    """Find URLs in seed text, fetch them, return combined context."""
    urls = _URL_RE.findall(seed)
    if not urls:
        return ""
    parts: list[str] = []
    for url in urls[:3]:
        text = _fetch_url_text(url)
        if text:
            parts.append(f"[URL: {url}]\n{text}")
    return "\n\n".join(parts)


@app.route("/api/brainstorm", methods=["POST"])
def api_brainstorm():
    try:
        seed = (request.form.get("seed") or "").strip()
        mode = (request.form.get("mode") or "quick").strip().lower()
        if not seed and not request.files:
            return jsonify(error="seed required"), 400

        context, images = _process_attachments(request.files.getlist("attachments"))

        url_context = _extract_urls_as_context(seed)
        if url_context:
            context = (url_context + "\n\n" + context).strip() if context else url_context

        if not seed:
            seed = "(see attached context)"

        if mode == "deep":
            result = brainstorm.brainstorm_deep(seed, context, images)
        else:
            result = brainstorm.brainstorm_quick(seed, context, images)

        return jsonify(ok=True, mode=mode, seed=seed, **result)
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, error=f"{type(e).__name__}: {e}"), 500


@app.route("/api/refine", methods=["POST"])
def api_refine():
    """Refine ONE idea with feedback. JSON body."""
    try:
        body = request.get_json(force=True) or {}
        idea = body.get("idea") or {}
        feedback = (body.get("feedback") or "").strip()
        seed = (body.get("seed") or "").strip()
        if not idea or not feedback:
            return jsonify(error="idea and feedback required"), 400
        revised = brainstorm.refine_idea(
            idea=idea, feedback=feedback, seed=seed,
        )
        return jsonify(ok=True, idea=revised)
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, error=f"{type(e).__name__}: {e}"), 500


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """Standalone Whisper transcription (used by voice-input flow if Web Speech API unavailable)."""
    try:
        f = request.files.get("audio")
        if not f or not f.filename:
            return jsonify(error="audio file required"), 400
        text = brainstorm.transcribe_audio(f.read(), f.filename)
        return jsonify(ok=True, text=text)
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, error=f"{type(e).__name__}: {e}"), 500


# ---------- Static frontend (catch-all MUST be last) ----------

@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    target = os.path.join(PUBLIC_DIR, filename)
    if os.path.isfile(target):
        return send_from_directory(PUBLIC_DIR, filename)
    return send_from_directory(PUBLIC_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
