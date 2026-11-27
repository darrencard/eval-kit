#!/usr/bin/env python3
"""The eval report as one self-contained HTML page, on the Leader Report's own template and the Landing Loop's one
visual family.

The page uses the report's whole stylesheet, taken from its template (vendor/template.html, vendored byte-identical
at the commit in vendor/VENDORED.json), and draws its picture with svgkit (vendor/svgkit.py, vendored byte-identical
from landing-loop). Only a few rules for this page's layout are added.

It reads top down for someone who has never run an eval: the shared header, the verdict as the heading, the likely
range of the pass rate against the target, then one thing to do next, owned by the person the landing brief names.
The figures follow in two columns. Version history and everything technical (status words as the record stores
them, reasons, ledger, record key) sit in folds. Public copy uses plain words: quality test, test cases kept back,
the likely range, too close to call.

Green, grey-white and red mean a project's landed, watch and stalled only, which did-it-land sets, so this page uses
none of them: the check prints as plain words in ink. Brass is the person who decides the next step. Every piece of
text from the traces is escaped. Nothing is fetched: the page works offline and from a file.
"""

from __future__ import annotations

import datetime
import html
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))

import svgkit as sk  # noqa: E402  (vendored, unchanged; see vendor/VENDORED.json)
from evalcore import BELOW, MEETS, NOISE, cases_to_clear  # noqa: E402
from landing import VERSION  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "vendor" / "template.html"
STYLE = re.compile(r"<style>(.*?)</style>", re.S)
NEXT_STEP_DAYS = 14

# Layout for this page only. Everything else comes from the template's stylesheet and svgkit.CSS.
PAGE_CSS = """
main.solo{margin-left:0}
.solo .slide{min-height:0}
.solo .slide.cover{min-height:0;padding-top:40px;padding-bottom:48px;justify-content:flex-start}
.solo h1{font-size:clamp(34px,4.6vw,60px);line-height:1;letter-spacing:-.04em;max-width:20ch;margin-bottom:20px}
.solo .lede{margin-bottom:24px}
.solo h2{margin-bottom:16px}
.status{display:inline-block;font:400 10px/16px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--t1);border:1px solid var(--line3);border-radius:3px;padding:1px 6px;white-space:nowrap}
.verdict{margin:0 0 20px}
.panel{border:1px solid var(--line);border-radius:12px;background:var(--s1);padding:24px 28px 20px}
@media (min-width:1100px){.panel .sk{display:grid;grid-template-columns:720px minmax(0,1fr);gap:16px 40px;align-items:center}.panel .sk figcaption{margin-top:0;flex-direction:column;align-items:flex-start}}
.next{margin-top:28px;display:grid;grid-template-columns:200px minmax(0,1fr);gap:8px 32px;align-items:baseline;border:1px solid var(--brass);border-radius:12px;padding:20px 24px;background:var(--brass-bg)}
.next>b{font:400 10px/22px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--brass)}
.next p{margin:0;font-size:16px;line-height:1.5;color:var(--t1)}
.next .who{display:flex;flex-wrap:wrap;gap:4px 24px;margin-top:10px;font:400 11.5px/16px var(--mono);color:var(--brass)}
.next .who span::before{font-size:10px;letter-spacing:.1em;color:var(--t3);margin-right:8px}
.next .who .o::before{content:"DECIDES"}.next .who .d::before{content:"DUE"}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px 56px;align-items:start}
.cols h3{margin-bottom:8px}
.figs{margin:0;display:grid}
.figs>div{display:grid;grid-template-columns:132px minmax(0,1fr);gap:4px 16px;border-top:1px solid var(--line);padding:11px 0}
.figs dt{font:400 10px/22px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--t3)}
.figs dd{margin:0;font-size:13.5px;line-height:1.55;color:var(--t2)}
.figs dd b{color:var(--t1);font-weight:500}
.fails{margin:0;padding:0;list-style:none}
.fails li{display:grid;grid-template-columns:64px minmax(0,1fr);gap:4px 16px;border-top:1px solid var(--line);padding:11px 0;font-size:13.5px;line-height:1.5;color:var(--t2)}
.fails .pc{font:400 12px/20px var(--mono);color:var(--t1);font-variant-numeric:tabular-nums}
.fails .pc i{display:block;height:4px;margin-top:6px;border-radius:1px;background:var(--agent)}
.fails small{display:block;font:400 10px/16px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--t3);margin-top:2px}
.solo details{margin-top:4px}
.solo details>*:not(summary){margin-top:12px}
.solo details p,.solo details li{margin:0 0 10px;font-size:13px;color:var(--t2);max-width:80ch}
.solo details ul{padding-left:18px}
.tablewrap td,.tablewrap th{overflow-wrap:anywhere}
.tablewrap .ex{font-size:12px;color:var(--t3)}
::selection{background:var(--t1);color:var(--bg)}
:focus-visible{outline-color:var(--t1)}
.foot{max-width:1120px;margin:0 auto;padding:28px 40px 64px;color:var(--t3);font-size:12px}
@media (max-width:980px){.foot{padding:24px 16px 48px}.solo .slide.cover{padding-top:24px}.cols,.next{grid-template-columns:1fr}.panel{padding:18px 16px 16px}
.stack table,.stack tbody,.stack tr,.stack td{display:block}.stack tr:first-child{display:none}.stack tr{padding:10px 16px;border-bottom:1px solid var(--line)}
.stack td{border:0;padding:3px 0;display:grid;grid-template-columns:118px 1fr;gap:12px}.stack td.num{text-align:left;white-space:normal}
.stack td::before{content:attr(data-l);font:400 10px/20px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--t3)}}
@media (max-width:560px){.figs>div{grid-template-columns:1fr;gap:0}}
"""

# The check words as the record stores them, and as the page prints them.
PLAIN = {MEETS: "clears the target", BELOW: "below target", NOISE: "not confirmed: too close to call", None: "not confirmed"}
WORDS = (
    (r"\bheld-out cases\b", "test cases kept back"),
    (r"\bheld-out case\(s\)", "test case(s) kept back"),
    (r"\bheld-out\b", "kept-back"),
    (r"\bHeld-out\b", "Kept-back"),
    (r"\b95% interval\b", "likely range"),
    (r"\binside noise\b", "too close to call"),
    (r"\bchallenger\b", "the new version"),
    (r"\bchampion\b", "the current version"),
)


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def plain(text: str) -> str:
    for pattern, to in WORDS:
        text = re.sub(pattern, to, text)
    return text


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
    """The check's words in ink, with no status colour: the colours belong to did-it-land."""
    return f'<span class="status">{esc(PLAIN.get(status, status))}</span>'


def money(x: float) -> str:
    return f"${x:,.4f}".rstrip("0").rstrip(".") if x < 1 else f"${x:,.2f}"


def fold(title: str, body: str, open_: bool = False) -> str:
    return f"<details{' open' if open_ else ''}><summary>{esc(title)}</summary>{body}</details>"


def pct(v: float) -> str:
    return f"{v:g}%"


# The signature picture


def range_chart(rows: list[dict], target: float | None, status: str | None, variant: str) -> str:
    """Each version's pass rate on the test cases kept back, as its likely range with the rate on it, against the
    target. The newest is ink, earlier ones grey. The part of the newest range short of the target is hatched."""
    wide = variant == "wide"
    width = sk.WIDE if wide else sk.TALL
    step = 64 if wide else 70
    top = 40
    height = top + step * len(rows) + (6 if wide else 0)
    x0, x1 = (128.0, 566.0) if wide else (50.0, 290.0)
    lows = [r["pass_ci"][0] for r in rows] + ([target] if target is not None else [])
    highs = [r["pass_ci"][1] for r in rows] + ([target] if target is not None else [])
    lo, hi = max(0.0, min(lows) - 8), min(100.0, max(highs) + 8)
    x = sk.scale((lo, hi), (x0, x1))
    hid = f"sk-ek-hatch-{variant}"
    parts = [sk.defs(sk.hatch_pattern(hid))]
    latest = rows[-1]
    for i, r in enumerate(rows):
        newest = r is latest
        tone = sk.INK if newest else sk.MUTED
        ry = top + step * i + (step / 2 if wide else 46)
        a, b = r["pass_ci"]
        parts.append(sk.range_bar(x(a), x(b), ry, height=12, tone=sk.LINE3 if newest else sk.LINE2))
        if newest and target is not None and a < target:
            cut = min(b, target)
            parts.append(sk.hatched(x(a), ry - 6, x(cut) - x(a), 12, pattern_id=hid))
        parts.append(sk.point(x(r["pass_rate"]), ry, r=6 if newest else 5, fill=tone))
        name = f"{r['version']} · {r['run_at']}"
        count = f"{r['passed']} of {r['cases']} pass"
        if wide:
            parts.append(sk.label(0, ry - 3, r["version"], tone=sk.INK if newest else sk.INK2))
            parts.append(sk.label(0, ry + 13, r["run_at"]))
            parts.append(sk.label(x(a) - 8, ry + 4, pct(a), anchor="end"))
            parts.append(sk.label(x(b) + 8, ry + 4, pct(b)))
            parts.append(sk.value(600, ry + 2, pct(r["pass_rate"]), size=22 if newest else 18, tone=tone))
            parts.append(sk.label(600, ry + 20, count))
        else:
            parts.append(sk.label(0, ry - 22, name, tone=sk.INK if newest else sk.INK2))
            parts.append(sk.value(width, ry - 20, pct(r["pass_rate"]), anchor="end", size=18, tone=tone))
            parts.append(sk.label(x(a) - 6, ry + 4, pct(a), anchor="end"))
            parts.append(sk.label(x(b) + 6, ry + 4, pct(b)))
    if target is not None:
        tx = x(target)
        parts.append(sk.target_tick(tx, top - 10, height - 4))
        parts.append(sk.label(tx, top - 18, f"Target {pct(target)}", anchor="middle", tone=sk.INK2))
    n = latest
    verdict = PLAIN.get(status, status)
    aria = f"{n['version']} passes {n['passed']} of {n['cases']} test cases kept back, {pct(n['pass_rate'])}; the likely range is {pct(n['pass_ci'][0])} to {pct(n['pass_ci'][1])}"
    aria += f" against a {pct(target)} target, so it is {verdict}." if target is not None else ", with no target set."
    return sk.frame("".join(parts), label=aria, height=height, width=width, variant=variant)


# The words


def heading(feature: str, status: str | None) -> str:
    says = {MEETS: "clears its target", BELOW: "is below its target", NOISE: "is too close to call"}.get(status, "is not confirmed yet")
    return f"{feature} {says}."


def lede(latest: dict, target: float | None, status: str | None) -> str:
    lo, hi = latest["pass_ci"]
    text = f"{latest['passed']} of {latest['cases']} test cases kept back pass, {pct(latest['pass_rate'])}. The likely range is {pct(lo)} to {pct(hi)}"
    if target is None:
        text += ", and no target is set."
    elif status == NOISE:
        text += f", which reaches under the {pct(target)} target, so this quality test cannot confirm it yet."
        if latest["pass_rate"] == target:
            text += " A pass rate exactly at the target never clears it, however many cases are added."
    elif status == MEETS:
        text += f", all of it above the {pct(target)} target."
    else:
        text += f", against a {pct(target)} target."
    return text + " Cases kept back are never used to tune the AI, so they can't be gamed."


def next_step(latest: dict, target: float | None, status: str | None, clusters: list[dict]) -> str:
    if target is None:
        return "Set a target in the landing brief, then run the quality test again."
    if status == NOISE:
        need = cases_to_clear(latest["pass_rate"], target)
        if need is None:
            return f"Improve the AI so it passes more than {pct(target)} of the test cases kept back, then run the quality test again. More cases alone cannot clear the target at this rate."
        return f"Add test cases kept back, then run the quality test again: at the same rate, {need} cases would clear the target."
    if status == BELOW:
        first = f" Start with the most common way it fails ({clusters[0]['share']}% of failures)." if clusters else ""
        return "Fix the AI, then run the quality test again." + first
    if status == MEETS:
        return "Release it to the next stage; did-it-land will read whether the project's number moves."
    return "Fix what stops the check, listed below, then run the quality test again."


def due_date(as_of: str, by: str | None) -> str:
    """The brief's date while it is ahead of the run; else NEXT_STEP_DAYS after it."""
    run = datetime.date.fromisoformat(as_of[:10])
    if by and datetime.date.fromisoformat(by) > run:
        return by
    return str(run + datetime.timedelta(days=NEXT_STEP_DAYS))


def figures(report: dict, evals: dict | None, latest: dict) -> str:
    lo, hi = latest["pass_ci"]
    rows = [("Test cases kept back", f"<b>{latest['passed']} of {latest['cases']} pass, {pct(latest['pass_rate'])}</b>. Likely range {pct(lo)} to {pct(hi)}.")]
    if latest["dev_pass_rate"] is not None:
        rows.append(
            (
                "Practice cases",
                f"{latest['dev_passed']} of {latest['dev_cases']} pass, {pct(latest['dev_pass_rate'])}. Not the headline: the AI was tuned on these.",
            )
        )
    if latest["autonomy_rate"] is not None:
        a, b = latest["autonomy_ci"]
        rows.append(
            (
                "Without a person",
                f"{latest['tasks_unassisted']} of {latest['tasks']} real tasks finished with no person stepping in, {pct(latest['autonomy_rate'])}. "
                f"Likely range {pct(a)} to {pct(b)}.",
            )
        )
    if latest["cost_per_task"] is not None:
        rows.append(("Cost per task", f"{esc(money(latest['cost_per_task']))}, from the cost check."))
    else:
        rows.append(("Cost per task", "Not checked yet: run cost-budget-check."))
    p = report["promotion"]
    if p:
        verb = "may replace" if p["promote"] else "may not replace"
        text = f"{esc(p['challenger'])} {verb} {esc(p['champion'])}: {esc(plain(p['reason']))}."
        if p["within_noise"]:
            text += " The two likely ranges overlap, so read the gain as direction, not size."
        rows.append(("New version", text))
    if evals:
        a = evals["against_brief"]
        if a["judged"]:
            v = "not computed" if a.get("value") is None else pct(a["value"])
            rows.append(
                (
                    "The plan's number",
                    f"{esc(plain(a['metric']))} is {esc(v)} against a target of {esc(a['bar'])} by {esc(a['by'])}: {status_chip(a['status'])}",
                )
            )
        else:
            rows.append(("The plan's number", f"{esc(a['metric'])} is not a quality test figure. did-it-land reads it against the landing brief."))
    return '<dl class="figs">' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows) + "</dl>"


def failures(report: dict) -> str:
    items = []
    for c in report["clusters"]:
        # The example's last part is the note a person wrote, the plainest account of what went wrong.
        ex = c["examples"][0]["text"].split(" / ")[-1] if c["examples"] else c["label"]
        items.append(
            f'<li><span class="pc">{c["share"]}%<i style="width:{min(100, max(4, c["share"]))}%"></i></span>'
            f"<span>{esc(ex)}<small>{c['size']} failures</small></span></li>"
        )
    body = f'<ul class="fails">{"".join(items)}</ul>' if items else "<p>No failures to read.</p>"
    sealed = report["held_out_failures_unread"]
    return body + f'<p class="sc-d">{sealed} failure(s) on test cases kept back are counted and not read, so those cases stay unseen.</p>'


def marker(report: dict) -> str:
    c = report["calibration"]
    if c is None:
        return "<p>Not checked. A pass rate scored by an AI marker cannot clear the target until the marker is checked against known answers.</p>"
    fa = ", ".join(c["false_accepts"]) or "none"
    return f"<p>The AI marker agreed with a person on {c['agreement']:g}% of {c['judged']} known answers. Marked as passing when a person said fail: {esc(fa)}.</p>"


def render(report: dict, evals: dict | None = None, brief: Any = None) -> str:
    rows = report["versions"]
    latest = rows[-1]
    status = evals["status"] if evals else report["status"]
    reasons = evals["reasons"] if evals else report["reasons"]
    target = report["target"]
    as_of = evals["as_of"] if evals else latest["run_at"]

    header = sk.page_header("eval-kit", date=as_of, version=f"v{VERSION}", illustrative=report["illustrative"])
    pic = sk.figure(
        range_chart(rows, target, status, "wide"),
        range_chart(rows, target, status, "tall"),
        caption="Each bar is the likely range of a version's pass rate on the test cases kept back; the dot is the rate it scored. "
        "The dashed line is the target. Hatched: the part of the newest range that falls short of it.",
        illustrative=report["illustrative"],
    )
    owner = getattr(brief, "decides", None)
    who = f'<span class="o">{esc(owner)}</span>' if owner else ""
    step = (
        f'<div class="next"><b>What to do next</b><div><p>{esc(next_step(latest, target, status, report["clusters"]))}</p>'
        f'<span class="who">{who}<span class="d">{esc(due_date(as_of, getattr(brief, "by", None)))}</span></span></div></div>'
    )
    cover = (
        f'<section class="slide cover">{header}<h1>{esc(heading(report["feature"], status))}</h1>'
        f'<p class="lede">{esc(lede(latest, target, status))}</p><p class="verdict">{status_chip(status)}</p>'
        f'<div class="panel">{pic}</div>{step}</section>'
    )
    detail = (
        '<section class="slide"><div class="meta"><span>What the test found</span></div><div class="cols">'
        f"<div><h3>The figures</h3>{figures(report, evals, latest)}</div>"
        f'<div><h3>The common ways it fails</h3>{failures(report)}<h3 style="margin-top:28px">Checking the marker against known answers</h3>{marker(report)}</div>'
        "</div></section>"
    )

    folds: list[str] = []
    tab = Table(("Version", "Run", "Kept back", "Practice", "Without a person", "Cost per task"))
    for r in rows:
        dev = f"{r['dev_passed']}/{r['dev_cases']} ({r['dev_pass_rate']:g}%)" if r["dev_pass_rate"] is not None else "not run"
        auto = f"{r['tasks_unassisted']}/{r['tasks']} ({r['autonomy_rate']:g}%)" if r["autonomy_rate"] is not None else "not run"
        cost = money(r["cost_per_task"]) + " (cited)" if r["cost_per_task"] is not None else "not checked"
        held = f"{r['passed']}/{r['cases']} ({r['pass_rate']:g}%), likely range {pct(r['pass_ci'][0])} to {pct(r['pass_ci'][1])}"
        tab.row(("", esc(r["version"])), *(("num", esc(v)) for v in (r["run_at"], held, dev, auto, cost)))
    folds.append(fold("By version", tab.html()))

    eng = [f"<p>Status as the record stores it: <code>{esc(status or 'not confirmed')}</code>. Blocking: {'yes' if report['blocking'] else 'no'}.</p>"]
    eng.append("<ul>" + "".join(f"<li>{esc(cap(r))}.</li>" for r in reasons) + "</ul>")
    warnings = evals["warnings"] if evals else report["warnings"]
    if warnings:
        eng.append("<p>Warnings:</p><ul>" + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>")
    if report["clusters"]:
        ct = Table(("Cluster", "Shared terms", "Size", "Read first"))
        for c in report["clusters"]:
            ex = "<br>".join(f"<span class='mono'>{esc(x['trace'])}</span> {esc(x['text'])}" for x in c["examples"])
            ct.row(("", esc(c["id"])), ("", esc(c["label"])), ("num", f"{c['size']} &middot; {c['share']}%"), ("ex", ex))
        eng.append(ct.html())
    lt = Table(("Row", "Figure", "Value", "Basis", "Source", "Provenance"))
    for r in report["ledger"]:
        val = money(r["value"]) if r["unit"] == "$" else f"{r['value']:g}{r['unit']}"
        lt.row(("", esc(r["id"])), ("", esc(r["label"])), ("num", esc(val)), ("", esc(r["basis"])), ("ex", esc(r["source"])), ("", esc(r["provenance"])))
    eng.append(lt.html())
    eng.append(
        "<p>With --brief and --bet, the run adds its page to the project file: the <code>evals</code> key of <code>landing/&lt;bet&gt;.json</code>, "
        "and no other key. --fail-on below-target or blocking turns the check into a CI gate (exit code 2).</p>"
    )
    folds.append(fold("For your engineers", "".join(eng)))
    more = f'<section class="slide"><div class="meta"><span>Detail</span></div>{"".join(folds)}</section>'

    title = esc(f"Quality test: {report['feature']}")
    return (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title><style>{stylesheet()}{sk.CSS}{PAGE_CSS}</style></head><body><main class="solo">{cover}{detail}{more}'
        '<p class="foot">This quality test says whether the AI clears its target before release. It is not the project\'s result: only did-it-land reads that. '
        "Every figure is computed in code from the logs named, and cost is cited from cost-budget-check.</p></main></body></html>\n"
    )
