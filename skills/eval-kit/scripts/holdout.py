#!/usr/bin/env python3
"""The holdout discipline: a development half you may read and tune against, and a sealed holdout half you may not.

An eval gate answers "did this change break something". It cannot answer "did this change generalise", because
the cases it checks are the cases the prompt was tuned against. That needs ground the tuning never touched. A change
that gains on development and loses on the holdout learned the practice cases, not the job.

The seal is tamper-evident against an accidental or convenient edit, not against an attacker: changing a held-out
case has to be a deliberate act (`holdout.py seal`), never a quiet one.

Ported from Throughline lib/eval/holdout.ts.

Usage:
  python3 scripts/holdout.py split CASES.csv --share 0.3 --out CASES_SPLIT.csv   # assign splits (eval rows only)
  python3 scripts/holdout.py seal TRACES.csv --out holdout.seal.json            # seal the holdout set
  python3 scripts/holdout.py verify TRACES.csv --seal holdout.seal.json         # check nothing moved
  python3 scripts/holdout.py promote TRACES.csv --champion V1 --challenger V2   # may V2 replace V1?
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # checked first, before anything is read or written
    sys.exit("eval-kit needs Python 3.11 or later; try python3.12")

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalcore import EvalError, Trace, fnv1a, load_traces, parse_map, pct, versions, wilson  # noqa: E402

# The holdout must be at least this share of each version's eval cases, or it is too thin to say anything.
MIN_HOLDOUT_SHARE = 0.2
# Below this many held-out cases a pass rate moves 3 or more points per case; the report says so.
SMALL_HOLDOUT = 30
DEFAULT_SHARE = 0.3


def assign_splits(case_ids: list[str], share: float = DEFAULT_SHARE) -> dict[str, str]:
    """Deterministic split: rank ids by their FNV-1a hash and hold out the first round(share * n).
    The same ids always get the same split, and adding a case never moves an existing one across
    unless the holdout size itself changes."""
    if not 0.0 < share < 1.0:
        raise EvalError(f"--share is {share:g}; use a value between 0 and 1, such as 0.3.")
    ids = sorted(set(case_ids))
    k = max(1, round(share * len(ids)))
    held = set(sorted(ids, key=lambda i: (fnv1a(i), i))[:k])
    return {i: ("holdout" if i in held else "development") for i in ids}


def check_splits(traces: list[Trace]) -> tuple[list[str], list[str]]:
    """Errors and warnings about the split. Errors block the report."""
    errors: list[str] = []
    warnings: list[str] = []
    evals = [t for t in traces if t.kind == "eval"]
    first: dict[str, Trace] = {}
    for t in evals:
        seen = first.setdefault(t.id, t)
        if seen.split != t.split:
            errors.append(f"case {t.id!r} is {seen.split} in {seen.version} and {t.split} in {t.version}. A case never changes split.")
        elif t.split == "holdout" and seen.input != t.input:
            errors.append(f"held-out case {t.id!r} has a different input in {t.version} than in {seen.version}. Reseal deliberately if the exam changed.")
    for v in versions(evals):
        rows = [t for t in evals if t.version == v]
        held = [t for t in rows if t.split == "holdout"]
        if not held:
            errors.append(f"version {v} has no holdout cases. Assign splits with `holdout.py split` first.")
        elif len(held) / len(rows) < MIN_HOLDOUT_SHARE:
            errors.append(f"version {v} holds out {len(held)} of {len(rows)} cases ({pct(len(held), len(rows))}%); the minimum is {MIN_HOLDOUT_SHARE:.0%}.")
        elif len(held) < SMALL_HOLDOUT:
            warnings.append(f"version {v} has {len(held)} held-out cases; each one moves the pass rate by {pct(1, len(held))} points.")
    return errors, warnings


def holdout_cases(traces: list[Trace]) -> dict[str, str]:
    """Held-out case id to its input, across every version. check_splits guarantees one input per id."""
    return {t.id: t.input for t in traces if t.kind == "eval" and t.split == "holdout"}


def case_fingerprint(case_id: str, case_input: str) -> str:
    return fnv1a(f"{case_id} {case_input}")


def seal(cases: dict[str, str]) -> str:
    """The set-level seal. Sorted by id so reordering is not a change; the count is folded in so dropping a case
    cannot pass as a no-op."""
    parts = [case_fingerprint(i, cases[i]) for i in sorted(cases)]
    return fnv1a(f"{len(parts)}:" + " ".join(parts))


def verify(traces: list[Trace], seal_file: Path) -> list[str]:
    """Errors when the holdout set no longer matches its seal, or a version did not run every sealed case."""
    try:
        sealed = json.loads(seal_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"cannot read the seal {seal_file}: {exc}") from None
    errors: list[str] = []
    cases = holdout_cases(traces)
    if seal(cases) != sealed.get("seal"):
        added = sorted(set(cases) - set(sealed.get("ids", [])))
        dropped = sorted(set(sealed.get("ids", [])) - set(cases))
        detail = []
        if added:
            detail.append(f"added {', '.join(added[:5])}")
        if dropped:
            detail.append(f"dropped {', '.join(dropped[:5])}")
        if not detail:
            detail.append("a held-out input was edited")
        errors.append(f"the holdout no longer matches its seal ({'; '.join(detail)}). Reseal with `holdout.py seal` only if the change was deliberate.")
    ids = set(sealed.get("ids", []))
    for v in versions([t for t in traces if t.kind == "eval"]):
        ran = {t.id for t in traces if t.kind == "eval" and t.version == v and t.split == "holdout"}
        if ids and ran != ids:
            errors.append(f"version {v} ran {len(ran & ids)} of {len(ids)} sealed holdout cases. A partial holdout is a chosen holdout.")
    return errors


@dataclass
class Verdict:
    promote: bool
    reason: str
    champion: str
    challenger: str
    champion_rate: float
    challenger_rate: float
    delta: float
    new_failures: list[str]
    regressions: list[str]
    gained: list[str] = field(default_factory=list)
    within_noise: bool = False


def judge_promotion(traces: list[Trace], champion: str, challenger: str) -> Verdict:
    """A challenger replaces the champion only by beating it on held-out cases, and only without failing a case
    the champion passed. Refusals, in order: different coverage is not a comparison; a new failure is a
    regression the average can hide; a tie or a loss goes to the champion."""

    def held(v: str) -> dict[str, Trace]:
        return {t.id: t for t in traces if t.kind == "eval" and t.version == v and t.split == "holdout"}

    a, b = held(champion), held(challenger)
    if not a or not b:
        missing = champion if not a else challenger
        raise EvalError(f"version {missing} has no holdout rows to compare.")
    rate_a = pct(sum(t.is_pass for t in a.values()), len(a))
    rate_b = pct(sum(t.is_pass for t in b.values()), len(b))
    base = {"champion": champion, "challenger": challenger, "champion_rate": rate_a, "challenger_rate": rate_b, "delta": round(rate_b - rate_a, 1)}
    # Direction, not size: when each rate sits inside the other's 95% interval the gain is real cases but not a
    # measured margin, and the report says so.
    lo_a, hi_a = wilson(sum(t.is_pass for t in a.values()), len(a))
    lo_b, hi_b = wilson(sum(t.is_pass for t in b.values()), len(b))
    base["within_noise"] = lo_a <= rate_b <= hi_a or lo_b <= rate_a <= hi_b
    base["gained"] = sorted(i for i in a if i in b and not a[i].is_pass and b[i].is_pass)
    if set(a) != set(b):
        return Verdict(False, "champion and challenger must run the same held-out cases", new_failures=[], regressions=[], **base)
    new_failures = sorted(i for i in a if a[i].is_pass and not b[i].is_pass)
    regressions = sorted(i for i in a if a[i].score is not None and b[i].score is not None and b[i].score < a[i].score and b[i].is_pass)
    if new_failures:
        reason = f"challenger fails {len(new_failures)} held-out case(s) the champion passed"
        return Verdict(False, reason, new_failures=new_failures, regressions=regressions, **base)
    if base["delta"] <= 0:
        return Verdict(False, "a tie or a loss goes to the champion", new_failures=[], regressions=regressions, **base)
    return Verdict(True, f"challenger gains {base['delta']:g} points on held-out cases with no new failure", new_failures=[], regressions=regressions, **base)


def _split_cmd(args: argparse.Namespace) -> None:
    with Path(args.cases).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "id" not in fields:
        raise EvalError(f"{args.cases} needs an `id` column.")

    # In a traces CSV only eval rows take a split; production tasks are not cases and must not use up the holdout.
    def is_case(r: dict[str, str]) -> bool:
        return "kind" not in fields or r.get("kind", "").strip().lower() == "eval"

    splits = assign_splits([r["id"] for r in rows if is_case(r)], args.share)
    if "split" not in fields:
        fields.append("split")
    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "split": splits[r["id"]] if is_case(r) else r.get("split", "")})
    held = sum(1 for s in splits.values() if s == "holdout")
    print(f"holdout: {held} of {len(splits)} cases held out; wrote {out}")


def _seal_cmd(args: argparse.Namespace) -> None:
    traces = load_traces(Path(args.traces), parse_map(args.map))
    errors, _ = check_splits(traces)
    if errors:
        raise EvalError("cannot seal: " + " ".join(errors))
    cases = holdout_cases(traces)
    payload = {"seal": seal(cases), "cases": len(cases), "ids": sorted(cases)}
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"holdout: sealed {len(cases)} cases as {payload['seal']}; wrote {args.out}")


def _verify_cmd(args: argparse.Namespace) -> None:
    traces = load_traces(Path(args.traces), parse_map(args.map))
    errors, warnings = check_splits(traces)
    errors += verify(traces, Path(args.seal))
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        raise EvalError(" ".join(errors))
    print("holdout: the seal holds and every version ran every sealed case")


def _promote_cmd(args: argparse.Namespace) -> None:
    v = judge_promotion(load_traces(Path(args.traces), parse_map(args.map)), args.champion, args.challenger)
    print(json.dumps(asdict(v), indent=2))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split", help="assign development and holdout splits to a cases CSV")
    s.add_argument("cases")
    s.add_argument("--share", type=float, default=DEFAULT_SHARE)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=_split_cmd)
    s = sub.add_parser("seal", help="seal the holdout set in a traces CSV")
    s.add_argument("traces")
    s.add_argument("--map", action="append", metavar="SCHEMA=YOURS")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=_seal_cmd)
    s = sub.add_parser("verify", help="check a traces CSV against its seal")
    s.add_argument("traces")
    s.add_argument("--map", action="append", metavar="SCHEMA=YOURS")
    s.add_argument("--seal", required=True)
    s.set_defaults(fn=_verify_cmd)
    s = sub.add_parser("promote", help="may the challenger replace the champion?")
    s.add_argument("traces")
    s.add_argument("--map", action="append", metavar="SCHEMA=YOURS")
    s.add_argument("--champion", required=True)
    s.add_argument("--challenger", required=True)
    s.set_defaults(fn=_promote_cmd)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
