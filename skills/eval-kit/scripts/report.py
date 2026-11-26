#!/usr/bin/env python3
"""The eval report for one AI feature, from a traces CSV. Computes every figure; the model writes none.

Per version it computes the held-out pass rate, the development pass rate beside it, autonomy (production tasks
finished with no person stepping in) and cost per successful task. It enforces the holdout split, checks the seal,
reads the judge's calibration, decides whether the latest version may replace the one before, and clusters the
failures it is allowed to read. Then it writes three files to --out:

  evals.csv    the Leader Report's `evals` source: version, run_at, cases, passed, cost_per_task, tasks, tasks_unassisted
  report.json  every figure with its ledger row, the status, the promotion verdict, clusters and calibration
  report.md    the same, for a person to read, with what the figures do and do not support

On any blocking error it writes nothing and exits non-zero with what to fix.

Usage:
  python3 scripts/report.py TRACES.csv --out run --feature "Quote drafting" [--map SCHEMA=YOURS] [--fail-on stalled] \\
      [--seal holdout.seal.json] [--judge-scores judge_scores.csv] [--target 85] [--illustrative]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calibration  # noqa: E402
import clusters  # noqa: E402
import holdout  # noqa: E402
from evalcore import EvalError, Ledger, Trace, load_traces, parse_map, pct, versions, wilson  # noqa: E402

# The Leader Report's evals columns, in its order (product-engineering-update, scripts/collect.py).
EVALS_COLUMNS = ("version", "run_at", "cases", "passed", "cost_per_task", "tasks", "tasks_unassisted")
# A held-out rate this many points under target is stalled, not watch.
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
    costs = [t.cost_usd for t in prod if t.cost_usd is not None]
    row: dict[str, Any] = {
        "version": v,
        "run_at": max(t.run_at for t in rows),
        "cases": len(held),
        "passed": sum(t.is_pass for t in held),
        "dev_cases": len(dev),
        "dev_passed": sum(t.is_pass for t in dev),
        "tasks": len(prod) or None,
        "tasks_unassisted": sum(1 for t in prod if t.succeeded and not t.human_stepped_in) if prod else None,
        "tasks_succeeded": len(succeeded) if prod else None,
        "cost_total": round(sum(costs), 4) if prod and len(costs) == len(prod) else None,
        "cost_per_task": None,
        "cost_partial": bool(prod) and 0 < len(costs) < len(prod),
        "judge_scored": any(t.passed is None for t in held + dev),
    }
    if row["cost_total"] is not None and succeeded:
        row["cost_per_task"] = round(row["cost_total"] / len(succeeded), 4)
    row["pass_rate"] = pct(row["passed"], row["cases"])
    row["dev_pass_rate"] = pct(row["dev_passed"], row["dev_cases"]) if dev else None
    row["autonomy_rate"] = pct(row["tasks_unassisted"], row["tasks"]) if prod else None
    row["pass_ci"] = wilson(row["passed"], row["cases"])
    row["autonomy_ci"] = wilson(row["tasks_unassisted"], row["tasks"]) if prod else None
    return row


def decide_status(
    latest: dict, target: float | None, sealed: bool, calib: dict | None, verdict: holdout.Verdict | None, before: dict | None = None
) -> tuple[str, list[str]]:
    """landed, watch or stalled for the latest version, with every reason. Nothing else prints as a status."""
    reasons: list[str] = []
    rate = latest["pass_rate"]
    if verdict and verdict.new_failures:
        why = [f"it fails {len(verdict.new_failures)} held-out case(s) {verdict.champion} passed"]
        # Goodhart guard: autonomy bought with quality is not progress. Name it when the pair moves apart.
        if before and latest["autonomy_rate"] is not None and before["autonomy_rate"] is not None and latest["autonomy_rate"] > before["autonomy_rate"]:
            why.append(f"autonomy rose ({before['autonomy_rate']:g}% to {latest['autonomy_rate']:g}%) while held-out quality fell")
        return "stalled", why
    if target is None:
        return "watch", ["no target is set for the held-out pass rate"]
    if rate < target - STALL_MARGIN:
        return "stalled", [f"held-out pass rate {rate:g}% is more than {STALL_MARGIN:g} points under the {target:g}% target"]
    if rate < target:
        reasons.append(f"held-out pass rate {rate:g}% is under the {target:g}% target")
    if not sealed:
        reasons.append("the holdout is not sealed, so it could have been tuned against")
    if latest["judge_scored"] and not (calib and calib["calibrated"]):
        reasons.append("a judge scored these cases and has not cleared its calibration cases")
    gap = None if latest["dev_pass_rate"] is None else round(latest["dev_pass_rate"] - rate, 1)
    if gap is not None and gap > OVERFIT_GAP:
        reasons.append(f"development runs {gap:g} points ahead of holdout, which reads as tuning to the practice cases")
    if reasons:
        return "watch", reasons
    return "landed", [f"held-out pass rate {rate:g}% meets the {target:g}% target on a sealed holdout"]


def build(args: argparse.Namespace) -> dict[str, Any]:
    src = Path(args.traces)
    traces = load_traces(src, parse_map(getattr(args, "map", None)))
    errors, warnings = holdout.check_splits(traces)
    sealed = False
    if args.seal:
        errors += holdout.verify(traces, Path(args.seal))
        sealed = not errors
    else:
        warnings.append("no --seal given: the holdout is unsealed, so no version can be marked landed.")
    if errors:
        raise EvalError("the report is blocked. " + " ".join(errors))

    order = versions([t for t in traces if t.kind == "eval"]) or versions(traces)
    rows = [version_row(traces, v) for v in versions(traces)]
    rows.sort(key=lambda r: order.index(r["version"]) if r["version"] in order else len(order))
    for r in rows:
        if r["cost_partial"]:
            warnings.append(f"version {r['version']}: some production rows have no cost_usd, so cost per task is not computed.")
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
    status, reasons = decide_status(latest, args.target, sealed, calib, verdict, before)

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
        if r["cost_per_task"] is not None:
            r["ledger"]["cost_per_task"] = ledger.add(
                f"Cost per successful task ({v})",
                r["cost_per_task"],
                "$",
                f"${r['cost_total']:g} cost_usd over {r['tasks_succeeded']} succeeded production rows",
            )

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
        "reasons": reasons,
        "promotion": asdict(verdict) if verdict else None,
        "calibration": calib,
        "clusters": clusters.cluster(failed, clusters.passes(traces, latest["version"])),
        "held_out_failures_unread": held_failed,
        "warnings": warnings,
        "ledger": ledger.rows,
    }


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


def markdown(report: dict) -> str:
    latest = next(r for r in report["versions"] if r["version"] == report["latest"])
    led = latest["ledger"]
    out = [f"# Evals: {report['feature']}", ""]
    if report["illustrative"]:
        out += ["> Illustrative. Sample data for Acme, an invented company. No figure here is a real measurement.", ""]
    why = "; ".join(report["reasons"])
    out.append(f"**Status: {report['status']}.** {why[:1].upper()}{why[1:]}.")
    out.append("")
    lo, hi = latest["pass_ci"]
    line = (
        f"Version {latest['version']} passes {latest['passed']} of {latest['cases']} held-out cases ({latest['pass_rate']:g}%, "
        f"95% interval {lo:g} to {hi:g}) [{led['pass_rate']}]"
    )
    if latest["dev_pass_rate"] is not None:
        line += f", against {latest['dev_pass_rate']:g}% on development [{led['dev_pass_rate']}]"
    out.append(line + ".")
    if report["target"] is not None and lo < report["target"] <= latest["pass_rate"]:
        out.append(f"The interval's low end, {lo:g}%, is under the {report['target']:g}% target. More held-out cases would settle it.")
    if latest["autonomy_rate"] is not None:
        out.append(
            f"It finished {latest['tasks_unassisted']} of {latest['tasks']} production tasks with no person stepping in "
            f"({latest['autonomy_rate']:g}%, 95% interval {latest['autonomy_ci'][0]:g} to {latest['autonomy_ci'][1]:g}) [{led['autonomy_rate']}]."
        )
    if latest["cost_per_task"] is not None:
        out.append(f"Cost per successful task: {fmt_money(latest['cost_per_task'])} [{led['cost_per_task']}].")
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
    out += ["## By version", "", "| Version | Run | Held-out pass | Development pass | Without a person | Cost per successful task |"]
    out.append("|---|---|---|---|---|---|")
    for r in report["versions"]:
        out.append(
            f"| {r['version']} | {r['run_at']} | {r['passed']}/{r['cases']} ({r['pass_rate']:g}%) | "
            + (f"{r['dev_passed']}/{r['dev_cases']} ({r['dev_pass_rate']:g}%)" if r["dev_pass_rate"] is not None else "not run")
            + " | "
            + (f"{r['tasks_unassisted']}/{r['tasks']} ({r['autonomy_rate']:g}%)" if r["autonomy_rate"] is not None else "not run")
            + " | "
            + (fmt_money(r["cost_per_task"]) if r["cost_per_task"] is not None else "not computed")
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
        out.append("Not run. A judge-scored pass rate cannot be marked landed until the judge clears the calibration cases.")
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
    p.add_argument("--fail-on", choices=("watch", "stalled"), help="exit 2 when the status is this bad or worse, for a CI gate")
    args = p.parse_args(argv)
    report = write(build(args), Path(args.out))
    gate(report, args.fail_on)


FAIL_ORDER = {"landed": 0, "watch": 1, "stalled": 2}


def gate(report: dict, fail_on: str | None) -> None:
    """For CI: exit 2 when the status is at or past --fail-on. The files are written first, so the run can be read."""
    if fail_on and FAIL_ORDER[report["status"]] >= FAIL_ORDER[fail_on]:
        print(f"report: failing the gate, {report['latest']} is {report['status']} (--fail-on {fail_on})")
        raise SystemExit(2)


def write(report: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    write_evals_csv(report, out / "evals.csv")
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    print(f"report: {report['latest']} is {report['status']}; wrote evals.csv, report.json and report.md to {out}")
    for w in report["warnings"]:
        print(f"warning: {w}")
    return report


if __name__ == "__main__":
    main()
