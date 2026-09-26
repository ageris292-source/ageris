"""Render a stored analysis report as the §81 markdown document."""

from __future__ import annotations

from typing import Any


def _pct(v: Any, d: int = 1) -> str:
    return "—" if v is None else f"{v * 100:.{d}f}%"


def _num(v: Any, d: int = 1) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def render(report: dict[str, Any], *, include_narrative: bool = True) -> str:
    s = report["synthesis"]
    lines: list[str] = []
    add = lines.append
    add(f"# AEGIS Research Report — {report.get('name') or report['ticker']} ({report['ticker']})")
    add("")
    add(f"- As of (market cut-off): {report['as_of']}")
    add(f"- Knowledge at (data vintage): {report['knowledge_at']}")
    add(
        f"- System mode: {report['system_mode']} · config {report['config_version']} "
        f"({report['config_fingerprint'][:12]})"
    )
    if report.get("report_id") is not None:
        add(f"- Report #{report['report_id']} · hash {report.get('report_hash', '')[:16]}")
    add("")
    add(
        "> Research only. Not investment advice. Scores are descriptive heuristics, not "
        "probabilities or expected returns."
    )
    add("")
    add("## 1. Decision")
    add("")
    add(f"**{s['decision']['trade']}** — {s['decision']['reason']}")
    add("")
    add("## 2. Research stance")
    add("")
    add(
        f"**{s['stance_text']}** · composite {_num(s['composite_score'])}/100 · confidence "
        f"{_num(s['confidence'], 2)} ({s['confidence_basis']}) · coverage {_pct(s['coverage'], 0)}"
    )
    for r in s["insufficient_reasons"]:
        add(f"- {r}")
    add("")
    add("## 3. Agents")
    add("")
    add("| Agent | Status | Score | Confidence | Data quality | Weight |")
    add("|---|---|---|---|---|---|")
    for a in s["agents"]:
        add(
            f"| {a['agent']} | {a['status']} | {_num(a['score'])} | {_num(a['confidence'], 2)} | "
            f"{_num(a['data_quality'], 2)} | {a['weight']:.2f} |"
        )
    for title, key in (("## 4. Bull case", "bull_case"), ("## 5. Bear case", "bear_case")):
        add("")
        add(title)
        add("")
        if not s[key]:
            add("- None identified by the agents.")
        for p in s[key]:
            add(f"- **{p['agent']}** · {p['detail']}")
    add("")
    add("## 6. Conflicts between agents")
    add("")
    add(
        "\n".join(f"- {c['detail']}" for c in s["conflicts"])
        or "- None above the conflict threshold."
    )
    val = report.get("valuation") or {}
    add("")
    add("## 7. Valuation")
    add("")
    sc = val.get("scenarios")
    if sc:
        add(
            f"Price ₹{_num(val.get('price'), 2)} on {val.get('price_date')}. "
            + (
                ""
                if val.get("dcf_reliable", True)
                else "DCF failed the reliability guard (not scored). "
            )
        )
        add("")
        add("| Scenario | Value/share | vs price | Growth | FCF margin | WACC | Terminal g |")
        add("|---|---|---|---|---|---|---|")
        for k in ("bear", "base", "bull"):
            if k in sc:
                x = sc[k]
                a = x["assumptions"]
                add(
                    f"| {k} | ₹{_num(x['per_share'], 0)} | {_pct(x['margin_of_safety'], 0)} | "
                    f"{_pct(a['growth'])} | {_pct(a['fcf_margin'])} | {_pct(a['wacc'])} | "
                    f"{_pct(a['terminal_growth'])} |"
                )
    else:
        add("- No DCF scenarios (see agent warnings).")
    rm = report.get("risk_metrics") or {}
    add("")
    add("## 8. Risk profile (trailing year)")
    add("")
    add(
        f"- Volatility {_pct(rm.get('volatility_annual'))}, beta {_num(rm.get('beta'), 2)}, "
        f"max drawdown {_pct(rm.get('max_drawdown'))}, 1-day VaR95 {_pct(rm.get('var_95_1d'))}, "
        f"CVaR99 {_pct(rm.get('cvar_99_1d'))}, Sharpe {_num(rm.get('sharpe'), 2)}"
    )
    adtv = rm.get("adtv")
    add(f"- Avg daily traded value: {'—' if adtv is None else f'₹{adtv / 1e7:,.1f} cr'}")
    rg = report.get("regime") or {}
    add("")
    add("## 9. Market regime")
    add("")
    add(
        f"- {rg.get('label', 'UNKNOWN')} (trend {rg.get('trend')}, "
        f"volatility {rg.get('volatility')}, {rg.get('risk')})"
    )
    add("")
    add("## 10. Key risks")
    add("")
    add("\n".join(f"- ({r['agent']}) {r['risk']}" for r in s["key_risks"]) or "- None flagged.")
    add("")
    add("## 11. What would change the view")
    add("")
    add("\n".join(f"- ({i['agent']}) {i['condition']}" for i in s["invalidation"]) or "- —")
    add("")
    add("## 12. Data quality and provenance")
    add("")
    add(
        "\n".join(f"- ({w['agent']}) {w['warning']}" for w in s["data_warnings"])
        or "- No data warnings."
    )
    for a in s["agents"]:
        if a["snapshot"]:
            add(f"- {a['agent']} {a['version']} · snapshot {a['snapshot'][:16]}")
    if include_narrative and report.get("narrative"):
        n = report["narrative"]
        add("")
        add("## 13. Summary")
        add("")
        add(n["text"])
        add("")
        add(f"_Narrative source: {n['source']}_")
        for w in n.get("warnings", []):
            add(f"- {w}")
    add("")
    return "\n".join(lines)
