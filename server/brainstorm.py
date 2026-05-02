"""The Idea Graveyard — OpenAI-powered brainstorm engine.

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
import random
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


# ---------- Divergence lenses ----------
# Each brainstorm randomly picks 6 of these to force genuinely different directions.

_LENSES = [
    "Flip it: what if the opposite of the obvious approach is better?",
    "Shrink it: what's the tiniest, most focused version that still works?",
    "10x it: what if budget and scale were unlimited?",
    "Wrong audience: apply this idea to a totally unexpected group of people.",
    "Analog it: remove all technology. How does this work with paper, in-person, physical?",
    "Mashup: combine the seed with an unrelated industry (food, sports, music, fashion, science).",
    "Time-shift: what if this existed 50 years ago, or 50 years from now?",
    "Villain lens: what's the dark, cynical, or subversive version?",
    "Kid-brain: how would an 8-year-old solve this? What's the stupidly simple version?",
    "Art project: treat it as a creative/artistic expression, not a business or product.",
    "One-person version: what can a single person build in a weekend?",
    "Community play: what if 1,000 strangers collaborated on this?",
    "Monetize differently: make money from the thing everyone ignores.",
    "Delete the core: remove the most 'obvious' feature. What's left?",
    "Personal angle: make it deeply autobiographical — only YOU could do this.",
    "Comedy lens: what's the funny version that still delivers real value?",
    "Luxury lens: what's the absurdly premium, high-end take?",
    "Emergency version: you have 48 hours and $100. Go.",
    "Physical-digital bridge: this idea lives in both the real world and online simultaneously.",
    "Trojan horse: disguise the real value inside something that looks like something else entirely.",
    "Seasonal/ephemeral: this only exists for a limited time, then it's gone forever.",
    "Anti-pattern: do the thing experts say you should never do.",
    "Sensory shift: what if the primary sense changes (sound-first, touch-first, smell-first)?",
    "Cultural remix: transplant this idea into a completely different culture or subculture.",
    "Rage fuel: what version of this would make people argue about it online?",
]


def _pick_lenses(n: int = 6) -> list[str]:
    return random.sample(_LENSES, min(n, len(_LENSES)))


def _lens_block(lenses: list[str]) -> str:
    lines = [f"{i+1}. {l}" for i, l in enumerate(lenses)]
    return "CREATIVE LENSES — each idea MUST use a different lens:\n" + "\n".join(lines)


# ---------- Prompt builders ----------

_SYSTEM_QUICK = """You are The Idea Graveyard — a brainstorm engine that generates genuinely different ideas, not 6 flavors of the same thing.

Rules:
- Generate 6 ideas. Each one MUST attack the seed from a fundamentally different angle.
  If two ideas could be merged without losing much, they're too similar — kill one and go weirder.
- You will receive a set of "creative lenses." Each idea must be clearly inspired by a different lens.
  Don't label which lens you used — just let it drive the direction.
- At least 1 idea should make the user uncomfortable (too ambitious, too weird, too honest).
- At least 1 idea should be laughably simple.
- Each idea: snappy title (<=8 words), one-sentence TLDR (<=160 chars), and a 2-4 paragraph
  full breakdown: what it is, why it works, concrete first step, biggest risk.
- Pick ONE winner: the most original + doable, NOT the safest.
- Write like a sharp friend, not a consultant. No corporate fluff. No "leveraging synergies."
- Be specific. Real names, real tools, real numbers. Vague = bad."""

_SYSTEM_DEEP_DIVERGE = """You are The Idea Graveyard in DEEP mode (Diverge stage).

Generate 12 wildly different candidate directions for the seed.

You will receive creative lenses. Use them to force genuine variety — each candidate
should feel like it came from a different person's brain.

Requirements:
- At least 2 should be contrarian or uncomfortable.
- At least 2 should be surprisingly small/simple.
- At least 2 should be ambitious/weird.
- NO two candidates should share the same core mechanic or audience.
- Each gets only a title + 1-line hook. No filler, no hedging.

Output JSON: {"candidates":[{"id","title","hook"}]}"""

_SYSTEM_DEEP_CRITIQUE = """You are The Idea Graveyard in DEEP mode (Critique stage).

Score each candidate 0-10 on:
- Originality (is this surprising? could only THIS person think of it?)
- Executability (can someone actually start this within a week?)
- Divergence (how different is it from the OTHER candidates?)

PUNISH sameness. If two candidates are similar, dock BOTH.
Eliminate the weakest. Return the top 6 with brief reasons.

Output JSON: {"survivors":[{"id","title","hook","score","reason"}]}"""

_SYSTEM_DEEP_EXPAND = """You are The Idea Graveyard in DEEP mode (Expand stage).

For each surviving candidate, write the full version:
- What it is (be specific — names, tools, formats, real details)
- Why it works (the non-obvious insight)
- First concrete step (something doable THIS WEEK)
- Biggest risk (be honest, not hand-wavy)

2-4 paragraphs each. Write like a sharp friend, not a consultant.
If you catch yourself writing "leveraging" or "fostering" — stop and rewrite that sentence."""

_SYSTEM_DEEP_RANK = """You are The Idea Graveyard in DEEP mode (Rank stage).

Pick the single winner. Criteria:
1. Would someone actually remember this idea tomorrow? (memorability)
2. Could someone start on it this week? (executability)
3. Is it genuinely different from what already exists? (originality)

Do NOT pick the safest idea. Pick the one with the most interesting failure mode.
Explain in 2-3 sentences why it wins."""

_SYSTEM_REFINE_ONE = """You are The Idea Graveyard refining a single idea.

The user wants you to revise this idea based on their feedback.
Push it further — don't just patch, actually improve.
Be more specific, more honest, more surprising.
Keep the same id. Output the revised idea only."""


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
        temperature=1.0,
    )
    raw = resp.choices[0].message.content or "{}"
    return json.loads(raw)


def _free_form_call(
    *,
    model: str,
    system: str,
    user_content: list[dict] | str,
    temperature: float = 1.0,
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
    lenses = _pick_lenses(6)
    user_content = _build_user_content(seed, context, images)
    if isinstance(user_content, list):
        user_content[0]["text"] += "\n\n" + _lens_block(lenses)
    else:
        user_content += "\n\n" + _lens_block(lenses)
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
    lenses = _pick_lenses(12)
    user_content = _build_user_content(seed, context, images)
    if isinstance(user_content, list):
        user_content[0]["text"] += "\n\n" + _lens_block(lenses)
    else:
        user_content += "\n\n" + _lens_block(lenses)

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
