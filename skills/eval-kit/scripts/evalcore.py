"""Shared pieces for the eval-kit scripts: reading the traces CSV, the stable hash and the ledger.

Standard library only. Pure and deterministic: no clock, no randomness, no network.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The Leader Report's evals columns, in its order (product-engineering-update, scripts/collect.py).
EVALS_COLUMNS = ("version", "run_at", "cases", "passed", "cost_per_task", "tasks", "tasks_unassisted")
# A judge score at or above this bar is a pass, when a row carries `score` instead of `passed`.
PASS_AT = 0.6

KINDS = ("eval", "production")
# What exports call the two kinds. Anything else is refused, never guessed.
KIND_ALIASES = {"test": "eval", "offline": "eval", "evaluation": "eval", "prod": "production", "live": "production", "online": "production"}
SPLITS = ("development", "holdout")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRUE = {"true", "yes", "y", "1", "pass", "passed"}
FALSE = {"false", "no", "n", "0", "fail", "failed"}


class EvalError(SystemExit):
    """A refusal with a message that says what to fix. Exits non-zero from any CLI."""

    def __init__(self, message: str) -> None:
        super().__init__(f"eval-kit: {message}")


def fnv1a(text: str) -> str:
    """FNV-1a, 32-bit, hex. Stable across runs and platforms (Python's hash() is salted per process)."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def parse_bool(value: str, column: str, line: int) -> bool:
    v = value.strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    raise EvalError(f"line {line}: `{column}` is {value!r}; use true or false.")


def parse_float(value: str, column: str, line: int) -> float:
    try:
        return float(value.strip())
    except ValueError:
        raise EvalError(f"line {line}: `{column}` is {value!r}; use a number.") from None


@dataclass
class Trace:
    """One row of the traces CSV: an eval case result or a production task."""

    line: int
    kind: str
    id: str
    version: str
    run_at: str
    split: str = ""
    passed: bool | None = None
    score: float | None = None
    succeeded: bool | None = None
    human_stepped_in: bool | None = None
    cost_usd: float | None = None
    input: str = ""
    output: str = ""
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_pass(self) -> bool:
        """Eval rows only. `passed` wins over `score` when both are present."""
        if self.passed is not None:
            return self.passed
        return self.score is not None and self.score >= PASS_AT

    @property
    def text(self) -> str:
        return f"{self.input} {self.output} {self.note}".strip()


REQUIRED = ("kind", "id", "version", "run_at")


COLUMNS = (*REQUIRED, "split", "passed", "score", "succeeded", "human_stepped_in", "cost_usd", "input", "output", "note")


def wilson(part: int, whole: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a rate, in percent. Honest at small n and near 0 or 100, unlike the normal one."""
    if not whole:
        return (0.0, 0.0)
    p = part / whole
    centre = (p + z * z / (2 * whole)) / (1 + z * z / whole)
    half = z * math.sqrt(p * (1 - p) / whole + z * z / (4 * whole * whole)) / (1 + z * z / whole)
    return (round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1))


def parse_map(pairs: list[str] | None) -> dict[str, str]:
    """`--map id=trace_id --map kind=type`: schema column on the left, the export's column on the right."""
    mapping: dict[str, str] = {}
    for pair in pairs or []:
        ours, _, theirs = pair.partition("=")
        ours, theirs = ours.strip(), theirs.strip()
        if ours not in COLUMNS or not theirs:
            raise EvalError(f"--map {pair!r}: use SCHEMA_COLUMN=YOUR_COLUMN, where SCHEMA_COLUMN is one of {', '.join(COLUMNS)}.")
        mapping[ours] = theirs
    return mapping


def load_traces(path: Path, mapping: dict[str, str] | None = None) -> list[Trace]:
    """Read and check the traces CSV. Refuses the whole file on the first bad row, with its line number.
    `mapping` renames the export's columns to the schema's, so the export is read as it is, never edited."""
    if not path.exists():
        raise EvalError(f"{path} does not exist.")
    rename = {theirs: ours for ours, theirs in (mapping or {}).items()}
    fields, records = _read(path)
    headers = [rename.get(h, h) for h in fields]
    unmapped = sorted(set(rename) - set(fields))
    if unmapped:
        raise EvalError(f"--map names column(s) {', '.join(unmapped)}, which {path.name} does not have.")
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        raise EvalError(f"{path.name} is missing column(s) {', '.join(missing)}. Map yours with --map, or see references/trace-schema.md.")
    rows: list[Trace] = []
    seen: set[tuple[str, str, str]] = set()
    for n, raw in records:
        rows.append(_row({rename.get(k, k): v for k, v in raw.items()}, n, seen))
    if not rows:
        raise EvalError(f"{path.name} has no rows.")
    return rows


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Nested JSON keys become dotted columns, so `--map version=metadata.version` reaches inside a trace."""
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
        else:
            out[key] = _cell(v)
    return out


def _read(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Rows as (line number, cells). CSV, or JSONL (one JSON object per line, as most trace tools export)."""
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        records: list[tuple[int, dict[str, str]]] = []
        fields: dict[str, None] = {}
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalError(f"line {n}: not valid JSON ({exc.msg}).") from None
            if not isinstance(obj, dict):
                raise EvalError(f"line {n}: each line must be one JSON object.")
            flat = _flatten(obj)
            fields.update(dict.fromkeys(flat))
            records.append((n, flat))
        return list(fields), records
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields_csv = [h.strip() for h in (reader.fieldnames or [])]
        return fields_csv, [(n, {k.strip(): (v or "").strip() for k, v in raw.items() if k}) for n, raw in enumerate(reader, start=2)]


def _row(r: dict[str, str], n: int, seen: set[tuple[str, str, str]]) -> Trace:
    for c in REQUIRED:
        if not r.get(c):
            raise EvalError(f"line {n}: `{c}` is empty.")
    kind = KIND_ALIASES.get(r["kind"].lower(), r["kind"].lower())
    if kind not in KINDS:
        raise EvalError(f"line {n}: `kind` is {r['kind']!r}; use eval or production (test, offline, prod, live and online also read).")
    if not DATE.match(r["run_at"]):
        raise EvalError(f"line {n}: `run_at` is {r['run_at']!r}; use YYYY-MM-DD.")
    key = (kind, r["version"], r["id"])
    if key in seen:
        raise EvalError(f"line {n}: {kind} id {r['id']!r} appears twice in version {r['version']!r}.")
    seen.add(key)
    text = {c: r.get(c, "") for c in ("input", "output", "note")}
    t = Trace(line=n, kind=kind, id=r["id"], version=r["version"], run_at=r["run_at"], **text)
    if kind == "eval":
        t.split = r.get("split", "").lower()
        if t.split not in SPLITS:
            raise EvalError(f"line {n}: eval row {r['id']!r} has split {r.get('split', '')!r}; every eval case needs development or holdout.")
        if r.get("passed"):
            t.passed = parse_bool(r["passed"], "passed", n)
        if r.get("score"):
            t.score = parse_float(r["score"], "score", n)
            if not 0.0 <= t.score <= 1.0:
                raise EvalError(f"line {n}: `score` is {t.score:g}; judge scores run from 0 to 1.")
        if t.passed is None and t.score is None:
            raise EvalError(f"line {n}: eval row {r['id']!r} needs `passed` or `score`.")
    else:
        for c in ("succeeded", "human_stepped_in"):
            if not r.get(c):
                raise EvalError(f"line {n}: production row {r['id']!r} needs `{c}`.")
        t.succeeded = parse_bool(r["succeeded"], "succeeded", n)
        t.human_stepped_in = parse_bool(r["human_stepped_in"], "human_stepped_in", n)
        if r.get("cost_usd"):
            t.cost_usd = parse_float(r["cost_usd"], "cost_usd", n)
            if t.cost_usd < 0:
                raise EvalError(f"line {n}: `cost_usd` is negative.")
    return t


def versions(traces: list[Trace]) -> list[str]:
    """Versions in run order: by their latest run_at, then by name, so a tie never reorders."""
    last: dict[str, str] = {}
    for t in traces:
        last[t.version] = max(last.get(t.version, ""), t.run_at)
    return sorted(last, key=lambda v: (last[v], v))


class Ledger:
    """Every figure the report prints, with where it came from. A figure with no ledger row is not printed."""

    def __init__(self, source: Path, illustrative: bool) -> None:
        self.source = source.name
        self.sha = sha256_file(source)[:12]
        self.illustrative = illustrative
        self.rows: list[dict[str, Any]] = []

    def add(self, label: str, value: float | int | str, unit: str, basis: str, source: str | None = None) -> str:
        lid = f"L{len(self.rows) + 1}"
        self.rows.append(
            {
                "id": lid,
                "label": label,
                "value": value,
                "unit": unit,
                "source": source or f"{self.source} (sha256 {self.sha})",
                "basis": basis,
                "provenance": "Illustrative" if self.illustrative else "Measured",
            }
        )
        return lid
