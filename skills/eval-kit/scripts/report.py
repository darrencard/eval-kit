#!/usr/bin/env python3
"""The eval report for one AI feature, from a traces CSV. Computes every figure; the model writes none.

Per version it computes the held-out pass rate, the development pass rate beside it, autonomy (production tasks
finished with no person stepping in); cost per task is cited from cost-budget-check, never computed. It enforces the holdout split, checks the seal,
reads the judge's calibration, decides whether the latest version may replace the one before, and clusters the
failures it is allowed to read. Then it writes three files to --out:

  evals.csv    the Leader Report's `evals` source: version, run_at, cases, passed, cost_per_task, tasks, tasks_unassisted
  report.json  every figure with its ledger row, the status, the promotion verdict, clusters and calibration
  report.md    the same, for a person to read, with what the figures do and do not support

On any blocking error it writes nothing and exits non-zero with what to fix.

Usage:
  python3 scripts/report.py TRACES.csv --out run --feature "Quote drafting" [--map SCHEMA=YOURS] [--fail-on blocking] \\
      [--seal holdout.seal.json] [--judge-scores judge_scores.csv] [--target 85] [--illustrative]
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # checked first, before anything is read or written
    sys.exit("eval-kit needs Python 3.11 or later; try python3.12")

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calibration  # noqa: E402
import clusters  # noqa: E402
import holdout  # noqa: E402
import landing  # noqa: E402
import render_html  # noqa: E402
from evalcore import (  # noqa: E402
    BELOW,
    EVALS_COLUMNS,
    MEETS,
    NOISE,
    EvalError,
    Ledger,
    Trace,
    clears,
    load_traces,
    noise_reason,
    parse_map,
    pct,
    versions,
    wilson,
)

# A held-out rate this many points under target blocks the CI gate, not only reads below target.
STALL_MARGIN = 10.0
# Development ahead of holdout by more than this many points reads as tuning to the practice cases.
OVERFIT_GAP = 10.0


def version_row(traces: list[Trace], v: str) -> dict[str, Any]:
    rows = [t for t in traces if t.version == v]
    held = [t for t in rows if t.kind == "eval" and t.split == "holdout"]
    dev = [t for t in rows if t.kind == "eval" and t.split == "development"]
    prod = [t for t in rows if t.kind == "production"]
    if prod and not held:
        raise EvalError(f"version {v} has production tasks but no held-out eval cases. Autonomy is reported only beside its quality pair, the pass rate.")
    succeeded = [t for t in prod if t.succeeded]
    row: dict[str, Any] = {
        "version": v,
        "run_at": max(t.run_at for t in rows),
        "window_from": min(t.run_at for t in rows),
        "cases": len(held),
        "passed": sum(t.is_pass for t in held),
        "dev_cases": len(dev),
        "dev_passed": sum(t.is_pass for t in dev),
        "tasks": len(prod) or None,
        "tasks_unassisted": sum(1 for t in prod if t.succeeded and not t.human_stepped_in) if prod else None,
        "tasks_succeeded": len(succeeded) if prod else None,
        # Cost per task is cost-budget-check's figure (Landing Loop contract, one owner per figure). It is only
        # ever cited here, from the record's cost key, never computed from trace costs.
        "cost_per_task": None,
        "judge_scored": any(t.passed is None for t in held + dev),
    }
    row["pass_rate"] = pct(row["passed"], row["cases"])
    row["dev_pass_rate"] = pct(row["dev_passed"], row["dev_cases"]) if dev else None
    row["autonomy_rate"] = pct(row["tasks_unassisted"], row["tasks"]) if prod else None
    row["pass_ci"] = wilson(row["passed"], row["cases"])
    row["autonomy_ci"] = wilson(row["tasks_unassisted"], row["tasks"]) if prod else None
    return row


FAIL_ON = ("below-target", "blocking")


def decide_status(
    latest: dict, target: float | None, sealed: bool, calib: dict | None, verdict: holdout.Verdict | None, before: dict | None = None
) -> tuple[str | None, bool, list[str]]:
    """(status, blocking, reasons) for the latest version.

    status is "meets target" only when the 95% interval's lower bound clears the target, so 24 of 30 never reads
    as a precise 80%. When the rate meets the target and the interval reaches under it, status is "not confirmed:
    inside noise", with the interval and the case count that would settle it. status is "below target" when the
    rate is under the target, and None when the run cannot confirm anything (no target, an unsealed holdout, an
    uncalibrated judge, development far ahead of holdout, or a new held-out failure). These are build checks, not a
    bet's status: landed, watch and stalled are did-it-land's words and never print here.
    blocking is True for what a CI gate should stop: a new held-out failure, or a rate far under target.
    """
    reasons: list[str] = []
    rate = latest["pass_rate"]
    if verdict and verdict.new_failures:
        why = [f"it fails {len(verdict.new_failures)} held-out case(s) {verdict.champion} passed"]
        # Goodhart guard: autonomy bought with quality is not progress. Name it when the pair moves apart.
        if before and latest["autonomy_rate"] is not None and before["autonomy_rate"] is not None and latest["autonomy_rate"] > before["autonomy_rate"]:
            why.append(f"autonomy rose ({before['autonomy_rate']:g}% to {latest['autonomy_rate']:g}%) while held-out quality fell")
        below = target is not None and rate < target
        return (BELOW if below else None), True, why
    if target is None:
        return None, False, ["no target is set for the held-out pass rate"]
    if rate < target - STALL_MARGIN:
        return BELOW, True, [f"held-out pass rate {rate:g}% is more than {STALL_MARGIN:g} points under the {target:g}% target"]
    below = rate < target
    if below:
        reasons.append(f"held-out pass rate {rate:g}% is under the {target:g}% target")
    if not sealed:
        reasons.append("the holdout is not sealed, so it could have been tuned against")
    if latest["judge_scored"] and not (calib and calib["calibrated"]):
        reasons.append("a judge scored these cases and has not cleared its calibration cases")
    gap = None if latest["dev_pass_rate"] is None else round(latest["dev_pass_rate"] - rate, 1)
    if gap is not None and gap > OVERFIT_GAP:
        reasons.append(f"development runs {gap:g} points ahead of holdout, which reads as tuning to the practice cases")
    if below:
        return BELOW, False, reasons
    noisy = not clears(latest["pass_ci"], target)
    if noisy:
        reasons.append(noise_reason("held-out pass rate", latest["passed"], latest["cases"], rate, latest["pass_ci"], target))
    if len(reasons) > 1 or (reasons and not noisy):
        return None, False, reasons
    if noisy:
        return NOISE, False, reasons
    lo = latest["pass_ci"][0]
    why = f"held-out pass rate {rate:g}% meets the {target:g}% target on a sealed holdout, and its 95% interval does not reach under it (low end {lo:g}%)"
    return MEETS, False, [why]


def status_text(status: str | None) -> str:
    """The status as printed: the word, or "not confirmed" when the run can confirm neither."""
    return status or "not confirmed"


def build(args: argparse.Namespace) -> dict[str, Any]:
    src = Path(args.traces)
    traces = load_traces(src, parse_map(getattr(args, "map", None)))
    errors, warnings = holdout.check_splits(traces)
    sealed = False
    if args.seal:
        errors += holdout.verify(traces, Path(args.seal))
        sealed = not errors
    else:
        warnings.append("no --seal given: the holdout is unsealed, so no version can be confirmed as meeting the target.")
    if errors:
        raise EvalError("the report is blocked. " + " ".join(errors))

    order = versions([t for t in traces if t.kind == "eval"]) or versions(traces)
    rows = [version_row(traces, v) for v in versions(traces)]
    rows.sort(key=lambda r: order.index(r["version"]) if r["version"] in order else len(order))
    latest = rows[-1]
    before = rows[-2] if len(rows) > 1 else None

    calib = None
    if args.judge_scores:
        cases = calibration.load_cases(Path(args.calibration_cases) if args.calibration_cases else None)
        set_errors = calibration.check_set(cases)
        if set_errors:
            raise EvalError("the calibration cases are not fit to test a judge. " + " ".join(set_errors))
        calib = calibration.check_judge(cases, Path(args.judge_scores))

    verdict = holdout.judge_promotion(traces, before["version"], latest["version"]) if before else None
    status, blocking, reasons = decide_status(latest, args.target, sealed, calib, verdict, before)

    ledger = Ledger(src, args.illustrative)
    for r in rows:
        v = r["version"]
        r["ledger"] = {
            "pass_rate": ledger.add(
                f"Held-out pass rate ({v})",
                r["pass_rate"],
                "%",
                f"{r['passed']} of {r['cases']} holdout eval rows passed; 95% interval {r['pass_ci'][0]:g} to {r['pass_ci'][1]:g}",
            ),
        }
        if r["dev_pass_rate"] is not None:
            r["ledger"]["dev_pass_rate"] = ledger.add(
                f"Development pass rate ({v})", r["dev_pass_rate"], "%", f"{r['dev_passed']} of {r['dev_cases']} development eval rows passed"
            )
        if r["autonomy_rate"] is not None:
            r["ledger"]["autonomy_rate"] = ledger.add(
                f"Tasks finished without a person ({v})",
                r["autonomy_rate"],
                "%",
                f"{r['tasks_unassisted']} of {r['tasks']} production rows succeeded with human_stepped_in false; "
                f"95% interval {r['autonomy_ci'][0]:g} to {r['autonomy_ci'][1]:g}",
            )
    cost_key = getattr(args, "cost_key", None)
    if cost_key is None and getattr(args, "record", None):
        cost_key = landing.read_record_cost(Path(args.record))
    cite_cost(rows, cost_key, ledger, warnings)

    failed = clusters.failures(traces, latest["version"])
    held_failed = latest["cases"] - latest["passed"]
    return {
        "feature": args.feature,
        "illustrative": args.illustrative,
        "source": ledger.rows[0]["source"] if ledger.rows else src.name,
        "target": args.target,
        "sealed": sealed,
        "versions": rows,
        "latest": latest["version"],
        "status": status,
        "blocking": blocking,
        "reasons": reasons,
        "promotion": asdict(verdict) if verdict else None,
        "calibration": calib,
        "clusters": clusters.cluster(failed, clusters.passes(traces, latest["version"])),
        "held_out_failures_unread": held_failed,
        "warnings": warnings,
        "ledger": ledger.rows,
    }


COST_OWNER = "cost-budget-check"
COST_MISSING = f"cost not checked: run {COST_OWNER}"


def cite_cost(rows: list[dict], cost: dict | None, ledger: Ledger, warnings: list[str]) -> None:
    """Cost per task is cost-budget-check's figure. Cite it from the loop record's `cost` key onto the latest version,
    or print none. eval-kit never computes a cost of its own, so there is one cost figure in the loop, not two."""
    for r in rows:
        r["cost_per_task"] = None
    fig = (cost or {}).get("cost_per_successful_task") or ((cost or {}).get("lines", {}).get("cost_per_task") or {}).get("actual")
    if not isinstance(fig, dict) or fig.get("value") is None:
        warnings.append(COST_MISSING + ". No cost figure is printed until it writes the cost key.")
        return
    latest = rows[-1]
    latest["cost_per_task"] = round(float(fig["value"]), 4)
    window = fig.get("window") or {}
    latest["ledger"]["cost_per_task"] = ledger.add(
        f"Cost per task ({latest['version']}), cited",
        latest["cost_per_task"],
        "$",
        f"cited from the cost key ({(cost or {}).get('tool', COST_OWNER)}), window {window.get('from')} to {window.get('to')}",
        source=str(fig.get("source", COST_OWNER)),
    )


def fmt_money(x: float) -> str:
    return f"${x:,.4f}".rstrip("0").rstrip(".") if x < 1 else f"${x:,.2f}"


def fmt_value(value: float, unit: str) -> str:
    return fmt_money(value) if unit == "$" else f"{value:g}{unit}"


def write_evals_csv(report: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(EVALS_COLUMNS)
        for r in report["versions"]:
            w.writerow(["" if r[c] is None else r[c] for c in EVALS_COLUMNS])


def markdown(report: dict, evals: dict | None = None) -> str:
    latest = next(r for r in report["versions"] if r["version"] == report["latest"])
    led = latest["ledger"]
    out = [f"# Evals: {report['feature']}", ""]
    if report["illustrative"]:
        out += ["> Illustrative. Sample data for Acme, an invented company. No figure here is a real measurement.", ""]
    status = evals["status"] if evals else report["status"]
    why = "; ".join(evals["reasons"] if evals else report["reasons"])
    out.append(f"**Status: {status_text(status)}.** {why[:1].upper()}{why[1:]}.")
    out.append("")
    if evals:
        a = evals["against_brief"]
        if a["judged"]:
            v = "not computed" if a.get("value") is None else f"{a['value']:g}%"
            out.append(f"Against the landing brief: **{status_text(a['status'])}**. {a['metric']} is {v} against a bar of {a['bar']} by {a['by']}.")
            if a.get("note"):
                out.append(f"{a['note'][:1].upper()}{a['note'][1:]}.")
        else:
            out.append(f"Against the landing brief: {a['note']}")
        out.append("")
    lo, hi = latest["pass_ci"]
    line = (
        f"Version {latest['version']} passes {latest['passed']} of {latest['cases']} held-out cases ({latest['pass_rate']:g}%, "
        f"95% interval {lo:g} to {hi:g}) [{led['pass_rate']}]"
    )
    if latest["dev_pass_rate"] is not None:
        line += f", against {latest['dev_pass_rate']:g}% on development [{led['dev_pass_rate']}]"
    out.append(line + ".")
    if latest["autonomy_rate"] is not None:
        out.append(
            f"It finished {latest['tasks_unassisted']} of {latest['tasks']} production tasks with no person stepping in "
            f"({latest['autonomy_rate']:g}%, 95% interval {latest['autonomy_ci'][0]:g} to {latest['autonomy_ci'][1]:g}) [{led['autonomy_rate']}]."
        )
    if latest["cost_per_task"] is not None:
        out.append(f"Cost per task, cited from cost-budget-check: {fmt_money(latest['cost_per_task'])} [{led['cost_per_task']}].")
    else:
        out.append(f"Cost: {COST_MISSING}.")
    out.append("")
    if report["promotion"]:
        p = report["promotion"]
        verb = "may replace" if p["promote"] else "may not replace"
        out += ["## Promotion", "", f"{p['challenger']} {verb} {p['champion']}: {p['reason']}.", ""]
        if p["gained"]:
            out += [f"It newly passes {len(p['gained'])} held-out case(s): {', '.join(p['gained'])}.", ""]
        if p["within_noise"]:
            out += ["Each rate sits inside the other's 95% interval, so read the gain as direction, not size. More held-out cases would measure it.", ""]
        if p["new_failures"]:
            out += [f"New held-out failures: {', '.join(p['new_failures'])}.", ""]
    out += ["## By version", "", "| Version | Run | Held-out pass | Development pass | Without a person | Cost per task |"]
    out.append("|---|---|---|---|---|---|")
    for r in report["versions"]:
        out.append(
            f"| {r['version']} | {r['run_at']} | {r['passed']}/{r['cases']} ({r['pass_rate']:g}%) | "
            + (f"{r['dev_passed']}/{r['dev_cases']} ({r['dev_pass_rate']:g}%)" if r["dev_pass_rate"] is not None else "not run")
            + " | "
            + (f"{r['tasks_unassisted']}/{r['tasks']} ({r['autonomy_rate']:g}%)" if r["autonomy_rate"] is not None else "not run")
            + " | "
            + (fmt_money(r["cost_per_task"]) + " (cited)" if r["cost_per_task"] is not None else "not checked")
            + " |"
        )
    out += ["", "## Failure modes", ""]
    if report["clusters"]:
        out += ["Clustered from development failures and production tasks that failed or needed a person. No categories were set in advance.", ""]
        out += ["| Cluster | Shared terms | Traces | Share |", "|---|---|---|---|"]
        out += [f"| {c['id']} | {c['label']} | {c['size']} | {c['share']}% |" for c in report["clusters"]]
        out += ["", "Read these before naming a cluster:", ""]
        for c in report["clusters"][:5]:
            for e in c["examples"]:
                out.append(f"- {c['id']} `{e['trace']}`: {e['text']}")
    else:
        out.append("No failures to read.")
    out += ["", f"{report['held_out_failures_unread']} held-out failure(s) are counted above and not read, so the holdout stays sealed.", ""]
    c = report["calibration"]
    out += ["## Judge calibration", ""]
    if c is None:
        out.append("Not run. A judge-scored pass rate cannot meet the target until the judge clears the calibration cases.")
    else:
        out.append(
            f"The judge agreed with the human verdict on {c['agreement']:g}% of {c['judged']} cases. "
            f"False accepts: {', '.join(c['false_accepts']) or 'none'}. False rejects: {', '.join(c['false_rejects']) or 'none'}."
        )
    out += ["", "## What these figures support", ""]
    out.append(f"- Say: the held-out pass rate for {latest['version']}, with its case count. Quote autonomy only beside it.")
    out.append("- Do not say: a development pass rate as the headline, a gain without a promotion verdict that allows it, or a cause for any change.")
    if report["warnings"]:
        out += ["", "## Warnings", ""] + [f"- {w}" for w in report["warnings"]]
    out += ["", "## Ledger", "", "| Row | Figure | Value | Basis | Source | Provenance |", "|---|---|---|---|---|---|"]
    out += [f"| {r['id']} | {r['label']} | {fmt_value(r['value'], r['unit'])} | {r['basis']} | {r['source']} | {r['provenance']} |" for r in report["ledger"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("traces")
    p.add_argument("--out", required=True)
    p.add_argument("--feature", required=True, help="the AI feature these traces are for")
    p.add_argument("--seal")
    p.add_argument("--judge-scores")
    p.add_argument("--calibration-cases", help="a JSON file of your own calibration cases; defaults to the built-in set")
    p.add_argument("--target", type=float, help="target held-out pass rate, in percent")
    p.add_argument("--illustrative", action="store_true", help="mark every figure Illustrative (sample data)")
    p.add_argument("--map", action="append", metavar="SCHEMA=YOURS", help="read your export's column as a schema column; repeat per column")
    p.add_argument(
        "--fail-on",
        choices=FAIL_ON,
        help="for a CI gate: below-target exits 2 unless the status is meets target; blocking exits 2 on a new held-out failure or a rate far under target",
    )
    p.add_argument("--record", help="a Landing Loop record, landing/<bet>.json, to cite cost per task from its cost key")
    args = p.parse_args(argv)
    report = write(build(args), Path(args.out))
    gate(report, args.fail_on)


def gate(report: dict, fail_on: str | None, evals: dict | None = None) -> None:
    """For CI: exit 2 when --fail-on trips. The files are written first, so the run can be read.

    below-target trips unless the status is meets target; blocking trips on a new held-out failure or a held-out
    rate far under target. With the evals key (run.py passes it), its status and blocking are the ones read."""
    src = evals if evals else report
    status, blocking = src["status"], src["blocking"]
    if (fail_on == "below-target" and status != MEETS) or (fail_on == "blocking" and blocking):
        print(f"report: failing the gate, {report['latest']}: {status_text(status)} (--fail-on {fail_on})")
        raise SystemExit(2)


def write(report: dict, out: Path, evals: dict | None = None, brief: Any = None) -> dict:
    """evals.csv, report.json, report.html (for leaders) and report.md (its plain-text twin)."""
    out.mkdir(parents=True, exist_ok=True)
    write_evals_csv(report, out / "evals.csv")
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(markdown(report, evals), encoding="utf-8")
    (out / "report.html").write_text(render_html.render(report, evals, brief), encoding="utf-8")
    status = evals["status"] if evals else report["status"]
    print(f"report: {report['latest']}: {status_text(status)}; wrote evals.csv, report.json, report.html and report.md to {out}")
    for w in report["warnings"]:
        print(f"warning: {w}")
    return report


if __name__ == "__main__":
    main()
