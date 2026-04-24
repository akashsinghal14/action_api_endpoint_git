"""
Reference remedial guidance from fire_inspect_action_list_original.json.

Adds referenceRemediation to API payloads (does not replace actionItems from OpenAI/Claude).
Optional: polish inspectorGuidance with OpenAI for professional UK English.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_ORIGINAL_DOC_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "fire_inspect_action_list_original.json"
)

# Internal measurement_type / gap_type -> exact section "title" in the original JSON
MEASUREMENT_TO_SECTION_TITLE: Dict[str, str] = {
    "head": "Perimeter gaps (head and jambs)",
    "hinge": "Perimeter gaps (head and jambs)",
    "closing": "Perimeter gaps (head and jambs)",
    "threshold": "Threshold gaps",
    "door_thickness": "Door construction / thickness",
    "frame_depth": "Does the door fit correctly in the frame",
    "door_size": "Does the door fit correctly in the frame",
    "intumescent_strips": "Intumescent strips",
    "self_closing_device": "Does the door close fully",
    "keep_shut_sign": "Fire door keep shut / keep locked signs",
    "hold_open_device": "Hold-open / free-swing / acoustic release device",
    "certification_visible": "Certification label / plug missing, painted over or unreadable",
    "glazing": "Glazing / vision panel fire resistance",
    "pyro_glazing": "Glazing / vision panel fire resistance",
    "door_close_fully": "Does the door close fully",
    "hinges_fire_rated": "Are all hinges fire rated",
    "cold_smoke_seals": "Smoke seals / cold smoke seals",
    "keep_locked_sign": "Fire door keep shut / keep locked signs",
}

_sections_by_title: Optional[Dict[str, str]] = None
_document_fingerprint: str = ""


def _templates_enabled() -> bool:
    return os.getenv("ENABLE_REMEDIATION_TEMPLATES", "true").lower() in ("1", "true", "yes")


def _polish_enabled() -> bool:
    return os.getenv("ENABLE_REFERENCE_GUIDANCE_POLISH", "true").lower() in ("1", "true", "yes")


def _load_sections() -> Dict[str, str]:
    global _sections_by_title, _document_fingerprint
    if _sections_by_title is not None:
        return _sections_by_title
    _sections_by_title = {}
    try:
        with open(_ORIGINAL_DOC_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        _document_fingerprint = "0"
        return _sections_by_title

    sections = data.get("sections") or []
    for block in sections:
        if not isinstance(block, dict):
            continue
        title = (block.get("title") or "").strip()
        text = block.get("text") or ""
        if not title:
            continue
        # Last wins if duplicate titles ever reappear
        _sections_by_title[title] = text if isinstance(text, str) else str(text)

    raw = json.dumps(sections, sort_keys=True).encode("utf-8")
    _document_fingerprint = hashlib.sha256(raw).hexdigest()[:16]
    return _sections_by_title


def get_reference_document_fingerprint() -> str:
    _load_sections()
    return _document_fingerprint


def get_section_for_measurement(measurement_type: str) -> Optional[Tuple[str, str]]:
    """Return (section_title, verbatim_source_text) or None."""
    title = MEASUREMENT_TO_SECTION_TITLE.get(measurement_type)
    if not title:
        return None
    sections = _load_sections()
    if title not in sections:
        return None
    text = sections[title]
    return title, text


def _polish_guidance_openai(section_title: str, source_text: str, api_key: str, model: str) -> Tuple[str, bool]:
    """Return (text_to_use, was_polished). On failure returns (source_text, False)."""
    if not source_text.strip():
        return source_text, False
    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        prompt = (
            f"SECTION TITLE:\n{section_title}\n\n"
            f"SOURCE TEXT (authoritative — preserve every technical requirement, BS/EN reference, "
            f"millimetre value, product name, and legal/compliance meaning; do not invent facts):\n{source_text}\n\n"
            "Rewrite this into clear, professional UK English suitable for a formal fire door inspection "
            "report aimed at UK building safety professionals. Use British spelling and terminology where "
            "appropriate. Do not add new requirements or change numbers. Preserve paragraph breaks using "
            "the characters \\n\\n between paragraphs inside the string.\n\n"
            'Return a JSON object with exactly one key: "inspectorGuidance" (string).'
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You refine UK fire-door remedial text for tone and clarity only. Output valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=2500,
        )
        raw = (response.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return source_text, False
        parsed = json.loads(m.group(0))
        polished = parsed.get("inspectorGuidance")
        if not polished or not isinstance(polished, str):
            return source_text, False
        return polished.strip(), True
    except Exception as e:
        print(f"Reference guidance polish failed: {e}")
        return source_text, False


def enrich_response_payload(
    payload: Dict[str, Any],
    measurement_type: str,
    polish_openai_key: Optional[str] = None,
    polish_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add referenceRemediation (verbatim source + polished inspectorGuidance when OpenAI available).

    If payload already contains referenceRemediation for the same remediationKey, returns payload
    unchanged (avoids double polish on cache hits).
    """
    if not _templates_enabled():
        return payload
    items = payload.get("actionItems")
    if not items:
        return payload

    section = get_section_for_measurement(measurement_type)
    if not section:
        return payload

    section_title, source_text = section

    existing = payload.get("referenceRemediation")
    if isinstance(existing, dict) and existing.get("remediationKey") == measurement_type:
        return payload

    polish_key = polish_openai_key or os.getenv("OPENAI_API_KEY")
    polish_model = polish_model or os.getenv("OPENAI_REFERENCE_POLISH_MODEL", "gpt-4o-mini")

    final_guidance = source_text
    polished_flag = False
    if _polish_enabled() and polish_key and source_text.strip():
        final_guidance, polished_flag = _polish_guidance_openai(
            section_title, source_text, polish_key, polish_model
        )

    reference: Dict[str, Any] = {
        "remediationKey": measurement_type,
        "sourceSectionTitle": section_title,
        "inspectorGuidanceSource": source_text,
        "inspectorGuidance": final_guidance,
        "inspectorGuidancePolished": polished_flag,
        "inspectorGuidancePolishModel": polish_model if polished_flag else None,
    }

    new_items: List[Dict[str, Any]] = []
    for item in items:
        merged = dict(item)
        merged["remediationKey"] = measurement_type
        new_items.append(merged)

    out = dict(payload)
    out["actionItems"] = new_items
    out["referenceRemediation"] = reference
    fp = get_reference_document_fingerprint()
    if fp and fp != "0":
        out["referenceDocumentFingerprint"] = fp
    return out
