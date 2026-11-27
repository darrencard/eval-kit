#!/usr/bin/env python3
"""Regenerate the committed Acme sample: eval-kit.html, eval-kit.md and the evals key of landing/quote-drafting.json.

Inputs, all illustrative (Acme is an invented company): the canonical briefs in briefs/ (copied from the landing-loop
repo, unchanged), the quote-drafting traces and their holdout seal in traces/, and the calibrated judge scores from
evals/fixtures/, and upstream/cost-budget-check.json, the record cost-budget-check 0.3.1 wrote for the same bet
(copied unchanged), so the run cites its cost key the way a real loop would. The same inputs give the same bytes,
so a chain script can call this and a test can check it.

Usage, from the repo root:
  python3 examples/acme/sample.py [--into DIR]

--into writes the outputs somewhere else (the test uses it); paths inside the outputs stay the same.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # checked first, before anything is read or written
    sys.exit("eval-kit needs Python 3.11 or later; try python3.12")

import argparse
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path("examples/acme")
sys.path.insert(0, str(ROOT / "skills" / "eval-kit" / "scripts"))

import run  # noqa: E402

BET = "quote-drafting"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--into", help="output folder (default examples/acme)")
    args = p.parse_args(argv)
    os.chdir(ROOT)  # paths written into the record are relative to the repo root
    into = Path(args.into).resolve() if args.into else ROOT / HERE
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # Start from the record as cost-budget-check left it: eval-kit reads cost and writes only evals. The run
        # works on a copy, so a failed run never leaves the committed record without its evals key.
        (work / "landing").mkdir()
        shutil.copy(HERE / "upstream" / "cost-budget-check.json", work / "landing" / f"{BET}.json")
        # The seal is read beside the traces; copy both so a run never touches the committed seal.
        shutil.copy(HERE / "traces" / f"{BET}.csv", work / f"{BET}.csv")
        shutil.copy(HERE / "traces" / f"{BET}.seal.json", work / f"{BET}.seal.json")
        run.main(
            [
                str(work / f"{BET}.csv"),
                "--feature", "Quote drafting",
                "--target", "80",
                "--illustrative",
                "--judge-scores", "evals/fixtures/acme_judge_scores.csv",
                "--brief", str(HERE / "briefs" / f"{BET}.md"),
                "--bet", BET,
                "--landing", str(work / "landing"),
                "--out", str(work / "run"),
            ]
        )  # fmt: skip
        # Only after the run succeeded: each output is written beside its target, then renamed over it.
        for src, dst in (
            (work / "run" / "report.html", into / "eval-kit.html"),
            (work / "run" / "report.md", into / "eval-kit.md"),
            (work / "landing" / f"{BET}.json", into / "landing" / f"{BET}.json"),
        ):
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp_dst = dst.with_name(f".{dst.name}.tmp")
            shutil.copyfile(src, tmp_dst)
            os.replace(tmp_dst, dst)
    print(f"sample: wrote eval-kit.html, eval-kit.md and landing/{BET}.json to {into}")


if __name__ == "__main__":
    main()
