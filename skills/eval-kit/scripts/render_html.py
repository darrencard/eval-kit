#!/usr/bin/env python3
"""The eval report as one self-contained HTML page, in the Leader Report's style guide.

Fonts and colour tokens are read from the vendored template.html at render time, so this page and the Leader
Report look like one product. The rules from the guide's references/design.md that apply here: numbers get a
picture that adds no number of its own; labels in mono capitals, content in sans; hairlines, not boxes; green,
grey-white and red mean a bet's landed, watch and stalled only, which did-it-land sets, so this page uses none of
them: meets target and below target print as plain words; one line per figure as `prior -> actual . TARGET x`.

Every piece of text from the traces is escaped. Nothing is fetched: the page works offline and from a file.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

VENDOR = Path(__file__).resolve().parent / "vendor"


def _style_guide() -> tuple[str, str]:
    """(@font-face blocks, :root token block) from the vendored template."""
    text = (VENDOR / "template.html").read_text(encoding="utf-8")
    faces = "".join(re.findall(r"@font-face\{.*?\}", text, re.S))
    root = re.search(r":root\{.*?\}", text, re.S)
    return faces, root.group(0) if root else ""


class Table:
    """A table whose cells carry their column name, so a phone shows each row as labelled lines."""

    def __init__(self, heads: tuple[str, ...]) -> None:
        self.heads = heads
        self.rows: list[str] = []

    def row(self, *cells: tuple[str, str]) -> None:
        tds = []
        for head, (cls, body) in zip(self.heads, cells, strict=True):
            attr = f' class="{cls}"' if cls else ""
            tds.append(f'<td{attr} data-l="{esc(head)}"><span>{body}</span></td>')
        self.rows.append("<tr>" + "".join(tds) + "</tr>")

    def html(self) -> str:
        return "<table><tr>" + "".join(f"<th>{esc(h)}</th>" for h in self.heads) + "</tr>" + "".join(self.rows) + "</table>"


CSS = """
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--t1);font-family:var(--sans);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
main{max-width:1080px;margin:0 auto;padding:40px 24px 64px}
.label{font:400 11px/16px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--t3)}
h1{font:600 30px/1.15 var(--display);letter-spacing:-.02em;margin:6px 0 10px}
h2{font:400 11px/16px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--t3);margin:40px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
p{margin:0 0 10px;color:var(--t2);max-width:72ch}
.status{display:inline-flex;align-items:center;gap:8px;font:500 12px/1 var(--mono);text-transform:uppercase;letter-spacing:.08em}
.lede{font-size:16px;color:var(--t1);max-width:72ch}
.tag{display:inline-block;font:400 10px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--brass);border:1px dashed var(--brass);border-radius:3px;padding:4px 6px;margin-left:10px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));border:1px solid var(--line);border-radius:6px}
.card{padding:22px 24px;border-left:1px solid var(--line)}
.card:first-child{border-left:0}
.fig{font:600 34px/1.1 var(--display);letter-spacing:-.02em;margin:8px 0 6px;color:var(--t1)}
.line{font:400 12px/18px var(--mono);color:var(--t3)}
.line b{color:var(--t1);font-weight:500}
svg.range{display:block;margin-top:12px}
table{width:100%;border-collapse:collapse}
th{font:400 10.5px/16px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--t3);text-align:left;padding:10px 12px 10px 0;border-bottom:1px solid var(--line2)}
td{padding:12px 12px 12px 0;border-bottom:1px solid var(--line);vertical-align:top;color:var(--t2)}
td.n{font-family:var(--mono);color:var(--t1);white-space:nowrap}
.bar{display:inline-block;height:6px;background:var(--agent);border-radius:1px;margin-right:8px;vertical-align:middle}
.ex{font-size:12.5px;color:var(--t3)}
.call{color:var(--brass)}
ul{margin:0;padding-left:18px;color:var(--t2)}
li{margin:4px 0}
.mono{font-family:var(--mono);color:var(--t2)}
.ex,td{overflow-wrap:anywhere}
@media (max-width:640px){.card{border-left:0;border-top:1px solid var(--line)}.card:first-child{border-top:0}main{padding:28px 16px}
table,tbody,tr,td{display:block}tr:first-child{display:none}tr{padding:12px 0;border-bottom:1px solid var(--line)}
td{border:0;padding:3px 0;display:grid;grid-template-columns:118px 1fr;gap:12px}td.n{white-space:normal}
td::before{content:attr(data-l);font:400 10.5px/20px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--t3)}}
@media print{:root{color-scheme:light;--bg:#fff;--t1:#0A0A0A;--t2:#3C3C3A;--t3:#585855;--line:#ddd;--line2:#bbb;--brass:#9A6B12}}
"""


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def status_chip(status: str | None) -> str:
    """The build check's word as plain text, with no status colour: the colours belong to did-it-land."""
    return f'<span class="status">{esc(status or "not confirmed")}</span>'


def range_line(actual: float, prior: float | None = None, target: float | None = None, ci: tuple | None = None) -> str:
    """Range line on 0 to 100: interval as a faint band, grey dot for prior, ink dot for actual, tick for target."""
    w, h, pad = 220, 22, 6

    def x(v: float) -> float:
        return pad + (w - 2 * pad) * max(0.0, min(100.0, v)) / 100

    parts = [f'<line x1="{pad}" y1="11" x2="{w - pad}" y2="11" stroke="var(--line2)" stroke-width="1"/>']
    if ci:
        parts.append(f'<rect x="{x(ci[0]):.1f}" y="8" width="{max(1.0, x(ci[1]) - x(ci[0])):.1f}" height="6" fill="var(--line2)" rx="1"/>')
    if target is not None:
        parts.append(f'<line x1="{x(target):.1f}" y1="3" x2="{x(target):.1f}" y2="19" stroke="var(--t2)" stroke-width="1.5"/>')
    if prior is not None:
        parts.append(f'<circle cx="{x(prior):.1f}" cy="11" r="4" fill="var(--agent)"/>')
    parts.append(f'<circle cx="{x(actual):.1f}" cy="11" r="5" fill="var(--t1)"/>')
    return f'<svg class="range" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">{"".join(parts)}</svg>'


def money(x: float) -> str:
    return f"${x:,.4f}".rstrip("0").rstrip(".") if x < 1 else f"${x:,.2f}"


def card(label: str, value: str, line: str, picture: str = "") -> str:
    return f'<div class="card"><div class="label">{esc(label)}</div><div class="fig">{value}</div><div class="line">{line}</div>{picture}</div>'


def render(report: dict, evals: dict | None = None) -> str:
    faces, root = _style_guide()
    rows = report["versions"]
    latest, before = rows[-1], (rows[-2] if len(rows) > 1 else None)
    status = evals["status"] if evals else report["status"]
    reasons = evals["reasons"] if evals else report["reasons"]
    target = report["target"]
    led = latest["ledger"]
    out: list[str] = []
    tag = '<span class="tag">Illustrative</span>' if report["illustrative"] else ""
    out.append(f'<div class="label">Evals · {esc(latest["version"])} · as of {esc(evals["as_of"] if evals else latest["run_at"])}{tag}</div>')
    out.append(f"<h1>{esc(report['feature'])}</h1>")
    out.append(f"<p>{status_chip(status)}</p>")
    out.append(f'<p class="lede">{esc("; ".join(reasons)[:1].upper() + "; ".join(reasons)[1:])}.</p>')

    prior_pass = before["pass_rate"] if before else None
    tgt = f" · TARGET {target:g}%" if target is not None else ""
    cards = [
        card(
            "Held-out pass rate",
            f"{latest['pass_rate']:g}%",
            (f"{prior_pass:g}% → " if prior_pass is not None else "") + f"<b>{latest['pass_rate']:g}%</b>{tgt}<br>"
            f"{latest['passed']} of {latest['cases']} · 95% {latest['pass_ci'][0]:g} to {latest['pass_ci'][1]:g} · {esc(led['pass_rate'])}",
            range_line(latest["pass_rate"], prior_pass, target, latest["pass_ci"]),
        )
    ]
    if latest["autonomy_rate"] is not None:
        prior_auto = before["autonomy_rate"] if before else None
        cards.append(
            card(
                "Without a person",
                f"{latest['autonomy_rate']:g}%",
                (f"{prior_auto:g}% → " if prior_auto is not None else "") + f"<b>{latest['autonomy_rate']:g}%</b><br>"
                f"{latest['tasks_unassisted']} of {latest['tasks']} tasks · {esc(led['autonomy_rate'])}",
                range_line(latest["autonomy_rate"], prior_auto, None, latest["autonomy_ci"]),
            )
        )
    if latest["cost_per_task"] is not None:
        cards.append(card("Cost per successful task", money(latest["cost_per_task"]), f"cited from cost-budget-check · {esc(led['cost_per_task'])}"))
    else:
        cards.append(card("Cost per successful task", "not checked", "cost not checked: run cost-budget-check"))
    out.append(f'<div class="cards">{"".join(cards)}</div>')

    if evals:
        a = evals["against_brief"]
        out.append("<h2>Against the landing brief</h2>")
        if a["judged"]:
            v = "not computed" if a.get("value") is None else f"{a['value']:g}%"
            out.append(
                f"<p>{status_chip(a['status'])} &nbsp; {esc(a['metric'])} is <b>{esc(v)}</b> against a bar of {esc(a['bar'])} ({esc(a['better'])} is better) by {esc(a['by'])}.</p>"
            )
            if a.get("note"):
                out.append(f"<p>{esc(a['note'][:1].upper() + a['note'][1:])}.</p>")
        else:
            out.append(f"<p>{esc(a['note'])}</p>")

    p = report["promotion"]
    if p:
        out.append("<h2>Promotion</h2>")
        verb = "may replace" if p["promote"] else "may not replace"
        out.append(f"<p>{esc(p['challenger'])} {verb} {esc(p['champion'])}: {esc(p['reason'])}.</p>")
        if p["new_failures"]:
            out.append(f"<p>New held-out failures: {esc(', '.join(p['new_failures']))}.</p>")
        if p["within_noise"]:
            out.append("<p>Each rate sits inside the other's 95% interval, so read the gain as direction, not size.</p>")

    out.append("<h2>By version</h2>")
    tab = Table(("Version", "Run", "Held-out pass", "Development pass", "Without a person", "Cost per successful task"))
    for r in rows:
        dev = f"{r['dev_passed']}/{r['dev_cases']} ({r['dev_pass_rate']:g}%)" if r["dev_pass_rate"] is not None else "not run"
        auto = f"{r['tasks_unassisted']}/{r['tasks']} ({r['autonomy_rate']:g}%)" if r["autonomy_rate"] is not None else "not run"
        cost = money(r["cost_per_task"]) + " (cited)" if r["cost_per_task"] is not None else "not checked"
        held = f"{r['passed']}/{r['cases']} ({r['pass_rate']:g}%)"
        tab.row(*(("n", esc(v)) for v in (r["version"], r["run_at"], held, dev, auto, cost)))
    out.append(tab.html())

    out.append("<h2>Failure modes</h2>")
    if report["clusters"]:
        out.append("<p>Found with no categories set in advance, from development failures and production tasks that failed or needed a person.</p>")
        tab = Table(("Cluster", "Shared terms", "Share", "Read first"))
        for c in report["clusters"]:
            ex = "<br>".join(f"<span class='mono'>{esc(e['trace'])}</span> {esc(e['text'])}" for e in c["examples"])
            share = f'<span class="bar" style="width:{max(2, c["share"])}px"></span>{c["size"]} · {c["share"]}%'
            tab.row(("n", esc(c["id"])), ("", esc(c["label"])), ("n", share), ("ex", ex))
        out.append(tab.html())
    else:
        out.append("<p>No failures to read.</p>")
    out.append(f"<p>{report['held_out_failures_unread']} held-out failure(s) are counted and not read, so the holdout stays sealed.</p>")

    c = report["calibration"]
    out.append("<h2>Judge calibration</h2>")
    if c is None:
        out.append("<p>Not run. A judge-scored pass rate cannot meet the target until the judge clears the calibration cases.</p>")
    else:
        fa = ", ".join(c["false_accepts"]) or "none"
        out.append(f"<p>The judge agreed with the human verdict on {c['agreement']:g}% of {c['judged']} cases. False accepts: {esc(fa)}.</p>")

    warnings = evals["warnings"] if evals else report["warnings"]
    if warnings:
        out.append("<h2>Warnings</h2><ul>" + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>")

    out.append("<h2>Ledger</h2>")
    tab = Table(("Row", "Figure", "Value", "Basis", "Source", "Provenance"))
    for r in report["ledger"]:
        val = money(r["value"]) if r["unit"] == "$" else f"{r['value']:g}{r['unit']}"
        tab.row(("n", esc(r["id"])), ("", esc(r["label"])), ("n", esc(val)), ("", esc(r["basis"])), ("ex", esc(r["source"])), ("n", esc(r["provenance"])))
    out.append(tab.html())
    body = "\n".join(out)
    title = esc(f"Evals: {report['feature']}")
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{faces}{root}{CSS}</style></head><body><main>{body}</main></body></html>\n"
    )
