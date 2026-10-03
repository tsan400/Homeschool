"""Reads handwritten answers with Claude vision. Transcription only: no solving, no grading."""

import base64
import json

import anthropic

from hs import config

SYSTEM = """You transcribe children's handwritten answers from scanned worksheet answer boxes.

Write down exactly what the child wrote. Do not solve the problem, fix mistakes, or guess what they meant.
Use plain ASCII:
- fractions as a/b (a stacked fraction becomes a/b), mixed numbers as "2 3/4"
- division remainders as "12 R3"
- negative numbers with a leading "-"
- decimals exactly as written (keep or omit leading zeros as the child did)
If something is crossed out, transcribe only the final answer that is not crossed out.
If the box is empty, return an empty string.

confidence is your probability (0 to 1) that your transcription matches what the child wrote.
Lower it for ambiguous digits (1/7, 4/9, 5/S, 0/6), smudges, or writing that runs outside the box.
Use note to briefly explain any doubt; leave it empty otherwise."""

SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "text": {"type": "string"},
                       "confidence": {"type": "number"}, "note": {"type": "string"}},
        "required": ["id", "text", "confidence", "note"], "additionalProperties": False}}},
    "required": ["answers"], "additionalProperties": False,
}


def transcribe(items: list[dict]) -> dict[str, dict]:
    """items: [{id, png, hint}] -> {id: {text, confidence, note}}. One API call per scanned page."""
    if not items:
        return {}
    content = []
    for it in items:
        content.append({"type": "text", "text": f"Answer box id={it['id']} (expected: {it['hint']}):"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                    "data": base64.standard_b64encode(it["png"]).decode()}})
    content.append({"type": "text", "text": "Transcribe every answer box above."})

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=config.settings()["model"],
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        return {it["id"]: {"text": "", "confidence": 0.0, "note": "model declined to read this page"} for it in items}
    text = next(b.text for b in response.content if b.type == "text")
    got = {a["id"]: a for a in json.loads(text)["answers"]}
    return {it["id"]: got.get(it["id"], {"text": "", "confidence": 0.0, "note": "missing from model output"}) for it in items}
