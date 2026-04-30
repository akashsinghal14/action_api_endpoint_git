"""
Reference remedial guidance from fire_inspect_action_list_original.json.

Adds referenceRemediation to API payloads (does not replace actionItems from OpenAI/Claude).
Optional: one OpenAI call to polish inspectorGuidance, then optional local trim to cap (no second API).

Env: REFERENCE_GUIDANCE_TARGET_LENGTH_RATIO (default ~0.42), REFERENCE_GUIDANCE_HARD_MAX_CHAR_RATIO (default ~0.5 of source chars).
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
    "hinge": "Door leaf dropped / sagging on hinges",
    "closing": "Does the door close fully",
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


def _reference_guidance_length_ratio() -> float:
    """Ideal target vs source length for the model prompt. Clamped to 0.35–0.70."""
    try:
        r = float(os.getenv("REFERENCE_GUIDANCE_TARGET_LENGTH_RATIO", "0.42"))
    except ValueError:
        r = 0.42
    return max(0.35, min(0.70, r))


def _hard_max_output_chars(src_len: int, ratio: float) -> int:
    """
    Absolute ceiling on polished output length (fraction of source).
    Default keeps output at or below ~50% of source unless trimmed further.
    """
    try:
        cap = float(os.getenv("REFERENCE_GUIDANCE_HARD_MAX_CHAR_RATIO", "0.5"))
    except ValueError:
        cap = 0.5
    cap = max(ratio + 0.02, min(0.62, cap))
    return max(100, int(src_len * cap))


def _trim_guidance_to_limit(text: str, limit: int) -> Tuple[str, bool]:
    """Shorten text without a second API call; prefer sentence boundaries."""
    text = text.strip()
    if len(text) <= limit:
        return text, False
    truncated = text[:limit]
    for sep in (".\n\n", ".\n", ". ", "?", "!", "\n\n"):
        idx = truncated.rfind(sep)
        min_keep = max(50, int(limit * 0.35))
        if idx >= min_keep:
            out = text[: idx + len(sep)].strip()
            return out, True
    sp = truncated.rfind(" ")
    if sp >= max(40, int(limit * 0.3)):
        return truncated[:sp].rstrip(",;:").strip() + "…", True
    return truncated.rstrip().rstrip(",;:") + "…", True


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


def _polish_guidance_openai(section_title: str, source_text: str, api_key: str, model: str) -> Tuple[str, bool, bool]:
    """Return (text_to_use, was_polished, was_trimmed). On failure returns (source_text, False, False)."""
    if not source_text.strip():
        return source_text, False, False
    try:
        import openai

        ratio = _reference_guidance_length_ratio()
        src_stripped = source_text.strip()
        src_len = len(src_stripped)
        target_chars = max(90, int(src_len * ratio))
        hard_max = _hard_max_output_chars(src_len, ratio)

        client = openai.OpenAI(api_key=api_key)
        prompt = (
            f"SECTION TITLE:\n{section_title}\n\n"
            f"SOURCE TEXT (obligations and facts must survive in shortened form — keep all mm figures, BS/EN refs, "
            f"product names; do not invent; do not soften mandatory actions into vague advice):\n{src_stripped}\n\n"
            "WRITE FOR A UK FIRE DOOR INSPECTION REGISTER — ONE PASS:\n"
            f"- HARD LIMIT: the string inspectorGuidance MUST be at most {hard_max} characters (including spaces and "
            f"newlines). The source is {src_len} characters; aim ~{target_chars}.\n"
            "- Voice: direct imperatives (e.g. Rectify…, Replace…, Reinstate…, Confirm…). No filler, no preamble, "
            "no sign-off. No \"it is important\" / \"should consider\" unless the source uses a legal must.\n"
            "- Prefer 2–4 short sentences in one block, OR up to 5 lines each starting with \"- \" for distinct "
            "actions if that reads clearer. Every line must carry a requirement or fact.\n"
            "- If you must omit detail to meet the character limit, drop repetition only — never drop a number, "
            "standard name, or non-negotiable action from the source.\n\n"
            'Return JSON: {"inspectorGuidance": "<string>"}'
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You produce very short, authoritative UK fire-door remedial text in one reply. "
                        "Respect the user's hard character limit. Output valid JSON only with key inspectorGuidance."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.15,
            max_tokens=900,
        )
        raw = (response.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return source_text, False, False
        parsed = json.loads(m.group(0))
        polished = parsed.get("inspectorGuidance")
        if not polished or not isinstance(polished, str):
            return source_text, False, False
        polished = polished.strip()
        trimmed = False
        if len(polished) > hard_max:
            polished, trimmed = _trim_guidance_to_limit(polished, hard_max)
        return polished, True, trimmed
    except Exception as e:
        print(f"Reference guidance polish failed: {e}")
        return source_text, False, False


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
    trimmed_flag = False
    target_ratio = _reference_guidance_length_ratio()
    if _polish_enabled() and polish_key and source_text.strip():
        final_guidance, polished_flag, trimmed_flag = _polish_guidance_openai(
            section_title, source_text, polish_key, polish_model
        )

    reference: Dict[str, Any] = {
        "remediationKey": measurement_type,
        "sourceSectionTitle": section_title,
        "inspectorGuidanceSource": source_text,
        "inspectorGuidance": final_guidance,
        "inspectorGuidancePolished": polished_flag,
        "inspectorGuidancePolishModel": polish_model if polished_flag else None,
        "inspectorGuidanceTargetLengthRatio": round(target_ratio, 2),
    }
    if polished_flag:
        src_n = max(1, len(source_text.strip()))
        hard = _hard_max_output_chars(src_n, target_ratio)
        reference["inspectorGuidanceHardMaxCharRatio"] = round(hard / src_n, 3)
        reference["inspectorGuidanceActualLengthRatio"] = round(len(final_guidance.strip()) / src_n, 2)
        reference["inspectorGuidanceTrimmed"] = trimmed_flag

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
