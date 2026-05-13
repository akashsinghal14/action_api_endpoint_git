"""
Static helpers when the gap-analysis LLM is not used (no prompt → no model severity).

When OpenAI/Claude runs, severity comes from the prompt + model output only.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Internal measurement_type → severity for static / cache-warm paths only
_MEASUREMENT_SEVERITY: Dict[str, str] = {
    "head": "medium",
    "hinge": "medium",
    "closing": "medium",
    "threshold": "medium",
    "door_thickness": "medium",
    "frame_depth": "medium",
    "door_size": "medium",
    "self_closing_device": "high",
    "door_close_fully": "high",
    "hinges_fire_rated": "high",
    "hold_open_device": "high",
    "intumescent_strips": "medium",
    "cold_smoke_seals": "medium",
    "glazing": "medium",
    "pyro_glazing": "medium",
    "keep_shut_sign": "low",
    "keep_locked_sign": "low",
    "certification_visible": "low",
}


def severity_for_noncompliant_measurement(measurement_type: str) -> str:
    """Severity when not calling the LLM (static payloads)."""
    return _MEASUREMENT_SEVERITY.get(measurement_type, "medium")


def confidence_score_for_severity(severity: str) -> int:
    """Static fallback confidence when not using AI-generated action items."""
    if severity == "high":
        return 95
    if severity == "medium":
        return 88
    if severity == "low":
        return 84
    if severity == "critical":
        return 98
    return 88


def normalize_llm_severities(action_items: List[Dict[str, Any]]) -> None:
    """Ensure each item has a valid API severity string (in-place)."""
    allowed = frozenset({"critical", "high", "medium", "low"})
    for item in action_items:
        s = str(item.get("severity", "medium")).lower().strip()
        item["severity"] = s if s in allowed else "medium"
