"""Deterministic event classification and entity linking for headlines.

Rules are transparent keyword patterns (first match wins, most specific
first). They are deliberately conservative: anything unmatched is `other`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "earnings_beat",
        re.compile(
            r"\b(beats?|tops?|surpass\w*|exceeds?|above) (street |analyst |market )?"
            r"(estimates?|expectations?|forecasts?)\b|\brecord (quarterly )?(profit|revenue)\b",
            re.I,
        ),
    ),
    (
        "earnings_miss",
        re.compile(
            r"\b(miss(es|ed)?|below|falls? short of|lags?) (street |analyst |market )?"
            r"(estimates?|expectations?|forecasts?)\b|\bprofit (falls?|drops?|declines?|slumps?)\b",
            re.I,
        ),
    ),
    (
        "results",
        re.compile(
            r"\b(q[1-4]|quarterly|annual|fy\d{2}) (results?|earnings|numbers)\b"
            r"|\bresults? (date|preview|today)\b|\bnet profit\b",
            re.I,
        ),
    ),
    (
        "regulatory",
        re.compile(
            r"\b(sebi|rbi|cci|penalty|fine[ds]?|show[- ]cause|probe|"
            r"regulator\w*|ban(ned)?|tax demand|gst notice)\b",
            re.I,
        ),
    ),
    (
        "lawsuit",
        re.compile(
            r"\b(lawsuit|sued|sues|litigation|court|tribunal|nclt|arbitration|"
            r"legal battle|boardroom battle)\b",
            re.I,
        ),
    ),
    (
        "acquisition",
        re.compile(
            r"\b(acquires?|acquisition|acquired|merger|merges?|takeover|"
            r"stake (buy|sale)|buyout|divest\w*)\b",
            re.I,
        ),
    ),
    (
        "management_change",
        re.compile(
            r"\b(ceo|cfo|md|chairman|chairperson|managing director)\b.*"
            r"\b(resign\w*|appoint\w*|steps? down|quits?|exit\w*|named)\b"
            r"|\b(resign\w*|appoint\w*) .*\b(ceo|cfo|chairman)\b",
            re.I,
        ),
    ),
    (
        "dividend_buyback",
        re.compile(
            r"\b(dividend|buyback|buy-back|record date|bonus issue|"
            r"stock split)\b",
            re.I,
        ),
    ),
    (
        "rating_change",
        re.compile(
            r"\b(upgrades?|downgrades?|target price|price target|"
            r"(buy|sell|hold|overweight|underweight) (rating|call)|brokerages?)\b",
            re.I,
        ),
    ),
    (
        "product_launch",
        re.compile(
            r"\b(launch(es|ed)?|unveil\w*|introduc\w*|rolls? out|"
            r"new (product|platform|service))\b",
            re.I,
        ),
    ),
    (
        "sector",
        re.compile(
            r"\b(it stocks|sector|nifty (it|bank|auto|pharma)|industry|"
            r"peers?|sensex|nifty)\b",
            re.I,
        ),
    ),
]


def classify(title: str) -> str:
    for event, pattern in _RULES:
        if pattern.search(title):
            return event
    return "other"


@dataclass(frozen=True)
class Alias:
    ticker: str
    patterns: tuple[re.Pattern[str], ...]


def build_aliases(stocks: list[tuple[str, str, str | None]]) -> list[Alias]:
    """(ticker, symbol, name) -> matchers on the symbol and the distinctive
    part of the company name (without 'Limited', 'Ltd', 'Industries')."""
    out: list[Alias] = []
    stop = {"limited", "ltd", "ltd.", "industries", "company", "corporation", "corp", "the"}
    for ticker, symbol, name in stocks:
        pats = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", re.I)]
        if name:
            words = [w for w in re.split(r"\s+", name) if w.lower() not in stop]
            if words:
                pats.append(re.compile(r"\b" + r"\s+".join(map(re.escape, words)) + r"\b", re.I))
        out.append(Alias(ticker, tuple(pats)))
    return out


def mentioned(title: str, aliases: list[Alias]) -> list[str]:
    return [a.ticker for a in aliases if any(p.search(title) for p in a.patterns)]
