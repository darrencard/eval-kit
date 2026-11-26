#!/usr/bin/env python3
"""One command from a traces CSV to a report: seal the holdout if it has no seal yet, set up judge calibration if a
judge scored the cases, then run the report.

The first run seals the holdout and says so. Commit the seal file beside your eval set: from then on any change to a
held-out case blocks the report until someone reseals on purpose.

Usage:
  python3 scripts/run.py TRACES.csv --feature "Quote drafting" --target 85 [--out run] [--map SCHEMA=YOURS ...]
      [--seal PATH] [--judge-scores FILE.csv] [--calibration-cases FILE.json] [--fail-on watch|stalled] [--illustrative]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import calibration  # noqa: E402
import holdout  # noqa: E402
import report  # noqa: E402
from evalcore import EvalError, load_traces, parse_map  # noqa: E402


def default_seal(traces: Path) -> Path:
    return traces.with_name(f"{traces.stem}.seal.json")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("traces")
    p.add_argument("--feature", required=True)
    p.add_argument("--target", type=float, help="target held-out pass rate, in percent")
    p.add_argument("--out", default="run")
    p.add_argument("--seal", help="defaults to TRACES.seal.json beside the traces")
    p.add_argument("--map", action="append", metavar="SCHEMA=YOURS")
    p.add_argument("--judge-scores")
    p.add_argument("--calibration-cases")
    p.add_argument("--fail-on", choices=("watch", "stalled"))
    p.add_argument("--illustrative", action="store_true")
    args = p.parse_args(argv)

    src = Path(args.traces)
    traces = load_traces(src, parse_map(args.map))
    if not any(t.kind == "eval" for t in traces):
        raise EvalError(f"{src.name} has no eval rows. The pass rate needs eval cases; autonomy is never reported without it.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seal_path = Path(args.seal) if args.seal else default_seal(src)
    if not seal_path.exists():
        errors, _ = holdout.check_splits(traces)
        if errors:
            raise EvalError("cannot seal: " + " ".join(errors))
        cases = holdout.holdout_cases(traces)
        seal_path.write_text(json.dumps({"seal": holdout.seal(cases), "cases": len(cases), "ids": sorted(cases)}, indent=2) + "\n", encoding="utf-8")
        print(f"run: first run, so sealed {len(cases)} held-out cases to {seal_path}. Commit it beside the eval set.")

    judge_scored = any(t.kind == "eval" and t.passed is None for t in traces)
    if judge_scored and not args.judge_scores:
        blind = out / "calibration_cases.csv"
        cases = calibration.load_cases(Path(args.calibration_cases) if args.calibration_cases else None)
        calibration.write_blind(cases, blind)
        print(
            f"run: a judge scored these cases and has not been calibrated. Have it score {blind} blind "
            "(relevance, specificity, grounding, actionability, 1 to 5), then rerun with --judge-scores."
        )

    ns = argparse.Namespace(
        traces=str(src),
        feature=args.feature,
        seal=str(seal_path),
        judge_scores=args.judge_scores,
        calibration_cases=args.calibration_cases,
        target=args.target,
        illustrative=args.illustrative,
        map=args.map,
    )
    result = report.write(report.build(ns), out)
    print(f"run: read {out / 'report.md'} first. Feed {out / 'evals.csv'} to the Leader Report as its evals source.")
    report.gate(result, args.fail_on)


if __name__ == "__main__":
    main()
