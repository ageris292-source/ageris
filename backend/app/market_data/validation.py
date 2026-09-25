"""Deterministic validation of daily price bars (spec §7, §31).

Two levels:
  * row-level CRITICAL issues reject that bar (it is never stored)
  * series-level issues describe the dataset; any CRITICAL one makes the whole
    series unusable, which later gates treat as a hard block

The quality score is a documented formula, not an opinion:
    score = 1 - 5 * missing_session_ratio - 0.01 * warnings   (floored at 0)
    score = min(score, coverage of the requested window)
    score = 0 if any critical issue exists
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from app.core.config_file import MarketDataRules
from app.market_data.calendar import CalendarRangeError, IndiaCalendar
from app.market_data.types import Bar, CorporateActionIn

Severity = Literal["critical", "warning", "info"]


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    session: date | None
    detail: str


@dataclass
class ValidationReport:
    accepted: list[Bar]
    rejected: list[tuple[Bar, str]]
    issues: list[Issue] = field(default_factory=list)
    expected_sessions: int = 0
    # Share of the REQUESTED window's sessions that we actually have. Reported
    # separately from the quality score so a short but clean history (e.g. a
    # thin provider or a recent listing) is never mistaken for full coverage.
    coverage: float = 0.0
    missing_sessions: list[date] = field(default_factory=list)
    quality_score: float = 0.0
    usable: bool = False

    @property
    def critical(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> dict[str, object]:
        return {
            "usable": self.usable,
            "quality_score": round(self.quality_score, 4),
            "accepted": len(self.accepted),
            "rejected": len(self.rejected),
            "expected_sessions": self.expected_sessions,
            "missing_sessions": [d.isoformat() for d in self.missing_sessions[:50]],
            "missing_session_count": len(self.missing_sessions),
            "coverage": round(self.coverage, 4),
            "issues": [
                {
                    "code": i.code,
                    "severity": i.severity,
                    "session": i.session.isoformat() if i.session else None,
                    "detail": i.detail,
                }
                for i in self.issues[:200]
            ],
            "issue_count": len(self.issues),
        }


_EXCLUDABLE = {"non_calendar_session_excluded"}
HEAD_GAP_TOLERANCE_SESSIONS = 5  # holidays/weekends at the window edge are not a gap


def _row_problem(b: Bar) -> str | None:
    if min(b.open, b.high, b.low, b.close) <= 0:
        return "non_positive_price"
    if b.high < b.low:
        return "high_below_low"
    if not (b.low <= b.open <= b.high) or not (b.low <= b.close <= b.high):
        return "open_or_close_outside_range"
    if b.volume < 0:
        return "negative_volume"
    return None


def validate_bars(
    bars: list[Bar],
    calendar: IndiaCalendar,
    rules: MarketDataRules,
    *,
    now: datetime,
    window: tuple[date, date] | None = None,
    actions: list[CorporateActionIn] | None = None,
) -> ValidationReport:
    report = ValidationReport(accepted=[], rejected=[])
    issues = report.issues
    lag = timedelta(minutes=rules.eod_availability_lag_minutes)

    if not bars:
        issues.append(Issue("no_data", "critical", None, "no bars returned"))
        return report

    # Duplicates: identical duplicates are collapsed (info); conflicting ones are critical.
    by_session: dict[date, list[Bar]] = {}
    for b in bars:
        by_session.setdefault(b.session, []).append(b)

    candidates: list[Bar] = []
    for session, group in sorted(by_session.items()):
        if len({g.model_dump_json() for g in group}) > 1:
            for g in group:
                report.rejected.append((g, "conflicting_duplicate"))
            issues.append(
                Issue("conflicting_duplicate", "critical", session, f"{len(group)} differing bars")
            )
            continue
        if len(group) > 1:
            issues.append(Issue("duplicate_collapsed", "info", session, f"{len(group)} identical"))
        candidates.append(group[0])

    for b in candidates:
        problem = _row_problem(b)
        if problem is None:
            try:
                if not calendar.is_session(b.session):
                    problem = "non_calendar_session_excluded"
                elif calendar.session_close_utc(b.session) + lag > now:
                    problem = "session_not_complete"
            except CalendarRangeError:
                problem = "outside_calendar_range"
        if problem:
            report.rejected.append((b, problem))
            # A bar on a date the exchange calendar does not list as a regular
            # session (e.g. the one-hour Diwali "Muhurat" session) is excluded,
            # not trusted. Excluding it is the safe action, so it is a warning;
            # every other row problem means the feed itself is corrupt.
            severity: Severity = "warning" if problem in _EXCLUDABLE else "critical"
            issues.append(Issue(problem, severity, b.session, _fmt(b)))
        else:
            report.accepted.append(b)

    acc = report.accepted
    if not acc:
        issues.append(Issue("no_valid_bars", "critical", None, "every bar was rejected"))
        return report

    # Missing sessions against the exchange calendar.
    start, end = window or (acc[0].session, acc[-1].session)
    start, end = max(start, acc[0].session), min(end, acc[-1].session)
    try:
        expected = calendar.sessions(start, end)
    except CalendarRangeError as exc:
        issues.append(Issue("calendar_unavailable", "critical", None, str(exc)))
        expected = []
    have = {b.session for b in acc}
    if window is not None:
        w_start = max(window[0], calendar.first_session)
        w_end = min(window[1], calendar.last_session, acc[-1].session)
        try:
            requested = calendar.sessions(w_start, w_end)
        except CalendarRangeError:
            requested = []
        if requested:
            report.coverage = sum(1 for d in requested if d in have) / len(requested)
            head_gap = [d for d in requested if d < acc[0].session]
            if len(head_gap) > HEAD_GAP_TOLERANCE_SESSIONS:
                issues.append(
                    Issue(
                        "history_starts_late",
                        "warning",
                        acc[0].session,
                        f"requested from {window[0]}, first bar {acc[0].session} "
                        f"({len(head_gap)} sessions absent; listing date or provider gap)",
                    )
                )
    else:
        report.coverage = 1.0 if expected else 0.0
    report.expected_sessions = len(expected)
    report.missing_sessions = [d for d in expected if d not in have]
    missing_ratio = len(report.missing_sessions) / len(expected) if expected else 0.0
    for d in report.missing_sessions[:50]:
        issues.append(Issue("missing_session", "warning", d, "no bar for trading session"))
    if missing_ratio > rules.max_missing_session_ratio:
        issues.append(
            Issue(
                "excessive_missing_sessions",
                "critical",
                None,
                f"{missing_ratio:.2%} missing > {rules.max_missing_session_ratio:.2%} allowed",
            )
        )

    # Abnormal moves not explained by a corporate action.
    action_dates = {a.ex_date for a in actions or []}
    threshold = Decimal(str(rules.abnormal_move_threshold))
    for prev, cur in pairwise(acc):
        move = abs(cur.close / prev.close - 1)
        if move > threshold and cur.session not in action_dates:
            issues.append(
                Issue(
                    "abnormal_move_unexplained",
                    "warning",
                    cur.session,
                    f"close moved {move:.1%} vs previous session with no corporate action",
                )
            )

    # Zero-volume sessions and stale (frozen) prices.
    for b in acc:
        if b.volume == 0:
            issues.append(Issue("zero_volume", "warning", b.session, "no shares traded"))
    run = 1
    for prev, cur in pairwise(acc):
        same = (prev.open, prev.high, prev.low, prev.close) == (
            cur.open,
            cur.high,
            cur.low,
            cur.close,
        )
        run = run + 1 if same else 1
        if run == rules.stale_price_run_sessions:
            issues.append(
                Issue("stale_prices", "warning", cur.session, f"identical OHLC for {run} sessions")
            )

    critical = any(i.severity == "critical" for i in issues)
    warnings = sum(1 for i in issues if i.severity == "warning")
    score = 0.0 if critical else max(0.0, 1.0 - 5 * missing_ratio - 0.01 * warnings)
    score = min(score, report.coverage)  # a clean but short history is still low quality
    report.quality_score = score
    report.usable = not critical
    return report


def issue_counts(report: ValidationReport) -> dict[str, int]:
    return dict(Counter(i.code for i in report.issues))


def _fmt(b: Bar) -> str:
    return f"O={b.open} H={b.high} L={b.low} C={b.close} V={b.volume}"
