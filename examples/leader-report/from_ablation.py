#!/usr/bin/env python3
"""A real run: eval-kit on the Leader Report's own ablation evals, read from its git history at a pinned commit.

The Leader Report's ablation harness asks a blind judge to compare two decks made from the same data: Claude with
the skill (condition C) against Claude alone (condition A), each pair judged twice, once in each order. Here each
C-against-A judgment is one eval case, and it passes when the judge picks the skill's deck overall. A tie is not a
pass. The judge is a model, so the cases are judge-scored. Each condition C generation is one production task:
it succeeded when the deck was written and the skill was loaded, and no person stepped in (the runs are headless).

Versions: v0.8.0 (evals/ablation/measured/2026-11-25) and v0.8.3 (measured/2026-11-25-v083), the two runs with the
same C-against-A design. The v0.7.4 run compared the pipeline alone (condition B), so it is a different feature
and is left out. Cost is not written: in the Landing Loop it belongs to cost-budget-check.

Where the harness skipped a judgment in one version (it did for sparse run 2 in v0.8.3), that case is dropped from
both versions, so the holdout compares the same cases.

Nothing in the Leader Report's folder is changed: every file is read with `git show COMMIT:PATH`.

Usage:
  python3 examples/leader-report/from_ablation.py --repo ~/product-engineering-update --out runs/leader-report
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess  # noqa: S404  (git, read only, with fixed arguments)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "eval-kit" / "scripts"))

import holdout  # noqa: E402
from evalcore import COLUMNS  # noqa: E402

COMMIT = "366da9bfede540ec19e9164ad5ad17ce28c1d06b"
RUNS = (("v0.8.0", "2026-11-25", "evals/ablation/measured/2026-11-25"), ("v0.8.3", "2026-11-25", "evals/ablation/measured/2026-11-25-v083"))
NAME = re.compile(r"pair-CA-(?P<fixture>[a-z_]+)-(?P<run>\d+)-(?P<order>12|21)\.json$")

BRIEF = """# Leader Report skill against Claude alone

## Landing brief

- **Problem:** A leader using Claude alone gets an update with wrong or unsourced figures; the skill should give a better one from the same data.
- **Metric:** Held-out pass rate
- **Bar:** 50%
- **Better:** higher
- **By:** 2026-12-31
- **Non-goals:** No change to the judge, the rubric or the fixtures to win.
- **Tokens per task:** 400,000
- **Price per token:** $0.0000015
- **The line:** model call. Figures stay in fixed code; Claude writes the words.
- **Decides the next step:** Product owner, Dacard
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout  # noqa: S603, S607


def show(repo: Path, path: str) -> str:
    return git(repo, "show", f"{COMMIT}:{path}")


def rows(repo: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    skipped: set[str] = set()
    for version, run_at, folder in RUNS:
        files = [f for f in git(repo, "ls-tree", "-r", "--name-only", COMMIT, f"{folder}/judgments").split() if NAME.search(f)]
        for f in sorted(files):
            m = NAME.search(f)
            j = json.loads(show(repo, f))
            if "verdict" not in j:
                skipped.add(f"{m['fixture']}-r{m['run']}")
                continue
            skill = "X" if "/C/" in j["x"] else "Y"
            winner = j["verdict"]["overall"]["winner"]
            won = winner == skill
            lost_on = [k for k, v in j["verdict"]["criteria"].items() if v.get("winner") not in (skill, "tie")]
            case = f"{m['fixture']}-r{m['run']}-{'skill-first' if skill == 'X' else 'skill-second'}"
            out.append(
                {
                    "kind": "eval",
                    "id": case,
                    "version": version,
                    "run_at": run_at,
                    "score": "1.00" if won else "0.00",
                    "input": f"fixture {m['fixture']}, run {m['run']}, skill deck shown {'first' if skill == 'X' else 'second'}",
                    # The judge's own reason is the signal; the lost criteria repeat on almost every loss, so they go last.
                    "output": "",
                    "note": "" if won else j["verdict"]["overall"]["reason"] + (" (tie)" if winner == "tie" else ""),
                    "lost_on": ", ".join(lost_on),
                }
            )
        summary = json.loads(show(repo, f"{folder}/summary.json"))
        decks = set(git(repo, "ls-tree", "--name-only", COMMIT, f"{folder}/decks-C/").split())
        for run_path, use in sorted(summary["skill_use_in_C"]["per_run"].items()):
            _, _, fixture, n = run_path.split("/")
            # v0.8.0 kept each deck as a folder, v0.8.3 as an .html file.
            wrote = bool({f"{folder}/decks-C/{fixture}-{n}", f"{folder}/decks-C/{fixture}-{n}.html"} & decks)
            out.append(
                {
                    "kind": "production",
                    "id": f"C-{fixture}-{n}",
                    "version": version,
                    "run_at": run_at,
                    "succeeded": "true" if wrote and use.get("skill_loaded") else "false",
                    "human_stepped_in": "false",
                    "output": f"deck {'written' if wrote else 'missing'}; {use.get('script_calls', 0)} script calls",
                }
            )
    # A judgment the harness skipped in one version is dropped from every version, so both run the same cases.
    if skipped:
        out = [r for r in out if not (r["kind"] == "eval" and any(r["id"].startswith(f"{s}-") for s in skipped))]
        print(f"from_ablation: the harness skipped {', '.join(sorted(skipped))} in at least one version; those cases are left out of both")
    splits = holdout.assign_splits([r["id"] for r in out if r["kind"] == "eval"], 0.3)
    for r in out:
        if r["kind"] == "eval":
            r["split"] = splits[r["id"]]
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True, help="the product-engineering-update checkout (read only)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = rows(Path(args.repo).expanduser())
    with (out / "traces.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(COLUMNS), lineterminator="\n")
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLUMNS} for r in data)
    (out / "brief.md").write_text(BRIEF, encoding="utf-8")
    n_eval = sum(r["kind"] == "eval" for r in data)
    print(f"from_ablation: {n_eval} judgments and {len(data) - n_eval} C runs from {COMMIT[:12]}; wrote traces.csv and brief.md to {out}")


if __name__ == "__main__":
    main()
