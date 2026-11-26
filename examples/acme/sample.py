#!/usr/bin/env python3
"""Regenerate the committed Acme sample: eval-kit.html, eval-kit.md and the evals key of landing/quote-drafting.json.

Inputs, all illustrative (Acme is an invented company): the canonical briefs in briefs/ (copied from the landing-loop
repo, unchanged), the quote-drafting traces and their holdout seal in traces/, and the calibrated judge scores from
evals/fixtures/. The same inputs give the same bytes, so a chain script can call this and a test can check it.

Usage, from the repo root:
  python3 examples/acme/sample.py [--into DIR]

--into writes the outputs somewhere else (the test uses it); paths inside the outputs stay the same.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
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
                "--landing", str(into / "landing"),
                "--out", str(work / "run"),
            ]
        )  # fmt: skip
        into.mkdir(parents=True, exist_ok=True)
        shutil.copy(work / "run" / "report.html", into / "eval-kit.html")
        shutil.copy(work / "run" / "report.md", into / "eval-kit.md")
    print(f"sample: wrote eval-kit.html, eval-kit.md and landing/{BET}.json to {into}")


if __name__ == "__main__":
    main()
