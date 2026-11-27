#!/usr/bin/env python3
"""The Landing Loop link: judge the evals against the feature's landing brief, and write the `evals` key of the
bet's loop record, landing/<bet>.json.

The brief is parsed by the vendored landing_brief.py, unchanged, so every skill in the loop reads one format.
The brief's definition of good is one metric, a bar, a direction and a date. When that metric is an eval figure
(the held-out pass rate, or tasks finished without a person) it is read here as meets target or below target
against the brief's bar. landed, watch and stalled are a bet's status, set only by did-it-land, so none prints here.
When it is a product metric, evals are the build check and did-it-land judges the metric; the key says so.

The record is shared. This writes only `evals` and keeps every other key exactly as it found it. It refuses a
record whose brief has changed since another step wrote it, since those keys were judged against another bar.

Usage:
  python3 scripts/landing.py check BRIEF.md     # parse the brief, and say which eval figure it judges
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # checked first, before anything is read or written
    sys.exit("eval-kit needs Python 3.11 or later; try python3.12")

import argparse
import datetime
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "vendor"))

import landing_brief  # noqa: E402  (vendored, unchanged; see vendor/VENDORED.json)
from evalcore import BELOW, EVALS_COLUMNS, MEETS, NOISE, EvalError, clears, noise_reason  # noqa: E402

SCHEMA = "landing-loop/1"
SKILL = "eval-kit"
VERSION = "0.3.4"
BET = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
# Which eval figure a brief's metric names. Matched on the metric's words, never guessed beyond these.
FIGURES = (
    ("autonomy_rate", ("autonomy", "without a person", "unassisted", "no person")),
    ("pass_rate", ("pass rate", "eval pass", "held-out", "holdout", "evals passed")),
)
LABELS = {"pass_rate": "Held-out pass rate", "autonomy_rate": "Tasks finished without a person"}


def read_brief(path: Path) -> landing_brief.Brief:
    try:
        return landing_brief.parse(landing_brief.description_of(path))
    except landing_brief.BriefError as exc:
        raise EvalError(f"the landing brief {path.name} cannot be used: {exc}") from None


def figure_for(metric: str) -> str | None:
    m = metric.lower()
    return next((name for name, words in FIGURES if any(w in m for w in words)), None)


def target_from(brief: landing_brief.Brief, cli_target: float | None) -> float | None:
    """The held-out pass-rate target: the brief's bar when the brief judges the pass rate, else --target."""
    if figure_for(brief.metric) != "pass_rate":
        return cli_target
    if brief.unit != "%":
        raise EvalError(f"the brief judges the pass rate, so its bar must be a percent; it is {brief.bar_text}.")
    if not brief.higher_is_better:
        raise EvalError("the brief judges the pass rate with Better: lower. A pass rate is better higher; fix the brief.")
    if cli_target is not None and cli_target != brief.bar:
        raise EvalError(f"the brief sets the bar at {brief.bar_text} and --target says {cli_target:g}%. Drop --target, or change the brief.")
    return brief.bar


def judge(brief: landing_brief.Brief, report: dict, as_of: str) -> dict[str, Any]:
    """The evals against the brief's definition of good: meets target or below target, never a bet's status."""
    rows = report["versions"]
    latest = rows[-1]
    before = rows[-2] if len(rows) > 1 else None
    base = {"metric": brief.metric, "bar": brief.bar_text, "better": "higher" if brief.higher_is_better else "lower", "by": brief.by}
    name = figure_for(brief.metric)
    if name is None:
        note = f"The brief's metric, {brief.metric}, is not an eval figure. did-it-land judges it; these evals are the build check."
        return {**base, "judged": None, "status": None, "note": note}
    value = latest[name]
    if value is None:
        return {**base, "judged": name, "status": None, "value": None, "note": f"{LABELS[name]} is not computed for {latest['version']}."}
    if brief.unit != "%":
        raise EvalError(f"the brief judges {LABELS[name].lower()}, a percent, but its bar is {brief.bar_text}.")
    prior = before[name] if before else None
    meets = value >= brief.bar if brief.higher_is_better else value <= brief.bar
    status = MEETS if meets else BELOW
    notes = []
    ci = latest["pass_ci"] if name == "pass_rate" else latest["autonomy_ci"]
    if meets and not clears(ci, brief.bar, brief.higher_is_better):
        # Same rule as the run's own status: a point estimate inside the noise does not meet the bar.
        status = NOISE
        part, whole = (latest["passed"], latest["cases"]) if name == "pass_rate" else (latest["tasks_unassisted"], latest["tasks"])
        notes.append(noise_reason(LABELS[name].lower(), part, whole, value, ci, brief.bar, brief.higher_is_better, "bar"))
    if not meets and datetime.date.fromisoformat(as_of) > datetime.date.fromisoformat(brief.by):
        notes.append(f"the date, {brief.by}, has passed")
    return {**base, "judged": name, "status": status, "value": value, "prior": prior, "note": "; ".join(notes)}


def combined(own: str | None, against: dict[str, Any]) -> str | None:
    """below target if either reads below; meets target only when both clear their bar outside the noise; not
    confirmed: inside noise when the only thing missing is an interval that clears the bar; else None."""
    theirs = against["status"] if against["judged"] else MEETS
    if BELOW in (own, theirs):
        return BELOW
    if own == MEETS and theirs == MEETS:
        return MEETS
    if {own, theirs} <= {MEETS, NOISE}:
        return NOISE
    return None


def figure(value: Any, unit: str, source: str, row: dict, as_of: str, ledger: str, interval: Any = None) -> dict[str, Any]:
    out = {"value": value, "unit": unit, "source": source, "window": {"from": row["window_from"], "to": row["run_at"]}, "as_of": as_of, "ledger": ledger}
    if interval:
        out["interval_95"] = list(interval)
    return out


def evals_key(report: dict, brief: landing_brief.Brief, as_of: str) -> dict[str, Any]:
    """The `evals` key: the Leader Report's evals columns, every figure with value, unit, source, window and as_of."""
    against = judge(brief, report, as_of)
    status = combined(report["status"], against)
    reasons = list(report["reasons"])
    if against["status"] == BELOW and report["status"] != BELOW:
        reasons.append(f"against the brief, {LABELS[against['judged']].lower()} is below target")
    warnings = list(report["warnings"])
    if brief.line == "fixed code":
        warnings.append("the brief puts the line at fixed code, but these are traces of a model call. Check the brief or the traces.")
    src = report["source"]
    figures: dict[str, Any] = {}
    for row in report["versions"]:
        v, led = row["version"], row["ledger"]
        figures[f"pass_rate@{v}"] = figure(row["pass_rate"], "%", src, row, as_of, led["pass_rate"], row["pass_ci"])
        if row["dev_pass_rate"] is not None:
            figures[f"dev_pass_rate@{v}"] = figure(row["dev_pass_rate"], "%", src, row, as_of, led["dev_pass_rate"])
        if row["autonomy_rate"] is not None:
            figures[f"autonomy_rate@{v}"] = figure(row["autonomy_rate"], "%", src, row, as_of, led["autonomy_rate"], row["autonomy_ci"])
        if row["cost_per_task"] is not None:
            lrow = next(x for x in report["ledger"] if x["id"] == led["cost_per_task"])
            figures[f"cost_per_task@{v}"] = figure(row["cost_per_task"], "$", lrow["source"], row, as_of, led["cost_per_task"])
    p = report["promotion"]
    return {
        "skill": SKILL,
        "skill_version": VERSION,
        "feature": report["feature"],
        "version": report["latest"],
        "as_of": as_of,
        "status": status,
        "blocking": report["blocking"],
        "reasons": reasons,
        "against_brief": against,
        "columns": list(EVALS_COLUMNS),
        "rows": [{c: row[c] for c in EVALS_COLUMNS} for row in report["versions"]],
        "figures": figures,
        "promotion": {k: p[k] for k in ("promote", "reason", "champion", "challenger", "delta", "new_failures", "within_noise")} if p else None,
        "calibration": {k: report["calibration"][k] for k in ("calibrated", "agreement", "false_accepts")} if report["calibration"] else None,
        "clusters": [{k: c[k] for k in ("id", "label", "size", "share")} for c in report["clusters"]],
        "cost": cost_note(report),
        "illustrative": report["illustrative"],
        "warnings": warnings,
    }


def cost_note(report: dict) -> dict[str, Any]:
    cited = any(r["label"].endswith(", cited") for r in report["ledger"])  # set only by report.cite_cost
    return {"owner": "cost-budget-check", "cited": cited, "note": "cited from the cost key" if cited else "cost not checked: run cost-budget-check"}


def read_cost(folder: Path, bet: str) -> dict | None:
    """The record's `cost` key, written by cost-budget-check, or None. Read only; never written here."""
    return read_record_cost(folder / f"{bet}.json")


def read_record_cost(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        cost = json.loads(path.read_text(encoding="utf-8")).get("cost")
    except (json.JSONDecodeError, AttributeError):
        raise EvalError(f"{path} is not valid JSON; fix it before any step writes to it.") from None
    return cost if isinstance(cost, dict) else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_record(folder: Path, bet: str, brief_path: Path, evals: dict[str, Any]) -> Path:
    """Write only the `evals` key of landing/<bet>.json; every other key stays exactly as it was."""
    if not BET.match(bet):
        raise EvalError(f"bet {bet!r}: use a slug of lower-case letters, digits and hyphens, such as quote-drafting-assistant.")
    path = folder / f"{bet}.json"
    digest = sha256(brief_path)
    if path.exists():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalError(f"{path} is not valid JSON ({exc.msg}); fix it before any step writes to it.") from None
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            raise EvalError(f"{path} is not a {SCHEMA} record.")
        if record.get("bet") != bet:
            raise EvalError(f"{path} is the record for {record.get('bet')!r}, not {bet!r}.")
        held = (record.get("brief") or {}).get("sha256")
        if held and held != digest:
            raise EvalError(
                f"the brief has changed since another step wrote {path.name} (sha256 {held[:12]}, now {digest[:12]}). "
                "Rerun the earlier steps on the new brief, or pass the brief they used."
            )
        record.setdefault("brief", {"path": str(brief_path), "sha256": digest})
    else:
        record = {"schema": SCHEMA, "bet": bet, "brief": {"path": str(brief_path), "sha256": digest}}
    record["evals"] = evals
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{bet}.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2) + "\n")
    os.replace(tmp, path)
    return path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check")
    s.add_argument("brief")
    args = p.parse_args(argv)
    brief = read_brief(Path(args.brief))
    name = figure_for(brief.metric)
    if name:
        better = "higher" if brief.higher_is_better else "lower"
        print(f"landing: the brief judges {LABELS[name].lower()} against {brief.bar_text}, {better} is better, by {brief.by}")
    else:
        print(f"landing: the brief's metric, {brief.metric}, is not an eval figure; evals report as the build check and did-it-land judges the metric")


if __name__ == "__main__":
    main()
