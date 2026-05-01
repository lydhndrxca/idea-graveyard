"""SHAWNDERMIND — OpenAI-powered brainstorm engine.

Two modes:
  - quick: one structured-output call -> 6 ideas with TLDR + full + #1 pick
  - deep:  4 stages (diverge -> critique -> expand -> rank) for richer ideas

Plus single-idea refinement and re-brainstorm-with-feedback.

All calls use OpenAI's structured outputs (JSON schema) so the frontend
can render predictably without parsing prose.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from openai import OpenAI

_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_DEEP_MODEL = os.environ.get("OPENAI_DEEP_MODEL", _DEFAULT_MODEL)
_TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")


def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env locally or to the Render dashboard."
        )
    return OpenAI(api_key=api_key)


# ---------- JSON schemas ----------

_BRAINSTORM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["winner_id", "ideas", "rationale"],
    "properties": {
        "winner_id": {"type": "string", "description": "id of the chosen #1 idea"},
        "rationale": {
            "type": "string",
            "description": "Why the #1 idea won (2-3 sentences).",
        },
        "ideas": {
            "type": "array",
            "minItems": 4,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title", "tldr", "full"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string", "description": "Snappy title (<=8 words)"},
                    "tldr": {
                        "type": "string",
                        "description": "One-sentence summary, <=160 chars.",
                    },
                    "full": {
                        "type": "string",
                        "description": "2-4 paragraph fleshed-out idea: what it is, why it works, how to start, risks.",
                    },
                },
            },
        },
    },
}

_REFINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "title", "tldr", "full"],
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "tldr": {"type": "string"},
        "full": {"type": "string"},
    },
}


# ---------- Prompt builders ----------

_SYSTEM_QUICK = """You are SHAWNDERMIND, a fast, sharp brainstorm engine.

You take a seed idea (and any attached context/images) and produce a tight
slate of distinct, high-quality candidate directions.

Rules:
- Generate 6 ideas, each meaningfully different from the others (different angle,
  audience, mechanic, or domain — not 6 variations of the same thing).
- Each idea: snappy title, one-sentence TLDR (<=160 chars), and a 2-4 paragraph
  full breakdown covering: what it is, why it works, first concrete step, biggest risk.
- Pick exactly ONE winner. Choose the most original + executable, not the safest.
- Use the user's tone. Be direct. No corporate fluff. No hedging."""

_SYSTEM_DEEP_DIVERGE = """You are SHAWNDERMIND in DEEP mode (Diverge stage).

Generate 12 wildly different candidate directions for the seed. Push range:
include weird, contrarian, ambitious, and lateral options. Each candidate
gets only a title + 1-line hook. No filler.

Output JSON: {"candidates":[{"id","title","hook"}]}"""

_SYSTEM_DEEP_CRITIQUE = """You are SHAWNDERMIND in DEEP mode (Critique stage).

Score each candidate 0-10 on (originality, executability, fit-to-seed).
Eliminate the weakest. Return the top 6 with brief reasons.

Output JSON: {"survivors":[{"id","title","hook","score","reason"}]}"""

_SYSTEM_DEEP_EXPAND = """You are SHAWNDERMIND in DEEP mode (Expand stage).

For each surviving candidate, write the full version: what it is, why it works,
first concrete step, biggest risk. 2-4 paragraphs each. Match the user's tone."""

_SYSTEM_DEEP_RANK = """You are SHAWNDERMIND in DEEP mode (Rank stage).

Pick the single winner from the expanded ideas. Pick for originality + executability,
not safety. Explain in 2-3 sentences why it beats the others."""

_SYSTEM_REFINE_ONE = """You are SHAWNDERMIND refining a single idea.

The user is happy with the direction but wants you to revise this specific idea
based on their feedback. Keep the same id. Output the revised idea only."""


# ---------- Helpers ----------

def _build_user_content(seed: str, context: str, images: list[dict] | None) -> list[dict]:
    """Build a multimodal user content list (text + image blocks)."""
    text = f"SEED IDEA:\n{seed.strip()}"
    if context.strip():
        text += f"\n\nADDITIONAL CONTEXT (from attachments):\n{context.strip()}"
    parts: list[dict] = [{"type": "text", "text": text}]
    if images:
        for img in images:
            parts.append({
                "type": "image_url",
                "image_url": {"url": img["data_url"], "detail": "auto"},
            })
    return parts


def _structured_call(
    *,
    model: str,
    system: str,
    user_content: list[dict] | str,
    schema: dict,
    schema_name: str,
) -> dict[str, Any]:
    """Call OpenAI chat.completions with JSON schema enforcement."""
    client = _client()
    if isinstance(user_content, str):
        user_msg = {"role": "user", "content": user_content}
    else:
        user_msg = {"role": "user", "content": user_content}
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, user_msg],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema, "strict": True},
        },
        temperature=0.9,
    )
    raw = resp.choices[0].message.content or "{}"
    return json.loads(raw)


def _free_form_call(
    *,
    model: str,
    system: str,
    user_content: list[dict] | str,
    temperature: float = 0.9,
) -> str:
    client = _client()
    user_msg = {"role": "user", "content": user_content}
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, user_msg],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


# ---------- Public API ----------

def brainstorm_quick(
    seed: str,
    context: str = "",
    images: list[dict] | None = None,
) -> dict[str, Any]:
    """One-shot brainstorm. ~5 seconds, 1 OpenAI call."""
    user_content = _build_user_content(seed, context, images)
    return _structured_call(
        model=_DEFAULT_MODEL,
        system=_SYSTEM_QUICK,
        user_content=user_content,
        schema=_BRAINSTORM_SCHEMA,
        schema_name="brainstorm_result",
    )


def brainstorm_deep(
    seed: str,
    context: str = "",
    images: list[dict] | None = None,
) -> dict[str, Any]:
    """4-stage deep brainstorm. ~30 seconds, 4 OpenAI calls.

    Stages: diverge (12 candidates) -> critique (top 6) -> expand (full ideas)
    -> rank (pick #1 + rationale). Returns the same shape as quick.
    """
    user_content = _build_user_content(seed, context, images)

    diverge_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array", "minItems": 8, "maxItems": 14,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "title", "hook"],
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                    },
                },
            },
        },
    }
    diverged = _structured_call(
        model=_DEEP_MODEL, system=_SYSTEM_DEEP_DIVERGE,
        user_content=user_content, schema=diverge_schema, schema_name="diverge",
    )

    critique_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["survivors"],
        "properties": {
            "survivors": {
                "type": "array", "minItems": 4, "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "title", "hook", "score", "reason"],
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    }
    critique_input = (
        f"SEED:\n{seed}\n\nCANDIDATES:\n{json.dumps(diverged['candidates'], indent=2)}"
    )
    critiqued = _structured_call(
        model=_DEEP_MODEL, system=_SYSTEM_DEEP_CRITIQUE,
        user_content=critique_input, schema=critique_schema, schema_name="critique",
    )

    expand_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ideas"],
        "properties": {
            "ideas": {
                "type": "array", "minItems": 4, "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "title", "tldr", "full"],
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "tldr": {"type": "string"},
                        "full": {"type": "string"},
                    },
                },
            },
        },
    }
    expand_input = (
        f"SEED:\n{seed}\n\nCONTEXT:\n{context}\n\nSURVIVORS:\n"
        f"{json.dumps(critiqued['survivors'], indent=2)}"
    )
    expanded = _structured_call(
        model=_DEEP_MODEL, system=_SYSTEM_DEEP_EXPAND,
        user_content=expand_input, schema=expand_schema, schema_name="expand",
    )

    rank_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["winner_id", "rationale"],
        "properties": {
            "winner_id": {"type": "string"},
            "rationale": {"type": "string"},
        },
    }
    rank_input = (
        f"SEED:\n{seed}\n\nIDEAS:\n{json.dumps(expanded['ideas'], indent=2)}"
    )
    ranked = _structured_call(
        model=_DEEP_MODEL, system=_SYSTEM_DEEP_RANK,
        user_content=rank_input, schema=rank_schema, schema_name="rank",
    )

    return {
        "winner_id": ranked["winner_id"],
        "rationale": ranked["rationale"],
        "ideas": expanded["ideas"],
    }


def refine_idea(
    *,
    idea: dict,
    feedback: str,
    seed: str = "",
    context: str = "",
    images: list[dict] | None = None,
) -> dict:
    """Refine a single idea with user feedback. Keeps the same id."""
    text = (
        f"ORIGINAL SEED:\n{seed}\n\n"
        f"IDEA TO REFINE:\n{json.dumps(idea, indent=2)}\n\n"
        f"USER FEEDBACK:\n{feedback}\n\n"
        "Revise the idea above to incorporate the feedback. Keep the same id. "
        "Return the revised idea only."
    )
    if context.strip():
        text = f"ATTACHMENT CONTEXT:\n{context}\n\n" + text
    parts: list[dict] = [{"type": "text", "text": text}]
    if images:
        for img in images:
            parts.append({
                "type": "image_url",
                "image_url": {"url": img["data_url"], "detail": "auto"},
            })
    return _structured_call(
        model=_DEFAULT_MODEL, system=_SYSTEM_REFINE_ONE,
        user_content=parts, schema=_REFINE_SCHEMA, schema_name="refined_idea",
    )


def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """Transcribe an audio file via Whisper."""
    client = _client()
    import io
    bio = io.BytesIO(file_bytes)
    bio.name = filename or "audio.mp3"
    resp = client.audio.transcriptions.create(
        model=_TRANSCRIBE_MODEL,
        file=bio,
    )
    return resp.text


def extract_pdf_text(file_bytes: bytes, max_chars: int = 30_000) -> str:
    """Extract text from a PDF (truncated to max_chars to keep prompts sane)."""
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(file_bytes))
    chunks: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if not t:
            continue
        chunks.append(t)
        total += len(t)
        if total >= max_chars:
            break
    out = "\n\n".join(chunks).strip()
    if len(out) > max_chars:
        out = out[:max_chars] + "\n\n[...truncated]"
    return out


def file_to_data_url(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"
