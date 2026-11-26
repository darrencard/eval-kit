#!/usr/bin/env python3
"""Failure modes without a predefined taxonomy.

Takes the failed traces, pulls the salient terms from what went wrong (the output and the reviewer note, not the
input, which would cluster by topic instead of by failure), drops terms that most passing traces also carry (they
name the feature, not a failure), groups traces that share a signature and labels each group by the terms its
members hold in common. Nobody writes the categories in advance; they come out of the failures.

Deterministic: sorted input, no clock, no randomness, so the same traces always give the same clusters.
The signature is lexical. Embeddings could replace it behind the same function; the clusters emerge either way.

Held-out failures are never read here. Their text stays sealed; only their count reaches the report.

Ported from Throughline lib/eval/failure-clusters.ts.

Usage:
  python3 scripts/clusters.py TRACES.csv [--version V]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalcore import Trace, load_traces, versions  # noqa: E402

# A trace joins a cluster only if it shares at least this many salient terms, so one shared domain word never
# merges two distinct modes.
MIN_SHARED = 2
# A term in more than this share of the passing traces is background, not a failure signal.
BACKGROUND_SHARE = 0.5

STOP = frozenset(
    " ".join(
        (
            "the a an and or but of to in on for with is are was were be been being it its this that these those as at by from into than then "
            "so not no do does did done have has had will would can could should about over under out up down off only just also very more "
            "most other each every some what which who whose when where why how our your their",
        )
    ).split()
)
TOKEN = re.compile(r"[^a-z0-9]+")


def keywords(text: str) -> list[str]:
    """Lowercased tokens of 4 or more characters, no stopwords, deduped in first-seen order."""
    seen: dict[str, None] = {}
    for raw in TOKEN.split(text.lower()):
        if len(raw) >= 4 and raw not in STOP:
            seen.setdefault(raw, None)
    return list(seen)


def failures(traces: list[Trace], version: str) -> list[Trace]:
    """The traces of one version that may be read: development eval failures, and production tasks that failed or
    needed a person. Held-out cases are excluded by design."""
    out = []
    for t in traces:
        if t.version != version:
            continue
        if (t.kind == "eval" and t.split == "development" and not t.is_pass) or (t.kind == "production" and (not t.succeeded or t.human_stepped_in)):
            out.append(t)
    return sorted(out, key=lambda t: (t.kind, t.id))


def passes(traces: list[Trace], version: str) -> list[Trace]:
    """The readable traces of one version that went right: the background the failures are read against."""
    return [
        t
        for t in traces
        if t.version == version
        and ((t.kind == "eval" and t.split == "development" and t.is_pass) or (t.kind == "production" and t.succeeded and not t.human_stepped_in))
    ]


def background(passed: list[Trace]) -> set[str]:
    df: dict[str, int] = {}
    for t in passed:
        for x in keywords(signal_text(t)):
            df[x] = df.get(x, 0) + 1
    return {x for x, n in df.items() if n / len(passed) > BACKGROUND_SHARE} if passed else set()


def signal_text(t: Trace) -> str:
    return f"{t.output} {t.note}".strip() or t.input


def cluster(failed: list[Trace], passed: list[Trace] | None = None) -> list[dict]:
    # Background is per kind: an eval failure is read against eval passes, a production one against production.
    common = {k: background([t for t in passed or [] if t.kind == k]) for k in ("eval", "production")}
    groups: list[dict] = []
    for t in failed:
        kw = [x for x in keywords(signal_text(t)) if x not in common[t.kind]]
        best, best_n = None, 0
        for g in groups:
            n = sum(1 for x in kw if x in g["sig"])
            if n >= MIN_SHARED and n > best_n:
                best, best_n = g, n
        if best is not None:
            best["members"].append(f"{t.kind}:{t.id}")
            best["kw"].append(kw)
            best["sig"].update(kw)
        else:
            groups.append({"members": [f"{t.kind}:{t.id}"], "kw": [kw], "sig": set(kw)})

    total = len(failed) or 1
    out = []
    for g in groups:
        freq: dict[str, int] = {}
        for kw in g["kw"]:
            for x in kw:
                freq[x] = freq.get(x, 0) + 1
        # The signature is the terms shared by at least half the members.
        half = math.ceil(len(g["members"]) / 2)
        shared = [x for x, _ in sorted(((x, n) for x, n in freq.items() if n >= half), key=lambda p: (-p[1], p[0]))]
        terms = (shared or sorted(freq))[:4]
        out.append(
            {
                "label": ", ".join(terms[:3]) or "(no salient terms)",
                "terms": terms,
                "size": len(g["members"]),
                "share": round(100 * len(g["members"]) / total),
                "members": sorted(g["members"]),
            }
        )
    out.sort(key=lambda c: (-c["size"], c["label"]))
    return [{"id": f"fc{i + 1}", **c} for i, c in enumerate(out)]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("traces")
    p.add_argument("--version", help="defaults to the latest version")
    args = p.parse_args(argv)
    traces = load_traces(Path(args.traces))
    version = args.version or versions(traces)[-1]
    print(json.dumps(cluster(failures(traces, version), passes(traces, version)), indent=2))


if __name__ == "__main__":
    main()
