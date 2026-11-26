#!/usr/bin/env python3
"""Write the Acme fixture: traces for Acme's quote-drafting assistant, two versions, eval cases and production tasks.

Acme is invented: invoicing software for trades businesses, Series C, about 400 people, 12 squads, with an AI
assistant that drafts quotes and chases invoices. Every figure the fixture produces is illustrative.

Seeded, so the output is the same on every run. The tests check the committed files match a fresh run.

Usage:
  python3 evals/make_fixture.py [--out evals/fixtures]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "eval-kit" / "scripts"))

import calibration  # noqa: E402
import holdout  # noqa: E402
from evalcore import load_traces  # noqa: E402

SEED = 20261126
JOBS = (
    "replace leaking water heater 50 gallon",
    "install outdoor tap and isolation valve",
    "rewire kitchen ring main and add two sockets",
    "service gas boiler and replace thermocouple",
    "fit new consumer unit with surge protection",
    "unblock main drain and camera survey",
    "replace bathroom extractor fan",
    "repair roof flashing around chimney",
)
# Failure modes, written as a reviewer note on the trace. The clusters must find these without being told.
MODES = (
    ("quote added part not listed in price book", "Added expansion tank; no such line in price book."),
    ("callout fee missing from quote total", "Total left out the callout fee."),
    ("tax applied twice to labour line", "Tax charged on labour twice, total too high."),
)
PROD_MODES = (
    ("invoice chase sent to wrong contact", "Chase went to site contact, not accounts payable."),
    ("estimator edited labour hours", "Estimator changed labour hours before sending."),
)
VERSIONS = (("v1.3", "2026-10-15", 0.70, 0.90, 0.32, 0.031), ("v1.4", "2026-11-15", 0.45, 0.94, 0.24, 0.024))


def rows() -> list[dict[str, str]]:
    rng = random.Random(SEED)
    ids = [f"q{n:03d}" for n in range(1, 101)]
    splits = holdout.assign_splits(ids, 0.3)
    inputs = {i: f"Draft quote: {JOBS[n % len(JOBS)]} for customer C{100 + n}" for n, i in enumerate(ids)}
    out: list[dict[str, str]] = []
    passed_before: dict[str, bool] = {}
    for version, run_at, pass_p, ok_p, help_p, cost in VERSIONS:
        for i in ids:
            # A case the earlier version passed stays passed, so v1.4 gains with no new failure.
            ok = passed_before.get(i, False) or rng.random() < pass_p
            passed_before[i] = ok
            mode = MODES[rng.randrange(len(MODES))]
            score = round(rng.uniform(0.7, 1.0) if ok else rng.uniform(0.2, 0.55), 2)
            out.append(
                {
                    "kind": "eval",
                    "id": i,
                    "version": version,
                    "run_at": run_at,
                    "split": splits[i],
                    "passed": "",
                    "score": f"{score:.2f}",
                    "succeeded": "",
                    "human_stepped_in": "",
                    "cost_usd": "",
                    "input": inputs[i],
                    "output": "Quote drafted with line items and total" if ok else f"Quote drafted: {mode[0]}",
                    "note": "" if ok else mode[1],
                }
            )
        for n in range(1, 201):
            ok = rng.random() < ok_p
            helped = rng.random() < help_p
            mode = PROD_MODES[1 if ok else 0]
            out.append(
                {
                    "kind": "production",
                    "id": f"t{n:04d}",
                    "version": version,
                    "run_at": run_at,
                    "split": "",
                    "passed": "",
                    "score": "",
                    "succeeded": "true" if ok else "false",
                    "human_stepped_in": "true" if helped or not ok else "false",
                    "cost_usd": f"{max(0.004, rng.gauss(cost, cost * 0.25)):.4f}",
                    "input": f"Task {n}: {JOBS[n % len(JOBS)]}",
                    "output": "Sent" if ok and not helped else mode[0],
                    "note": "" if ok and not helped else mode[1],
                }
            )
    return out


def judge_scores(lenient: bool) -> list[dict[str, str]]:
    """A calibrated judge agrees with every human rubric. The lenient one waves through the invented part."""
    out = []
    for c in calibration.CASES:
        r = dict(c.human)
        if lenient and c.id == "invented-part":
            r["grounding"] = 4
        out.append({"id": c.id, **{a: str(r[a]) for a in calibration.GATED_AXES}})
    return out


def write_csv(path: Path, data: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(data[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=str(ROOT / "evals" / "fixtures"))
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    traces = out / "acme_quote_traces.csv"
    write_csv(traces, rows())
    write_csv(out / "acme_judge_scores.csv", judge_scores(lenient=False))
    write_csv(out / "acme_judge_scores_lenient.csv", judge_scores(lenient=True))
    cases = holdout.holdout_cases(load_traces(traces))
    seal = {"seal": holdout.seal(cases), "cases": len(cases), "ids": sorted(cases)}
    (out / "acme_holdout.seal.json").write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    print(f"fixture: wrote {traces.name}, judge scores and the seal to {out}")


if __name__ == "__main__":
    main()
