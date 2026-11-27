#!/usr/bin/env python3
"""The eval report as one self-contained HTML page, on the Leader Report's own template.

The page uses the report's whole stylesheet, taken from its template (vendor/template.html, vendored byte-identical
at the commit in vendor/VENDORED.json), so it is the same brand family as the deck and did-it-land's page: the
DACARD wordmark, the same fonts, tokens, scorecard rows and range line. Only a few rules for this page's layout are
added. It follows the report's references/design.md: mono capitals for labels, sans for sentences; hairlines, not
boxes; grey for the prior version, ink for the actual. Green, grey-white and red mean a bet's landed, watch and
stalled only, which did-it-land sets, so this page uses none of them: the build check prints as plain words in ink,
and so do the Illustrative tag and every chip. Brass is a person's call; this page names none, so it carries none
outside the wordmark. The template paints selection and focus green; this page's own rules set both to ink.

A leader gets the point in 30 seconds: a one-line answer at the top, a five-line summary, the scorecard, then the
detail folded under <details>. Every piece of text from the traces is escaped. Nothing is fetched: the page works
offline and from a file.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from evalcore import MEETS, NOISE

TEMPLATE = Path(__file__).resolve().parent / "vendor" / "template.html"
STYLE = re.compile(r"<style>(.*?)</style>", re.S)

# Layout for this page only. Everything else comes from the template's stylesheet.
PAGE_CSS = """
main.solo{margin-left:0}
.solo .slide{min-height:0}
.solo .slide.cover{padding-top:72px;padding-bottom:40px}
.solo .lede{margin-bottom:8px}
.solo h2{margin-bottom:16px}
.status{font:400 10px/16px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--t1);border:1px solid var(--line3);border-radius:3px;padding:1px 6px;white-space:nowrap}
.ill{color:var(--t1)}
.summary{margin:0 0 8px;padding:0;list-style:none;max-width:80ch}
.summary li{display:grid;grid-template-columns:150px minmax(0,1fr);gap:4px 16px;align-items:baseline;font-size:14px;line-height:1.6;color:var(--t2);border-top:1px solid var(--line);padding:6px 0}
.summary li b{font:400 10px/22px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--t3);font-weight:400}
.summary .status{justify-self:start}
.solo .sc-h,.solo .sc-r{grid-template-columns:minmax(0,1.2fr) minmax(0,1fr) 210px}
.sc-s .status{white-space:normal}
.sc-n .sc-d{max-width:46ch}
.bl .ci{top:4px;height:6px;border-radius:2px;background:var(--line3)}
.solo details{margin-top:4px}
.solo details>*:not(summary){margin-top:12px}
.solo details p,.solo details li{margin:0 0 10px;font-size:13px;color:var(--t2);max-width:80ch}
.solo details ul{padding-left:18px}
.tablewrap td,.tablewrap th{overflow-wrap:anywhere}
.tablewrap .ex{font-size:12px;color:var(--t3)}
.tablewrap .sh i{background:var(--agent)}
::selection{background:var(--t1);color:var(--bg)}
:focus-visible{outline-color:var(--t1)}
.foot{max-width:1120px;margin:0 auto;padding:28px 40px 64px;color:var(--t3);font-size:12px}
@media (max-width:980px){.foot{padding:24px 16px 48px}.solo .slide.cover{padding-top:48px}.summary li{grid-template-columns:1fr;gap:0}.solo .sc-r{grid-template-columns:1fr}
.stack table,.stack tbody,.stack tr,.stack td{display:block}.stack tr:first-child{display:none}.stack tr{padding:10px 16px;border-bottom:1px solid var(--line)}
.stack td{border:0;padding:3px 0;display:grid;grid-template-columns:118px 1fr;gap:12px}.stack td.num{text-align:left;white-space:normal}
.stack td::before{content:attr(data-l);font:400 10px/20px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--t3)}}
"""

MARK = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">'
    '<rect x="2" y="13" width="3" height="7" fill="var(--agent)"/><rect x="7" y="10" width="3" height="10" fill="var(--agent)"/>'
    '<rect x="12" y="2" width="1.5" height="20" fill="var(--brass)"/><rect x="16" y="4" width="4" height="16" fill="var(--t1)"/></svg>'
)


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def stylesheet() -> str:
    """The report template's whole stylesheet, fonts included."""
    found = STYLE.search(TEMPLATE.read_text(encoding="utf-8"))
    return found.group(1) if found else ""


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


class Table:
    """A table whose cells carry their column name, so a phone shows each row as labelled lines."""

    def __init__(self, heads: tuple[str, ...]) -> None:
        self.heads = heads
        self.rows: list[str] = []

    def row(self, *cells: tuple[str, str]) -> None:
        tds = []
        for head, (cls, body) in zip(self.heads, cells, strict=True):
            attr = f' class="{cls}"' if cls else ""
            tds.append(f'<td{attr} data-l="{esc(head)}">{body}</td>')
        self.rows.append("<tr>" + "".join(tds) + "</tr>")

    def html(self) -> str:
        head = "<tr>" + "".join(f"<th>{esc(h)}</th>" for h in self.heads) + "</tr>"
        return f'<div class="tablewrap stack"><table>{head}{"".join(self.rows)}</table></div>'


def status_chip(status: str | None) -> str:
    """The build check's words in ink, with no status colour: the colours belong to did-it-land."""
    return f'<span class="status">{esc(status or "not confirmed")}</span>'


def _pct(v: float) -> str:
    return f"{round(v, 1):g}"


def range_line(actual: float, prior: float | None = None, target: float | None = None, ci: tuple | list | None = None) -> str:
    """The scorecard's range line on 0 to 100: the 95% interval as a grey band, a grey dot for the prior version,
    an ink dot for the actual, a tick for the target. No healthy-side band: on the template that band is green."""
    parts = ['<i class="tr"></i>']
    if ci:
        parts.append(f'<i class="ci" style="left:{_pct(ci[0])}%;width:{_pct(max(0.5, ci[1] - ci[0]))}%"></i>')
    if prior is not None:
        lo, hi = sorted((prior, actual))
        parts.append(f'<i class="mv" style="left:{_pct(lo)}%;width:{_pct(hi - lo)}%"></i><i class="pr" style="left:{_pct(prior)}%"></i>')
    if target is not None:
        parts.append(f'<i class="goal" style="left:{_pct(target)}%"></i>')
    parts.append(f'<i class="ac" style="left:{_pct(actual)}%"></i>')
    return f'<span class="bl" aria-hidden="true">{"".join(parts)}</span>'


def money(x: float) -> str:
    return f"${x:,.4f}".rstrip("0").rstrip(".") if x < 1 else f"${x:,.2f}"


def sc_row(name: str, desc: str, picture: str, line: str, check: str) -> str:
    return (
        f'<div class="sc-r"><div class="sc-n"><span>{esc(name)}</span><span class="sc-d">{desc}</span></div>'
        f'<div class="sc-v">{picture}<span class="sc-l">{line}</span></div><div class="sc-s">{check}</div></div>'
    )


def scorecard(latest: dict, before: dict | None, target: float | None, own: str | None, against: dict | None) -> str:
    led = latest["ledger"]
    lo, hi = latest["pass_ci"]
    prior = before["pass_rate"] if before else None
    base = f"{prior:g}% <i>&rarr;</i> " if prior is not None else ""
    tgt = f" &middot; <em>Target</em> {target:g}%" if target is not None else ""
    rows = [
        sc_row(
            "Held-out pass rate",
            f"{latest['passed']} of {latest['cases']} cases &middot; 95% {lo:g} to {hi:g} &middot; {esc(led['pass_rate'])}",
            range_line(latest["pass_rate"], prior, target, latest["pass_ci"]),
            f"{base}<b>{latest['pass_rate']:g}%</b>{tgt}",
            status_chip(own) if target is not None else "",
        )
    ]
    if latest["autonomy_rate"] is not None:
        a_prior = before["autonomy_rate"] if before else None
        a_base = f"{a_prior:g}% <i>&rarr;</i> " if a_prior is not None else ""
        bar, check = "", ""
        if against and against.get("judged") == "autonomy_rate":
            bar, check = f" &middot; <em>Bar</em> {esc(against['bar'])}", status_chip(against["status"])
        rows.append(
            sc_row(
                "Without a person",
                f"{latest['tasks_unassisted']} of {latest['tasks']} tasks &middot; 95% {latest['autonomy_ci'][0]:g} to {latest['autonomy_ci'][1]:g} &middot; {esc(led['autonomy_rate'])}",
                range_line(latest["autonomy_rate"], a_prior, None, latest["autonomy_ci"]),
                f"{a_base}<b>{latest['autonomy_rate']:g}%</b>{bar}",
                check,
            )
        )
    if latest["cost_per_task"] is not None:
        rows.append(
            sc_row(
                "Cost per task", f"cited from cost-budget-check &middot; {esc(led['cost_per_task'])}", "", f"<b>{esc(money(latest['cost_per_task']))}</b>", ""
            )
        )
    else:
        rows.append(sc_row("Cost per task", "cost not checked: run cost-budget-check", "", "<b>not checked</b>", ""))
    head = '<div class="sc-h"><span>Figure</span><span>Prior &rarr; now &middot; target</span><span>Check</span></div>'
    return f'<div class="tablewrap sc">{head}{"".join(rows)}</div>'


def summary(report: dict, evals: dict | None, latest: dict, status: str | None) -> list[tuple[str, str]]:
    """Five lines a leader can read in 30 seconds."""
    target = report["target"]
    lo, hi = latest["pass_ci"]
    tgt = f" against a {target:g}% target" if target is not None else ", no target set"
    lines = [("Build check", f"{status_chip(status)}")]
    lines.append(("Held-out pass rate", esc(f"{latest['pass_rate']:g}% ({latest['passed']} of {latest['cases']}, 95% interval {lo:g} to {hi:g}){tgt}.")))
    if evals and evals["against_brief"]["judged"]:
        a = evals["against_brief"]
        v = "not computed" if a.get("value") is None else f"{a['value']:g}%"
        lines.append(("Against the brief", f"{status_chip(a['status'])} {esc(a['metric'])} is {esc(v)} against a bar of {esc(a['bar'])} by {esc(a['by'])}."))
    elif evals:
        lines.append(("Against the brief", esc(evals["against_brief"]["note"])))
    else:
        lines.append(("Against the brief", "No landing brief given."))
    p = report["promotion"]
    if p:
        verb = "may replace" if p["promote"] else "may not replace"
        lines.append(("Promotion", esc(f"{p['challenger']} {verb} {p['champion']}: {p['reason']}.")))
    else:
        lines.append(("Promotion", "One version only, so nothing to compare."))
    if latest["cost_per_task"] is not None:
        lines.append(("Cost per task", esc(f"{money(latest['cost_per_task'])}, cited from cost-budget-check.")))
    else:
        lines.append(("Cost per task", "cost not checked: run cost-budget-check."))
    return lines


def headline(report: dict, latest: dict, status: str | None, reasons: list[str]) -> str:
    """The one-line answer: the build check word, then one short clause on why."""
    word = f"Build check: {status or 'not confirmed'}."
    lo, target = latest["pass_ci"][0], report["target"]
    if target is not None and status in (MEETS, NOISE):
        side = "stays at or above" if status == MEETS else "reaches under"
        return f"{word} {latest['passed']} of {latest['cases']} held-out cases pass ({latest['pass_rate']:g}%); the 95% interval {side} the {target:g}% target (low end {lo:g}%)."
    return f"{word} {cap(reasons[0])}." if reasons else word


def fold(title: str, body: str, open_: bool = False) -> str:
    return f"<details{' open' if open_ else ''}><summary>{esc(title)}</summary>{body}</details>"


def render(report: dict, evals: dict | None = None) -> str:
    rows = report["versions"]
    latest, before = rows[-1], (rows[-2] if len(rows) > 1 else None)
    status = evals["status"] if evals else report["status"]
    reasons = evals["reasons"] if evals else report["reasons"]
    target = report["target"]
    against = evals["against_brief"] if evals else None
    as_of = evals["as_of"] if evals else latest["run_at"]

    meta = f"<span>Evals</span><span>{esc(latest['version'])}</span><span>As of {esc(as_of)}</span>"
    if report["illustrative"]:
        meta += '<span class="ill">Illustrative</span>'
    answer = headline(report, latest, status, reasons)
    cover = (
        f'<section class="slide cover"><div class="brand">{MARK}<span translate="no">DACARD</span></div><div class="meta">{meta}</div>'
        f'<h1>{esc(report["feature"])}</h1><p class="lede">{esc(answer)}</p>'
        '<ul class="summary">' + "".join(f"<li><b>{esc(k)}</b><span>{v}</span></li>" for k, v in summary(report, evals, latest, status)) + "</ul></section>"
    )
    score = (
        '<section class="slide"><div class="meta"><span>Scorecard</span></div><h2>Every figure, against its target</h2>'
        f"{scorecard(latest, before, target, report['status'], against)}</section>"
    )

    detail: list[str] = []
    why = "".join(f"<li>{esc(cap(r))}.</li>" for r in reasons)
    body = f"<ul>{why}</ul>"
    if against:
        if against["judged"]:
            v = "not computed" if against.get("value") is None else f"{against['value']:g}%"
            body += (
                f"<p>Against the landing brief: {status_chip(against['status'])} {esc(against['metric'])} is <b>{esc(v)}</b> "
                f"against a bar of {esc(against['bar'])} ({esc(against['better'])} is better) by {esc(against['by'])}.</p>"
            )
            if against.get("note"):
                body += f"<p>{esc(cap(against['note']))}.</p>"
        else:
            body += f"<p>Against the landing brief: {esc(against['note'])}</p>"
    detail.append(fold("Why the build check reads this way", body, open_=True))

    p = report["promotion"]
    if p:
        verb = "may replace" if p["promote"] else "may not replace"
        body = f"<p>{esc(p['challenger'])} {verb} {esc(p['champion'])}: {esc(p['reason'])}.</p>"
        if p["new_failures"]:
            body += f"<p>New held-out failures: {esc(', '.join(p['new_failures']))}.</p>"
        if p["within_noise"]:
            body += "<p>Each rate sits inside the other's 95% interval, so read the gain as direction, not size.</p>"
        detail.append(fold("Promotion", body))

    tab = Table(("Version", "Run", "Held-out pass", "Development pass", "Without a person", "Cost per task"))
    for r in rows:
        dev = f"{r['dev_passed']}/{r['dev_cases']} ({r['dev_pass_rate']:g}%)" if r["dev_pass_rate"] is not None else "not run"
        auto = f"{r['tasks_unassisted']}/{r['tasks']} ({r['autonomy_rate']:g}%)" if r["autonomy_rate"] is not None else "not run"
        cost = money(r["cost_per_task"]) + " (cited)" if r["cost_per_task"] is not None else "not checked"
        held = f"{r['passed']}/{r['cases']} ({r['pass_rate']:g}%)"
        tab.row(("", esc(r["version"])), *(("num", esc(v)) for v in (r["run_at"], held, dev, auto, cost)))
    detail.append(fold("By version", tab.html()))

    if report["clusters"]:
        body = "<p>Found with no categories set in advance, from development failures and production tasks that failed or needed a person.</p>"
        tab = Table(("Cluster", "Shared terms", "Share", "Read first"))
        for c in report["clusters"]:
            ex = "<br>".join(f"<span class='mono'>{esc(e['trace'])}</span> {esc(e['text'])}" for e in c["examples"])
            share = f'<span class="sh"><i style="width:{min(100, max(2, c["share"]))}%"></i></span>{c["size"]} &middot; {c["share"]}%'
            tab.row(("", esc(c["id"])), ("", esc(c["label"])), ("num", share), ("ex", ex))
        body += tab.html()
    else:
        body = "<p>No failures to read.</p>"
    body += f"<p>{report['held_out_failures_unread']} held-out failure(s) are counted and not read, so the holdout stays sealed.</p>"
    detail.append(fold("Failure modes", body))

    c = report["calibration"]
    if c is None:
        body = "<p>Not run. A judge-scored pass rate cannot meet the target until the judge clears the calibration cases.</p>"
    else:
        fa = ", ".join(c["false_accepts"]) or "none"
        body = f"<p>The judge agreed with the human verdict on {c['agreement']:g}% of {c['judged']} cases. False accepts: {esc(fa)}.</p>"
    detail.append(fold("Judge calibration", body))

    warnings = evals["warnings"] if evals else report["warnings"]
    if warnings:
        detail.append(fold("Warnings", "<ul>" + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>"))

    tab = Table(("Row", "Figure", "Value", "Basis", "Source", "Provenance"))
    for r in report["ledger"]:
        val = money(r["value"]) if r["unit"] == "$" else f"{r['value']:g}{r['unit']}"
        tab.row(("", esc(r["id"])), ("", esc(r["label"])), ("num", esc(val)), ("", esc(r["basis"])), ("ex", esc(r["source"])), ("", esc(r["provenance"])))
    detail.append(fold("Ledger", tab.html()))

    more = f'<section class="slide"><div class="meta"><span>Detail</span></div><h2>Reasons, versions and the ledger</h2>{"".join(detail)}</section>'
    title = esc(f"Evals: {report['feature']}")
    return (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title><style>{stylesheet()}{PAGE_CSS}</style></head><body><main class="solo">{cover}{score}{more}'
        '<p class="foot">A build check says whether the evals clear their target. It is not the bet\'s result: only did-it-land reads that. '
        "Every figure is computed in code from the traces named, and cost is cited from cost-budget-check.</p></main></body></html>\n"
    )
