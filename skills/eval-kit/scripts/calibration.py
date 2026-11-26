#!/usr/bin/env python3
"""Calibration cases for the judge: does the thing deciding pass or fail know a bad answer when it sees one?

Each case is a candidate output with a verdict a person assigned in advance, and most are meant to be rejected.
A judge that has only ever been shown work it approves has not been tested. Every gated axis gets a case that
fails on that axis alone, so a rejection has to be for the right reason and not by luck.

Two layers. The rule layer: `passes()` must classify every human-labelled rubric correctly (`selftest`). The
judge layer: the judge model scores the same answers blind, and `check` compares its verdicts with the human
ones. A judge that accepts a case meant to be rejected is a judge failure, and the report will not mark a
judge-scored pass rate landed until the judge clears every case.

Ported from Throughline lib/eval/judge-calibration.ts and rubric.ts. The default cases use Acme, an invented
invoicing company for trades businesses, and its quote-drafting assistant. All illustrative.

Usage:
  python3 scripts/calibration.py selftest [--cases FILE.json]
  python3 scripts/calibration.py export --out calibration_cases.csv [--cases FILE.json]   # blind: no verdicts
  python3 scripts/calibration.py check JUDGE_SCORES.csv [--cases FILE.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalcore import EvalError, pct  # noqa: E402

GATED_AXES = ("relevance", "specificity", "grounding", "actionability")
# Every axis must reach this score (1 to 5), and the average must reach MIN_AVG.
AXIS_MIN = 3
MIN_AVG = 4.0


def average(rubric: dict[str, int]) -> float:
    return round(sum(rubric[a] for a in GATED_AXES) / len(GATED_AXES), 2)


def failed_axes(rubric: dict[str, int]) -> list[str]:
    return [a for a in GATED_AXES if rubric[a] < AXIS_MIN]


def passes(rubric: dict[str, int]) -> bool:
    """The scoring rule, apart from the judge that produces the scores."""
    return not failed_axes(rubric) and average(rubric) >= MIN_AVG


@dataclass(frozen=True)
class Case:
    id: str
    context: str  # what the assistant was given (the read it must stay inside)
    answer: str  # the candidate output
    human: dict[str, int]  # the rubric a person assigned
    expect: str  # pass or fail
    fails_on: str | None
    why: str


_CTX_QUOTE = (
    "Customer: Riverside Rentals. Job: replace a leaking water heater, 50 gallon. Price book: water heater "
    "(50 gal) $1,180; labour $95 per hour, 3 hours estimated; call-out fee $65. Tax 5%. Quote valid 30 days."
)
_CTX_CHASE = "Invoice INV-2041 for $1,640.00 to Northgate Property, issued 2026-10-01, due 2026-10-31, unpaid. Contact: accounts payable."

CASES: tuple[Case, ...] = (
    Case(
        "grounded-quote",
        _CTX_QUOTE,
        "Quote for Riverside Rentals: 50 gallon water heater $1,180, labour 3 hours at $95 ($285), call-out fee $65. "
        "Subtotal $1,530, tax 5% $76.50, total $1,606.50. Valid 30 days. Reply to accept and we will book the install.",
        {"relevance": 5, "specificity": 5, "grounding": 5, "actionability": 5},
        "pass",
        None,
        "every line comes from the price book and the next step is clear",
    ),
    Case(
        "grounded-chase",
        _CTX_CHASE,
        "Hi, invoice INV-2041 for $1,640.00 was due on 31 October and is still open. Could you confirm a payment date "
        "this week? The pay link is on the invoice.",
        {"relevance": 5, "specificity": 4, "grounding": 5, "actionability": 4},
        "pass",
        None,
        "quotes the invoice exactly and asks for one thing",
    ),
    Case(
        "invented-part",
        _CTX_QUOTE,
        "Quote for Riverside Rentals: 50 gallon water heater $1,180, expansion tank $140, labour 3 hours at $95 ($285), "
        "call-out fee $65. Total with tax $1,753.50. Reply to accept.",
        {"relevance": 5, "specificity": 5, "grounding": 1, "actionability": 5},
        "fail",
        "grounding",
        "adds an expansion tank the price book does not list",
    ),
    Case(
        "misquoted-price",
        _CTX_QUOTE,
        "Quote for Riverside Rentals: 50 gallon water heater $1,080, labour 3 hours at $95 ($285), call-out fee $65. "
        "Total with tax $1,501.50. Valid 30 days. Reply to accept.",
        {"relevance": 5, "specificity": 5, "grounding": 1, "actionability": 5},
        "fail",
        "grounding",
        "misquotes a price that is in the book, the same trust break as inventing one",
    ),
    Case(
        "vague-quote",
        _CTX_QUOTE,
        "Thanks for reaching out. Replacing a water heater usually runs a bit over a thousand dollars once labour and "
        "fees are in. Reply to accept and we will book the install.",
        {"relevance": 5, "specificity": 1, "grounding": 4, "actionability": 4},
        "fail",
        "specificity",
        "invents nothing and commits to nothing: no line items, no total",
    ),
    Case(
        "wrong-job",
        _CTX_QUOTE,
        "Quote for Riverside Rentals: annual boiler service, 2 hours at $95 ($190), call-out fee $65. Total with tax $267.75. Reply to accept.",
        {"relevance": 1, "specificity": 5, "grounding": 4, "actionability": 5},
        "fail",
        "relevance",
        "precise and priced from the book, for a job nobody asked about",
    ),
    Case(
        "no-next-step",
        _CTX_QUOTE,
        "Water heater (50 gal) $1,180, labour 3 hours at $95 ($285), call-out fee $65, tax 5% $76.50. Total $1,606.50.",
        {"relevance": 5, "specificity": 5, "grounding": 5, "actionability": 1},
        "fail",
        "actionability",
        "a correct total with no validity window and no way to accept",
    ),
    Case(
        "chase-wrong-amount",
        _CTX_CHASE,
        "Hi, invoice INV-2041 for $1,460.00 is overdue. Could you confirm a payment date this week?",
        {"relevance": 5, "specificity": 4, "grounding": 1, "actionability": 4},
        "fail",
        "grounding",
        "chases the right invoice for the wrong amount",
    ),
)


def load_cases(path: Path | None) -> tuple[Case, ...]:
    if path is None:
        return CASES
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            Case(c["id"], c.get("context", ""), c["answer"], {a: int(c["human"][a]) for a in GATED_AXES}, c["expect"], c.get("fails_on"), c.get("why", ""))
            for c in raw
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise EvalError(f"cannot read calibration cases from {path}: {exc}") from None


def check_set(cases: tuple[Case, ...]) -> list[str]:
    """The case set itself must be fit to test a judge. Returns errors."""
    errors: list[str] = []
    rejected = [c for c in cases if c.expect == "fail"]
    if len(rejected) * 2 <= len(cases):
        errors.append(f"{len(rejected)} of {len(cases)} cases are meant to be rejected; most must be.")
    for axis in GATED_AXES:
        if not any(c.fails_on == axis for c in rejected):
            errors.append(f"no rejected case tests {axis} alone.")
    for c in cases:
        if c.expect not in ("pass", "fail"):
            errors.append(f"case {c.id}: expect is {c.expect!r}; use pass or fail.")
            continue
        if passes(c.human) != (c.expect == "pass"):
            errors.append(f"case {c.id}: the rule says {'pass' if passes(c.human) else 'fail'} on the human rubric, the case expects {c.expect}.")
        if c.expect == "fail" and failed_axes(c.human) != [c.fails_on]:
            errors.append(f"case {c.id}: written to fail on {c.fails_on}, but the human rubric fails on {failed_axes(c.human) or 'nothing'}.")
    return errors


def check_judge(cases: tuple[Case, ...], scores_csv: Path) -> dict:
    """Compare the judge's blind scores with the human verdicts."""
    by_id = {c.id: c for c in cases}
    with scores_csv.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    judged: dict[str, dict[str, int]] = {}
    for n, r in enumerate(rows, start=2):
        cid = (r.get("id") or "").strip()
        if cid not in by_id:
            raise EvalError(f"{scores_csv.name} line {n}: unknown calibration case {cid!r}.")
        try:
            judged[cid] = {a: int(r[a]) for a in GATED_AXES}
        except (KeyError, TypeError, ValueError):
            raise EvalError(f"{scores_csv.name} line {n}: needs whole-number scores for {', '.join(GATED_AXES)}.") from None
    missing = sorted(set(by_id) - set(judged))
    false_accepts, false_rejects, wrong_reason = [], [], []
    for cid, rubric in sorted(judged.items()):
        c = by_id[cid]
        verdict = "pass" if passes(rubric) else "fail"
        if c.expect == "fail" and verdict == "pass":
            false_accepts.append(cid)
        elif c.expect == "pass" and verdict == "fail":
            false_rejects.append(cid)
        elif c.expect == "fail" and c.fails_on not in failed_axes(rubric):
            wrong_reason.append(cid)
    agreed = len(judged) - len(false_accepts) - len(false_rejects)
    calibrated = not missing and not false_accepts and not false_rejects
    return {
        "cases": len(cases),
        "judged": len(judged),
        "missing": missing,
        "agreement": pct(agreed, len(judged)) if judged else 0.0,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "wrong_reason": wrong_reason,
        "calibrated": calibrated,
    }


def _selftest(args: argparse.Namespace) -> None:
    cases = load_cases(Path(args.cases) if args.cases else None)
    errors = check_set(cases)
    if errors:
        raise EvalError(" ".join(errors))
    rejected = sum(c.expect == "fail" for c in cases)
    print(f"calibration: the rule classifies all {len(cases)} cases correctly; {rejected} are meant to be rejected")


def _export(args: argparse.Namespace) -> None:
    cases = load_cases(Path(args.cases) if args.cases else None)
    with Path(args.out).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "context", "answer", *GATED_AXES])
        for c in cases:
            w.writerow([c.id, c.context, c.answer, "", "", "", ""])
    print(f"calibration: wrote {len(cases)} blind cases to {args.out}; the judge fills the 4 score columns (1 to 5)")


def _check(args: argparse.Namespace) -> None:
    result = check_judge(load_cases(Path(args.cases) if args.cases else None), Path(args.scores))
    print(json.dumps(result, indent=2))
    if not result["calibrated"]:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--cases")
    s.set_defaults(fn=_selftest)
    s = sub.add_parser("export")
    s.add_argument("--out", required=True)
    s.add_argument("--cases")
    s.set_defaults(fn=_export)
    s = sub.add_parser("check")
    s.add_argument("scores")
    s.add_argument("--cases")
    s.set_defaults(fn=_check)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
