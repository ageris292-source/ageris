"""Report narrative (spec §15): deterministic by default, optional LLM prose.

The LLM is a narrator, never an authority. It receives only the finished
deterministic report and is asked to summarise it. Its output is rejected
(and the deterministic narrative used instead) if it contains any number that
does not appear in the facts, if it is empty, or if it mentions buying or
selling as advice. The trade decision is never taken from the narrative.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

import httpx

from app.core.settings import get_settings

_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_ADVICE = re.compile(r"\b(buy|sell|accumulate|strong buy|target price|price target)\b", re.I)
SYSTEM_PROMPT = (
    "You summarise a stock research report for an investor in plain English, in at most "
    "180 words. Use ONLY facts in the report. Do not add any number that is not in the "
    "report. Do not give buy, sell or hold advice and do not state price targets. State "
    "that the decision is NO TRADE unless the report says otherwise. Mention the main "
    "points for and against and the biggest risk."
)


def _norm(tok: str) -> str:
    t = tok.replace(",", "").lstrip("+")
    try:
        f = float(t)
    except ValueError:
        return t
    return f"{f:.6g}"


def numbers_in(text: str) -> set[str]:
    return {_norm(m.group()) for m in _NUM.finditer(text)}


def validate_narrative(text: str, facts: str) -> list[str]:
    """Problems with an LLM narrative; empty list = acceptable."""
    problems: list[str] = []
    if not text.strip():
        return ["empty narrative"]
    allowed = numbers_in(facts) | {str(i) for i in range(10)}
    extra = sorted(numbers_in(text) - allowed)
    if extra:
        problems.append("numbers not present in the facts: " + ", ".join(extra[:10]))
    if _ADVICE.search(text):
        problems.append("contains buy/sell/target language")
    return problems


class Narrator(Protocol):
    name: str

    def narrate(self, facts: str) -> str: ...


class AnthropicNarrator:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, transport: httpx.BaseTransport | None = None):
        self._key, self.model = api_key, model
        self._client = httpx.Client(timeout=30, transport=transport)

    def narrate(self, facts: str) -> str:
        r = self._client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 600,
                "temperature": 0,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": facts}],
            },
        )
        r.raise_for_status()
        body = r.json()
        return "".join(
            b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
        )


def configured_narrator() -> Narrator | None:
    s = get_settings()
    if s.llm_api_key is None or not s.llm_api_key.get_secret_value():
        return None
    return AnthropicNarrator(s.llm_api_key.get_secret_value(), s.llm_model)


def narrator_status() -> dict[str, Any]:
    n = configured_narrator()
    if n is None:
        return {"available": False, "reason": "No LLM API key configured (AEGIS_LLM_API_KEY)"}
    return {"available": True, "provider": n.name, "model": getattr(n, "model", None)}


def deterministic(report: dict[str, Any]) -> str:
    s = report["synthesis"]
    parts = [
        f"{report['ticker']}: {s['stance_text'].lower()}"
        + (
            f" (composite {s['composite_score']:.1f}/100, confidence {s['confidence']:.2f})."
            if s["composite_score"] is not None
            else "."
        )
    ]
    if s["insufficient_reasons"]:
        parts.append(" ".join(s["insufficient_reasons"]) + ".")
    if s["bull_case"]:
        parts.append("For: " + "; ".join(p["detail"] for p in s["bull_case"][:3]) + ".")
    if s["bear_case"]:
        parts.append("Against: " + "; ".join(p["detail"] for p in s["bear_case"][:3]) + ".")
    if s["conflicts"]:
        parts.append("Conflicts: " + "; ".join(c["detail"] for c in s["conflicts"]) + ".")
    if s["key_risks"]:
        parts.append(f"Main risk: {s['key_risks'][0]['risk']}.")
    parts.append("Decision: NO TRADE (research only).")
    return " ".join(parts)


def narrate(
    report: dict[str, Any], facts_markdown: str, narrator: Narrator | None
) -> dict[str, Any]:
    base = deterministic(report)
    if narrator is None:
        return {"text": base, "source": "deterministic", "warnings": []}
    try:
        text = narrator.narrate(facts_markdown)
    except Exception as exc:  # network / API errors never break a report
        return {
            "text": base,
            "source": "deterministic",
            "warnings": [
                f"LLM narrator failed ({exc.__class__.__name__}); deterministic text used"
            ],
        }
    problems = validate_narrative(text, facts_markdown)
    if problems:
        return {
            "text": base,
            "source": "deterministic",
            "warnings": ["LLM narrative rejected: " + "; ".join(problems)],
        }
    return {"text": text.strip(), "source": f"llm:{narrator.name}", "warnings": []}
