#!/usr/bin/env python3
"""Live data first: turn what your eval and tracing tools already export into the traces CSV, with no retyping.

Usage:
  python3 scripts/from_traces.py traces --out traces.csv [sources...]
    --openai-eval-items FILE   OpenAI Evals output items (GET /v1/evals/{eval_id}/runs/{run_id}/output_items),
                               one file per run; --version names the run (repeat both, in the same order)
    --langfuse-traces FILE     Langfuse traces (GET /api/public/traces), with --langfuse-scores FILE
                               (GET /api/public/scores); production tasks
    --posthog-query FILE       a PostHog HogQL result ({"columns", "results"}) over $ai_trace or $ai_generation
                               events; production tasks. The query is in references/live-data.md

Cost: rows keep a trace's cost in `cost_usd` for cost-budget-check to read. eval-kit itself computes no cost
figure; cost per task belongs to cost-budget-check (Landing Loop contract, one owner per figure).

Saved responses are read as they stand. A response with no field this needs is refused with what is missing;
nothing is guessed. Eval items keep a `split` from the dataset item when it has one; otherwise run
`holdout.py split` on the result. This script reads files and writes files. It makes no network calls.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "vendor"))

import from_posthog  # noqa: E402  (vendored, unchanged; see vendor/PINS.json)
from evalcore import COLUMNS, EvalError  # noqa: E402

Json = dict[str, Any]


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalError(f"cannot read {path} ({exc}). Save the tool's response as it stands, as UTF-8 JSON.") from None


def _records(data: Any, path: Path) -> list[Json]:
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise EvalError(f"{path.name} has no data list. Save the API response as it stands.")
    return [x for x in items if isinstance(x, dict)]


def _day(value: Any) -> str:
    """A date from a Unix timestamp or an ISO timestamp."""
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, tz=datetime.UTC).date().isoformat()
    text = str(value or "")
    try:
        return datetime.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise EvalError(f"timestamp {value!r} is not a date.") from None


def _text(value: Any) -> str:
    """Message lists, dicts and strings, flattened to one line of text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return " ".join(_text(v.get("content") if isinstance(v, dict) and "content" in v else v) for v in value).strip()
    if isinstance(value, dict):
        for key in ("content", "text", "output", "input"):
            if key in value:
                return _text(value[key])
        return " ".join(json.dumps(value, sort_keys=True).split())
    return str(value)


def openai_eval_items(path: Path, version: str) -> list[Json]:
    """One eval row per output item. The case id is the datasource item's own id when it has one, else its index,
    so the same case keeps the same id across runs."""
    rows = []
    for item in _records(_load(path), path):
        ds = item.get("datasource_item") or {}
        case = ds.get("id") if isinstance(ds, dict) and ds.get("id") is not None else item.get("datasource_item_id")
        if case is None:
            raise EvalError(f"{path.name}: output item {item.get('id')} has no datasource_item_id, so it cannot be tracked across runs.")
        results = item.get("results") or []
        if results:
            passed = all(bool(r.get("passed")) for r in results if isinstance(r, dict))
        elif item.get("status") in ("pass", "fail"):
            passed = item["status"] == "pass"
        else:
            raise EvalError(f"{path.name}: output item {item.get('id')} has no results and no pass or fail status.")
        sample = item.get("sample") or {}
        failed = [r.get("name", "") for r in results if isinstance(r, dict) and not r.get("passed")]
        rows.append(
            {
                "kind": "eval",
                "id": str(case),
                "version": version,
                "run_at": _day(item.get("created_at")),
                "split": str(ds.get("split", "")) if isinstance(ds, dict) else "",
                "passed": "true" if passed else "false",
                "input": _text(sample.get("input")),
                "output": _text(sample.get("output")),
                "note": ("failed graders: " + ", ".join(failed)) if failed else "",
            }
        )
    return rows


def _score_flag(score: Json) -> bool:
    value = score.get("value")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value >= 1
    return str(score.get("stringValue", value)).strip().lower() in ("true", "yes", "1")


def langfuse(traces_path: Path, scores_path: Path, success: str, human: str, version: str | None) -> list[Json]:
    """Production rows from Langfuse traces, with succeeded and human_stepped_in read from two named scores."""
    by_trace: dict[str, dict[str, Json]] = {}
    for s in _records(_load(scores_path), scores_path):
        by_trace.setdefault(str(s.get("traceId")), {})[str(s.get("name"))] = s
    rows = []
    for t in _records(_load(traces_path), traces_path):
        scores = by_trace.get(str(t.get("id")), {})
        missing = [n for n in (success, human) if n not in scores]
        if missing:
            raise EvalError(
                f"Langfuse trace {t.get('id')} has no score named {', '.join(missing)}. Score every trace, or pass --success-score and --human-score."
            )
        v = version or t.get("version") or t.get("release")
        if not v:
            raise EvalError(f"Langfuse trace {t.get('id')} has no version or release. Pass --version.")
        cost = t.get("totalCost")
        notes = [str(scores[n].get("comment")) for n in (success, human) if scores[n].get("comment")]
        rows.append(
            {
                "kind": "production",
                "id": str(t.get("id")),
                "version": str(v),
                "run_at": _day(t.get("timestamp")),
                "succeeded": "true" if _score_flag(scores[success]) else "false",
                "human_stepped_in": "true" if _score_flag(scores[human]) else "false",
                "cost_usd": "" if cost is None else f"{float(cost):.6f}",
                "input": _text(t.get("input")),
                "output": _text(t.get("output")),
                "note": " ".join(notes),
            }
        )
    return rows


POSTHOG_NEEDED = ("id", "version", "run_at", "succeeded", "human_stepped_in")


def posthog(path: Path) -> list[Json]:
    """Production rows from a HogQL result. Columns are named as the trace schema; see references/live-data.md."""
    data = from_posthog.load(path)
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list) or not isinstance(data.get("results"), list):
        raise EvalError(f"{path.name} needs PostHog's columns and results lists.")
    cols = [str(c).lower() for c in data["columns"]]
    missing = [c for c in POSTHOG_NEEDED if c not in cols]
    if missing:
        raise EvalError(f"{path.name}: the query returns no {', '.join(missing)} column. Alias the columns as in references/live-data.md.")
    out = []
    for row in data["results"]:
        if not isinstance(row, list):
            continue
        r = dict(zip(cols, row, strict=False))
        out.append(
            {
                "kind": "production",
                "id": str(r["id"]),
                "version": str(r["version"]),
                "run_at": _day(r["run_at"]),
                "succeeded": "true" if r["succeeded"] in (True, 1, "true", "1") else "false",
                "human_stepped_in": "true" if r["human_stepped_in"] in (True, 1, "true", "1") else "false",
                "cost_usd": "" if r.get("cost_usd") is None else f"{float(r['cost_usd']):.6f}",
                "input": _text(r.get("input")),
                "output": _text(r.get("output")),
                "note": _text(r.get("note")),
            }
        )
    return out


def write_csv(rows: list[Json], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(COLUMNS), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("traces")
    t.add_argument("--out", required=True)
    t.add_argument("--openai-eval-items", action="append", default=[])
    t.add_argument("--version", action="append", default=[])
    t.add_argument("--langfuse-traces")
    t.add_argument("--langfuse-scores")
    t.add_argument("--success-score", default="succeeded")
    t.add_argument("--human-score", default="human_stepped_in")
    t.add_argument("--posthog-query", action="append", default=[])
    args = p.parse_args(argv)

    rows: list[Json] = []
    if args.openai_eval_items:
        if len(args.version) != len(args.openai_eval_items):
            raise EvalError("give one --version per --openai-eval-items file, in the same order.")
        for path, version in zip(args.openai_eval_items, args.version, strict=True):
            rows += openai_eval_items(Path(path), version)
    if args.langfuse_traces or args.langfuse_scores:
        if not (args.langfuse_traces and args.langfuse_scores):
            raise EvalError("Langfuse needs both --langfuse-traces and --langfuse-scores.")
        lf_version = args.version[0] if args.version and not args.openai_eval_items else None
        rows += langfuse(Path(args.langfuse_traces), Path(args.langfuse_scores), args.success_score, args.human_score, lf_version)
    for path in args.posthog_query:
        rows += posthog(Path(path))
    if not rows:
        raise EvalError("no source given. Pass --openai-eval-items, --langfuse-traces with --langfuse-scores, or --posthog-query.")
    write_csv(rows, Path(args.out))
    kinds = {k: sum(r["kind"] == k for r in rows) for k in ("eval", "production")}
    print(f"from_traces: wrote {kinds['eval']} eval and {kinds['production']} production rows to {args.out}")


if __name__ == "__main__":
    main()
