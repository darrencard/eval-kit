#!/usr/bin/env python3
"""Hold eval-kit to its promises.

Usage:
  python3 -m unittest discover -s evals -v

Groups:
  Fixture       the committed Acme fixture is what make_fixture.py writes.
  Loader        the traces CSV is refused whole on a bad row, with its line number.
  Holdout       splits, the seal and the promotion rule (ported from Throughline holdout.ts).
  Calibration   the case set and the judge check (ported from judge-calibration.ts).
  Clusters      failure modes found with no taxonomy, and the holdout never read (failure-clusters.ts).
  Report        every figure, the status rule and the Leader Report's evals columns.
  OneCommand    run.py seals on first run, sets up calibration, maps columns and gates CI.
  Hygiene       no em dashes, no banned words, versions in step.

Standard library only. Runs on Python 3.11 or later.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "eval-kit" / "scripts"
FIX = ROOT / "evals" / "fixtures"
TRACES = FIX / "acme_quote_traces.csv"
SEAL = FIX / "acme_holdout.seal.json"
JUDGE = FIX / "acme_judge_scores.csv"
LENIENT = FIX / "acme_judge_scores_lenient.csv"
EM_DASH = chr(0x2014)
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "evals"))

import calibration  # noqa: E402
import clusters  # noqa: E402
import evalcore  # noqa: E402
import holdout  # noqa: E402
import make_fixture  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402
from evalcore import EvalError, fnv1a, load_traces, parse_map, wilson  # noqa: E402


def read_rows(path: Path = TRACES) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_rows(rows: list[dict[str, str]], path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path


def args(traces: Path = TRACES, **kw) -> argparse.Namespace:
    base = {"traces": str(traces), "feature": "Quote drafting", "seal": str(SEAL), "judge_scores": str(JUDGE), "calibration_cases": None, "target": 80.0}
    base["illustrative"] = True
    base.update(kw)
    return argparse.Namespace(**base)


def first_champion_pass(rows: list[dict[str, str]]) -> str:
    return next(r["id"] for r in rows if r["version"] == "v1.3" and r["split"] == "holdout" and float(r["score"]) >= 0.6)


def fail_on_v14(rows: list[dict[str, str]], case_id: str) -> None:
    for r in rows:
        if r["version"] == "v1.4" and r["id"] == case_id:
            r["score"] = "0.10"


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class Fixture(Temp):
    def test_committed_fixture_matches_a_fresh_run(self) -> None:
        with redirect_stdout(io.StringIO()):
            make_fixture.main(["--out", str(self.tmp)])
        for name in ("acme_quote_traces.csv", "acme_holdout.seal.json", "acme_judge_scores.csv", "acme_judge_scores_lenient.csv"):
            self.assertEqual((self.tmp / name).read_bytes(), (FIX / name).read_bytes(), name)

    def test_fixture_shape(self) -> None:
        traces = load_traces(TRACES)
        self.assertEqual(len(traces), 600)
        self.assertEqual({t.version for t in traces}, {"v1.3", "v1.4"})
        self.assertEqual(sum(t.kind == "eval" and t.split == "holdout" and t.version == "v1.4" for t in traces), 30)


class Loader(Temp):
    def broken(self, **change: str) -> Path:
        rows = read_rows()
        rows[0].update(change)
        return write_rows(rows, self.tmp / "t.csv")

    def test_refusals_name_the_line(self) -> None:
        cases = {
            "kind": ("shadow", "use eval or production"),
            "run_at": ("15/10/2026", "YYYY-MM-DD"),
            "split": ("", "development or holdout"),
            "score": ("1.4", "from 0 to 1"),
        }
        for column, (value, message) in cases.items():
            with self.subTest(column=column), self.assertRaises(EvalError) as ctx:
                load_traces(self.broken(**{column: value}))
            self.assertIn("line 2", str(ctx.exception))
            self.assertIn(message, str(ctx.exception))

    def test_duplicate_id_refused(self) -> None:
        rows = read_rows()
        rows.append(dict(rows[0]))
        with self.assertRaises(EvalError) as ctx:
            load_traces(write_rows(rows, self.tmp / "t.csv"))
        self.assertIn("appears twice", str(ctx.exception))

    def test_missing_column_refused(self) -> None:
        (self.tmp / "t.csv").write_text("kind,id,version\neval,a,v1\n", encoding="utf-8")
        with self.assertRaises(EvalError) as ctx:
            load_traces(self.tmp / "t.csv")
        self.assertIn("run_at", str(ctx.exception))

    def test_production_rows_need_both_flags(self) -> None:
        rows = read_rows()
        next(r for r in rows if r["kind"] == "production")["human_stepped_in"] = ""
        with self.assertRaises(EvalError) as ctx:
            load_traces(write_rows(rows, self.tmp / "t.csv"))
        self.assertIn("human_stepped_in", str(ctx.exception))

    def test_column_map_reads_an_export_as_it_is(self) -> None:
        rows = [{("trace_id" if k == "id" else "type" if k == "kind" else k): v for k, v in r.items()} for r in read_rows()]
        path = write_rows(rows, self.tmp / "export.csv")
        mapped = load_traces(path, parse_map(["id=trace_id", "kind=type"]))
        self.assertEqual([(t.kind, t.id) for t in mapped], [(t.kind, t.id) for t in load_traces(TRACES)])

    def test_jsonl_with_nested_keys_and_export_kind_names(self) -> None:
        path = self.tmp / "export.jsonl"
        lines = []
        for r in read_rows():
            meta = {"version": r.pop("version"), "run_at": r.pop("run_at")}
            kind = {"eval": "test", "production": "prod"}[r.pop("kind")]
            flags = {k: (r[k] == "true") for k in ("succeeded", "human_stepped_in") if r[k]}
            cells = {k: v for k, v in r.items() if v and k not in flags}
            lines.append(json.dumps({**cells, **flags, "type": kind, "metadata": meta}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        got = load_traces(path, parse_map(["kind=type", "version=metadata.version", "run_at=metadata.run_at"]))
        want = load_traces(TRACES)
        self.assertEqual([(t.kind, t.id, t.version, t.is_pass, t.succeeded) for t in got], [(t.kind, t.id, t.version, t.is_pass, t.succeeded) for t in want])

    def test_bad_jsonl_names_the_line(self) -> None:
        path = self.tmp / "bad.jsonl"
        path.write_text('{"kind": "eval"}\n', encoding="utf-8")
        with self.assertRaises(EvalError) as ctx:
            load_traces(path)
        self.assertIn("missing column", str(ctx.exception))
        path.write_text('{"kind": "eval", "id": "a", "version": "v1", "run_at": "2026-01-01"}\nnot json\n', encoding="utf-8")
        with self.assertRaises(EvalError) as ctx:
            load_traces(path)
        self.assertIn("line 2", str(ctx.exception))

    def test_a_bad_map_is_refused(self) -> None:
        with self.assertRaises(EvalError):
            parse_map(["trace=trace_id"])
        with self.assertRaises(EvalError) as ctx:
            load_traces(TRACES, parse_map(["id=not_there"]))
        self.assertIn("does not have", str(ctx.exception))

    def test_passed_wins_over_score(self) -> None:
        t = load_traces(self.broken(passed="false", score="0.99"))[0]
        self.assertFalse(t.is_pass)


class Holdout(Temp):
    def test_fnv1a_matches_the_typescript_reference(self) -> None:
        # Published FNV-1a 32-bit vectors, which holdout.ts also produces for ASCII input.
        self.assertEqual(fnv1a(""), "811c9dc5")
        self.assertEqual(fnv1a("a"), "e40c292c")
        self.assertEqual(fnv1a("foobar"), "bf9cf968")

    def test_assign_splits_is_deterministic_and_sized(self) -> None:
        ids = [f"c{n}" for n in range(50)]
        a = holdout.assign_splits(ids, 0.3)
        b = holdout.assign_splits(list(reversed(ids)), 0.3)
        self.assertEqual(a, b)
        self.assertEqual(sum(v == "holdout" for v in a.values()), 15)

    def test_assign_splits_rejects_a_bad_share(self) -> None:
        for share in (0.0, 1.0, 1.5):
            with self.subTest(share=share), self.assertRaises(EvalError):
                holdout.assign_splits(["a", "b"], share)

    def test_split_command_on_traces_splits_eval_rows_only(self) -> None:
        rows = [dict(r, split="") for r in read_rows()]
        src = write_rows(rows, self.tmp / "t.csv")
        with redirect_stdout(io.StringIO()):
            holdout.main(["split", str(src), "--out", str(self.tmp / "out.csv")])
        out = read_rows(self.tmp / "out.csv")
        self.assertTrue(all(r["split"] == "" for r in out if r["kind"] == "production"))
        self.assertEqual(len({r["id"] for r in out if r["split"] == "holdout"}), 30)

    def test_wilson_interval(self) -> None:
        self.assertEqual(wilson(24, 30), (62.7, 90.5))
        self.assertEqual(wilson(0, 10)[0], 0.0)
        self.assertEqual(wilson(10, 10)[1], 100.0)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))

    def test_a_small_gain_is_flagged_as_direction_not_size(self) -> None:
        v = holdout.judge_promotion(load_traces(TRACES), "v1.3", "v1.4")
        self.assertTrue(v.within_noise)
        self.assertEqual(len(v.gained), 3)

    def test_split_command_adds_a_split_column(self) -> None:
        src = self.tmp / "cases.csv"
        src.write_text("id,input\n" + "".join(f"c{n},job {n}\n" for n in range(10)), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            holdout.main(["split", str(src), "--out", str(self.tmp / "out.csv")])
        rows = read_rows(self.tmp / "out.csv")
        self.assertEqual(sum(r["split"] == "holdout" for r in rows), 3)

    def test_fixture_split_is_clean(self) -> None:
        errors, warnings = holdout.check_splits(load_traces(TRACES))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_a_case_never_changes_split(self) -> None:
        rows = read_rows()
        r = next(r for r in rows if r["version"] == "v1.4" and r["split"] == "holdout")
        r["split"] = "development"
        errors, _ = holdout.check_splits(load_traces(write_rows(rows, self.tmp / "t.csv")))
        self.assertTrue(any("never changes split" in e for e in errors))

    def test_a_thin_holdout_is_refused(self) -> None:
        rows = [r for r in read_rows() if not (r["split"] == "holdout" and int(r["id"][1:]) % 3)]
        errors, _ = holdout.check_splits(load_traces(write_rows(rows, self.tmp / "t.csv")))
        self.assertTrue(any("the minimum is 20%" in e for e in errors))

    def test_no_holdout_is_refused(self) -> None:
        rows = [r for r in read_rows() if r["split"] != "holdout"]
        errors, _ = holdout.check_splits(load_traces(write_rows(rows, self.tmp / "t.csv")))
        self.assertTrue(any("no holdout cases" in e for e in errors))

    def test_seal_ignores_order_and_moves_on_any_edit(self) -> None:
        cases = holdout.holdout_cases(load_traces(TRACES))
        s = holdout.seal(cases)
        self.assertEqual(s, holdout.seal(dict(reversed(list(cases.items())))))
        first = sorted(cases)[0]
        self.assertNotEqual(s, holdout.seal({**cases, first: cases[first] + " (revised)"}))
        self.assertNotEqual(s, holdout.seal({k: v for k, v in cases.items() if k != first}))

    def test_verify_holds_on_the_fixture(self) -> None:
        self.assertEqual(holdout.verify(load_traces(TRACES), SEAL), [])

    def test_verify_catches_an_edited_held_out_input(self) -> None:
        held = sorted(json.loads(SEAL.read_text())["ids"])[0]
        rows = read_rows()
        for r in rows:
            if r["id"] == held:
                r["input"] += " (easier)"
        errors = holdout.verify(load_traces(write_rows(rows, self.tmp / "t.csv")), SEAL)
        self.assertTrue(any("no longer matches its seal" in e for e in errors))

    def test_verify_catches_a_partial_holdout_run(self) -> None:
        held = sorted(json.loads(SEAL.read_text())["ids"])
        rows = [r for r in read_rows() if not (r["version"] == "v1.4" and r["id"] == held[0])]
        errors = holdout.verify(load_traces(write_rows(rows, self.tmp / "t.csv")), SEAL)
        self.assertTrue(any("ran 29 of 30 sealed holdout cases" in e for e in errors))

    def test_promotion_on_the_fixture(self) -> None:
        v = holdout.judge_promotion(load_traces(TRACES), "v1.3", "v1.4")
        self.assertTrue(v.promote)
        self.assertEqual((v.champion_rate, v.challenger_rate, v.delta), (70.0, 80.0, 10.0))
        self.assertEqual(v.new_failures, [])

    def test_a_new_failure_blocks_promotion_whatever_the_average(self) -> None:
        rows = read_rows()
        case = first_champion_pass(rows)
        fail_on_v14(rows, case)
        v = holdout.judge_promotion(load_traces(write_rows(rows, self.tmp / "t.csv")), "v1.3", "v1.4")
        self.assertFalse(v.promote)
        self.assertEqual(v.new_failures, [case])
        self.assertGreater(v.delta, 0)

    def test_a_tie_goes_to_the_champion(self) -> None:
        v = holdout.judge_promotion(load_traces(TRACES), "v1.4", "v1.4")
        self.assertFalse(v.promote)
        self.assertIn("tie", v.reason)

    def test_different_coverage_is_not_a_comparison(self) -> None:
        held = sorted(json.loads(SEAL.read_text())["ids"])
        rows = [r for r in read_rows() if not (r["version"] == "v1.4" and r["id"] == held[-1])]
        v = holdout.judge_promotion(load_traces(write_rows(rows, self.tmp / "t.csv")), "v1.3", "v1.4")
        self.assertFalse(v.promote)
        self.assertIn("same held-out cases", v.reason)


class Calibration(Temp):
    def test_the_rule_classifies_every_case(self) -> None:
        self.assertEqual(calibration.check_set(calibration.CASES), [])

    def test_most_cases_are_meant_to_be_rejected_and_every_axis_is_tested(self) -> None:
        rejected = [c for c in calibration.CASES if c.expect == "fail"]
        self.assertGreater(len(rejected), len(calibration.CASES) / 2)
        self.assertEqual({c.fails_on for c in rejected}, set(calibration.GATED_AXES))

    def test_a_set_of_easy_cases_is_refused(self) -> None:
        easy = tuple(c for c in calibration.CASES if c.expect == "pass" or c.id == "invented-part")
        errors = calibration.check_set(easy)
        self.assertTrue(any("most must be" in e for e in errors))
        self.assertTrue(any("tests relevance alone" in e for e in errors))

    def test_a_case_that_fails_for_two_reasons_is_refused(self) -> None:
        c = calibration.CASES[2]
        muddled = calibration.Case(c.id, c.context, c.answer, {**c.human, "specificity": 1}, "fail", "grounding", c.why)
        errors = calibration.check_set((muddled, *calibration.CASES[3:]))
        self.assertTrue(any("written to fail on grounding" in e for e in errors))

    def test_a_calibrated_judge(self) -> None:
        r = calibration.check_judge(calibration.CASES, JUDGE)
        self.assertTrue(r["calibrated"])
        self.assertEqual(r["agreement"], 100.0)

    def test_a_lenient_judge_is_caught(self) -> None:
        r = calibration.check_judge(calibration.CASES, LENIENT)
        self.assertFalse(r["calibrated"])
        self.assertEqual(r["false_accepts"], ["invented-part"])
        self.assertEqual(r["agreement"], 87.5)

    def test_a_judge_that_skips_cases_is_not_calibrated(self) -> None:
        rows = read_rows(JUDGE)[:-1]
        r = calibration.check_judge(calibration.CASES, write_rows(rows, self.tmp / "j.csv"))
        self.assertFalse(r["calibrated"])
        self.assertEqual(len(r["missing"]), 1)

    def test_export_is_blind(self) -> None:
        out = self.tmp / "cases.csv"
        with redirect_stdout(io.StringIO()):
            calibration.main(["export", "--out", str(out)])
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("expect", text)
        for c in calibration.CASES:
            self.assertNotIn(c.why, text)

    def test_template_is_a_fit_shape_once_written(self) -> None:
        cases = calibration.load_cases(self._write_json(calibration.template()))
        errors = calibration.check_set(cases)
        self.assertTrue(errors and all("template text" in e for e in errors))
        filled = [{**c, "context": "Job: fix tap.", "answer": f"Answer {c['id']}"} for c in calibration.template()]
        self.assertEqual(calibration.check_set(calibration.load_cases(self._write_json(filled))), [])

    def _write_json(self, data: list) -> Path:
        path = self.tmp / "cases.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_custom_cases_from_json(self) -> None:
        path = self.tmp / "cases.json"
        data = [{"id": c.id, "answer": c.answer, "human": c.human, "expect": c.expect, "fails_on": c.fails_on} for c in calibration.CASES]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(calibration.check_set(calibration.load_cases(path)), [])


class Clusters(Temp):
    def test_recovers_every_planted_mode_without_a_taxonomy(self) -> None:
        traces = load_traces(TRACES)
        failed = clusters.failures(traces, "v1.3")
        got = clusters.cluster(failed, clusters.passes(traces, "v1.3"))
        self.assertEqual(
            [(c["label"], c["size"]) for c in got],
            [
                ("before, changed, edited", 59),
                ("accounts, chase, contact", 23),
                ("callout, left, missing", 7),
                ("added, book, expansion", 6),
                ("applied, charged, high", 5),
            ],
        )
        self.assertEqual(sum(c["size"] for c in got), len(failed))

    def test_order_of_rows_does_not_change_the_clusters(self) -> None:
        rows = read_rows()
        random.Random(7).shuffle(rows)
        a, b = load_traces(TRACES), load_traces(write_rows(rows, self.tmp / "t.csv"))
        self.assertEqual(
            clusters.cluster(clusters.failures(a, "v1.3"), clusters.passes(a, "v1.3")),
            clusters.cluster(clusters.failures(b, "v1.3"), clusters.passes(b, "v1.3")),
        )

    def test_held_out_failures_are_never_read(self) -> None:
        rows = read_rows()
        held = next(r for r in rows if r["version"] == "v1.4" and r["split"] == "holdout" and float(r["score"]) < 0.6)
        held["note"] = "zzsecretmarker zzsecretmarker2"
        traces = load_traces(write_rows(rows, self.tmp / "t.csv"))
        failed = clusters.failures(traces, "v1.4")
        self.assertNotIn(held["id"], {t.id for t in failed if t.kind == "eval"})
        self.assertNotIn("zzsecretmarker", json.dumps(clusters.cluster(failed, clusters.passes(traces, "v1.4"))))

    def test_one_shared_word_does_not_merge_two_modes(self) -> None:
        base = read_rows()[0]
        a = dict(base, id="x1", split="development", score="0.1", output="refund invoice twice", note="")
        b = dict(base, id="x2", split="development", score="0.1", output="invoice layout broken", note="")
        traces = load_traces(write_rows([a, b], self.tmp / "t.csv"))
        self.assertEqual(len(clusters.cluster(clusters.failures(traces, traces[0].version))), 2)

    def test_every_cluster_carries_traces_to_read(self) -> None:
        traces = load_traces(TRACES)
        for c in clusters.cluster(clusters.failures(traces, "v1.3"), clusters.passes(traces, "v1.3")):
            self.assertTrue(1 <= len(c["examples"]) <= 2)
            self.assertTrue(all(e["trace"] in c["members"] for e in c["examples"]))

    def test_keywords_drop_stopwords_and_short_tokens(self) -> None:
        self.assertEqual(clusters.keywords("The tax was applied to the Labour line, twice. Tax!"), ["applied", "labour", "line", "twice"])


class Report(Temp):
    def run_report(self, **kw) -> dict:
        return report.build(args(**kw))

    def test_figures_on_the_fixture(self) -> None:
        r = self.run_report()
        latest = r["versions"][-1]
        self.assertEqual(r["status"], "not confirmed: too close to call")
        self.assertFalse(r["blocking"])
        self.assertEqual((latest["cases"], latest["passed"], latest["pass_rate"]), (30, 24, 80.0))
        self.assertEqual((latest["dev_cases"], latest["dev_passed"]), (70, 63))
        self.assertEqual((latest["tasks"], latest["tasks_unassisted"], latest["autonomy_rate"]), (200, 143, 71.5))
        self.assertIsNone(latest["cost_per_task"])

    def test_evals_csv_matches_the_leader_report_source(self) -> None:
        # product-engineering-update collect.py: version str, run_at date, cases num, passed num,
        # cost_per_task num?, tasks num?, tasks_unassisted num?, and tasks_unassisted never above tasks.
        r = self.run_report()
        path = self.tmp / "evals.csv"
        report.write_evals_csv(r, path)
        rows = read_rows(path)
        self.assertEqual(list(rows[0]), ["version", "run_at", "cases", "passed", "cost_per_task", "tasks", "tasks_unassisted"])
        for row in rows:
            self.assertRegex(row["run_at"], r"^\d{4}-\d{2}-\d{2}$")
            for c in ("cases", "passed", "tasks", "tasks_unassisted"):
                float(row[c])
            self.assertEqual(row["cost_per_task"], "", "cost per task is cost-budget-check's; with no cost key the column stays empty")
            self.assertLessEqual(float(row["passed"]), float(row["cases"]))
            self.assertLessEqual(float(row["tasks_unassisted"]), float(row["tasks"]))
        self.assertEqual([x["version"] for x in rows], ["v1.3", "v1.4"])

    def test_cli_writes_three_files(self) -> None:
        out = self.tmp / "run"
        cli = ["--out", str(out), "--feature", "Quote drafting", "--seal", str(SEAL), "--judge-scores", str(JUDGE), "--target", "80", "--illustrative"]
        with redirect_stdout(io.StringIO()):
            report.main([str(TRACES), *cli])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["evals.csv", "report.html", "report.json", "report.md"])

    def test_every_figure_has_a_ledger_row_and_is_illustrative(self) -> None:
        r = self.run_report()
        ids = {row["id"] for row in r["ledger"]}
        md = report.markdown(r)
        for ref in re.findall(r"\[(L\d+)\]", md):
            self.assertIn(ref, ids)
        self.assertTrue(all(row["provenance"] == "Illustrative" for row in r["ledger"]))
        self.assertIn("Illustrative", md)
        self.assertEqual(len(r["ledger"]), 6)

    def test_measured_when_not_illustrative(self) -> None:
        r = self.run_report(illustrative=False)
        self.assertTrue(all(row["provenance"] == "Measured" for row in r["ledger"]))
        self.assertNotIn("Illustrative", report.markdown(r))

    def test_unsealed_never_meets_target(self) -> None:
        r = self.run_report(seal=None)
        self.assertIsNone(r["status"])
        self.assertTrue(any("not sealed" in x for x in r["reasons"]))

    def test_an_uncalibrated_judge_never_meets_target(self) -> None:
        for scores in (None, str(LENIENT)):
            with self.subTest(scores=scores):
                r = self.run_report(judge_scores=scores)
                self.assertIsNone(r["status"])
                self.assertTrue(any("calibration" in x for x in r["reasons"]))

    def test_human_labels_need_no_judge(self) -> None:
        rows = read_rows()
        for row in rows:
            if row["kind"] == "eval":
                row["passed"] = "true" if float(row["score"]) >= 0.6 else "false"
                row["score"] = ""
        r = self.run_report(traces=write_rows(rows, self.tmp / "t.csv"), judge_scores=None, target=60.0)
        self.assertEqual(r["status"], "meets target")

    def test_no_target_gives_no_status(self) -> None:
        self.assertIsNone(self.run_report(target=None)["status"])

    def test_just_under_target_inside_the_range_is_too_close_to_call(self) -> None:
        # 24 of 30 is 80%, range 62.7 to 90.5: under 85 as a point, but the high end reaches over it.
        r = self.run_report(target=85.0)
        self.assertEqual((r["status"], r["blocking"]), ("not confirmed: too close to call", False))

    def test_far_under_target_is_below_target_and_blocking(self) -> None:
        r = self.run_report(target=95.0)
        self.assertEqual((r["status"], r["blocking"]), ("below target", True))

    def test_a_new_held_out_failure_blocks(self) -> None:
        rows = read_rows()
        fail_on_v14(rows, first_champion_pass(rows))
        r = self.run_report(traces=write_rows(rows, self.tmp / "t.csv"))
        self.assertTrue(r["blocking"])
        self.assertNotEqual(r["status"], "meets target")

    def test_development_far_ahead_of_holdout_reads_as_overfitting(self) -> None:
        rows = read_rows()
        for row in rows:
            if row["kind"] == "eval" and row["version"] == "v1.4" and row["split"] == "development":
                row["score"] = "0.95"
        r = self.run_report(traces=write_rows(rows, self.tmp / "t.csv"), target=75.0)
        self.assertIsNone(r["status"])
        self.assertTrue(any("tuning to the practice cases" in x for x in r["reasons"]))

    def test_autonomy_without_its_quality_pair_is_blocked(self) -> None:
        rows = [r for r in read_rows() if not (r["version"] == "v1.4" and r["kind"] == "eval")]
        with self.assertRaises(EvalError) as ctx:
            self.run_report(traces=write_rows(rows, self.tmp / "t.csv"), seal=None)
        self.assertIn("quality pair", str(ctx.exception))

    def test_a_broken_seal_blocks_and_writes_nothing(self) -> None:
        held = sorted(json.loads(SEAL.read_text())["ids"])[0]
        rows = read_rows()
        for r in rows:
            if r["id"] == held:
                r["input"] += " (easier)"
        out = self.tmp / "run"
        with self.assertRaises(EvalError):
            report.main([str(write_rows(rows, self.tmp / "t.csv")), "--out", str(out), "--feature", "x", "--seal", str(SEAL)])
        self.assertFalse(out.exists())

    def test_no_cost_figure_of_its_own(self) -> None:
        r = self.run_report()
        self.assertTrue(all(v["cost_per_task"] is None for v in r["versions"]))
        self.assertFalse(any("cost" in row["label"].lower() for row in r["ledger"]))
        md = report.markdown(r)
        self.assertIn("Cost: cost not checked: run cost-budget-check.", md)
        self.assertNotRegex(md, r"\$0\.0\d")
        self.assertTrue(any("cost not checked: run cost-budget-check" in w for w in r["warnings"]))

    def test_record_flag_cites_the_cost_key(self) -> None:
        cost = {
            "tool": "cost-budget-check 0.2.0",
            "cost_per_successful_task": {
                "value": 0.0281,
                "unit": "USD per task",
                "source": "usage.csv",
                "window": {"from": "2026-11-01", "to": "2026-11-15"},
            },
        }
        record = self.tmp / "b.json"
        record.write_text(json.dumps({"schema": "landing-loop/1", "bet": "b", "cost": cost}), encoding="utf-8")
        r = self.run_report(record=str(record))
        self.assertEqual(r["versions"][-1]["cost_per_task"], 0.0281)
        self.assertIsNone(r["versions"][0]["cost_per_task"])
        cited = [row for row in r["ledger"] if row["label"].endswith(", cited")]
        self.assertEqual([row["source"] for row in cited], ["usage.csv"])
        self.assertIn("cited from cost-budget-check: $0.0281", report.markdown(r))

    def test_status_vocabulary(self) -> None:
        for kw in ({}, {"seal": None}, {"target": 99.0}, {"target": None}):
            self.assertIn(self.run_report(**kw)["status"], {"meets target", "below target", "not confirmed: too close to call", None})

    def test_24_of_30_never_reads_as_a_precise_80(self) -> None:
        r = self.run_report()
        self.assertEqual(r["status"], "not confirmed: too close to call")
        why = r["reasons"][0]
        self.assertIn("62.7% to 90.5%", why)
        self.assertIn("however many cases", why)
        self.assertIn("**Status: not confirmed: too close to call.**", report.markdown(r))

    def test_meets_target_only_when_the_interval_clears_it(self) -> None:
        r = self.run_report(target=60.0)
        self.assertEqual(r["status"], "meets target")
        self.assertIn("low end 62.7%", r["reasons"][0])

    def test_inside_noise_names_the_cases_that_would_settle_it(self) -> None:
        r = self.run_report(target=75.0)
        self.assertEqual(r["status"], "not confirmed: too close to call")
        need = evalcore.cases_to_clear(80.0, 75.0)
        self.assertIn(f"{need} cases would clear it", r["reasons"][0])

    def test_cases_to_clear_is_the_fewest_that_clear(self) -> None:
        need = evalcore.cases_to_clear(85.0, 80.0)
        self.assertTrue(evalcore.clears(evalcore.wilson(0.85 * need, need), 80.0))
        self.assertFalse(evalcore.clears(evalcore.wilson(0.85 * (need - 1), need - 1), 80.0))
        self.assertIsNone(evalcore.cases_to_clear(80.0, 80.0))
        self.assertIsNone(evalcore.cases_to_clear(70.0, 80.0))
        self.assertIsNotNone(evalcore.cases_to_clear(10.0, 20.0, higher_is_better=False))

    def test_inside_noise_and_another_gap_is_not_confirmed(self) -> None:
        r = self.run_report(seal=None)
        self.assertIsNone(r["status"])
        self.assertTrue(any("inside" in x or "point estimate" in x for x in r["reasons"]))


class OneRule(unittest.TestCase):
    """The page, the stored evals.status and the CI gate read one rule, evalcore.check_word."""

    @staticmethod
    def latest(passed: int, cases: int) -> dict:
        rate = evalcore.pct(passed, cases)
        ci = wilson(passed, cases)
        return {"pass_rate": rate, "pass_ci": ci, "passed": passed, "cases": cases, "judge_scored": False, "dev_pass_rate": None, "autonomy_rate": None}

    def test_the_rule_reads_the_range_ends(self) -> None:
        self.assertEqual(evalcore.check_word((80.0, 95.0), 80), "meets target")
        self.assertEqual(evalcore.check_word((60.0, 79.9), 80), "below target")
        self.assertEqual(evalcore.check_word((52.1, 83.3), 80), "not confirmed: too close to call")
        self.assertEqual(evalcore.check_word((10.0, 20.0), 25, higher_is_better=False), "meets target")
        self.assertEqual(evalcore.check_word((26.0, 40.0), 25, higher_is_better=False), "below target")

    def test_21_of_30_at_an_80_target_is_too_close_to_call_everywhere(self) -> None:
        import render_html

        latest = self.latest(21, 30)  # 70%, range 52.1 to 83.3: the high end reaches over 80
        status, blocking, reasons = report.decide_status(latest, 80.0, True, None, None)
        self.assertEqual((status, blocking), ("not confirmed: too close to call", False))
        self.assertIn("52.1% to 83.3%", reasons[-1])
        self.assertIn("not confirmed below", reasons[-1])
        # The page reads the same word for that row.
        self.assertEqual(render_html.range_word(latest, 80.0), status)
        # The CI gate: below-target passes, not-met fails, blocking passes.
        rep = {"latest": "v1.3", "status": status, "blocking": blocking}
        with redirect_stdout(io.StringIO()):
            report.gate(rep, "below-target")
            report.gate(rep, "blocking")
            with self.assertRaises(SystemExit) as ctx:
                report.gate(rep, "not-met")
        self.assertEqual(ctx.exception.code, 2)

    def test_far_under_blocks_but_keeps_the_range_word(self) -> None:
        latest = self.latest(3, 6)  # 50%, range 18.8 to 81.2: far under 80, yet the range reaches over it
        status, blocking, _ = report.decide_status(latest, 80.0, True, None, None)
        self.assertEqual((status, blocking), ("not confirmed: too close to call", True))


class OneCommand(Temp):
    def copy_traces(self) -> Path:
        dst = self.tmp / "traces.csv"
        dst.write_bytes(TRACES.read_bytes())
        return dst

    def test_first_run_seals_and_sets_up_calibration(self) -> None:
        src = self.copy_traces()
        out = self.tmp / "run"
        buf = io.StringIO()
        with redirect_stdout(buf):
            run.main([str(src), "--feature", "Quote drafting", "--target", "80", "--out", str(out)])
        seal = json.loads((self.tmp / "traces.seal.json").read_text(encoding="utf-8"))
        self.assertEqual(seal, json.loads(SEAL.read_text(encoding="utf-8")))
        self.assertTrue((out / "calibration_cases.csv").exists())
        self.assertIn("not confirmed", buf.getvalue())

    def test_second_run_with_a_calibrated_judge_meets_target(self) -> None:
        src = self.copy_traces()
        out = self.tmp / "run"
        with redirect_stdout(io.StringIO()):
            run.main([str(src), "--feature", "x", "--target", "80", "--out", str(out)])
            run.main([str(src), "--feature", "x", "--target", "60", "--out", str(out), "--judge-scores", str(JUDGE), "--fail-on", "below-target"])
        self.assertEqual(json.loads((out / "report.json").read_text(encoding="utf-8"))["status"], "meets target")

    def test_too_close_to_call_fails_not_met_but_not_below_target_or_blocking(self) -> None:
        src = self.copy_traces()
        for i, gate in enumerate(("blocking", "below-target")):
            with redirect_stdout(io.StringIO()):
                run.main([str(src), "--feature", "x", "--target", "80", "--out", str(self.tmp / f"a{i}"), "--judge-scores", str(JUDGE), "--fail-on", gate])
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            run.main([str(src), "--feature", "x", "--target", "80", "--out", str(self.tmp / "b"), "--judge-scores", str(JUDGE), "--fail-on", "not-met"])
        self.assertEqual(ctx.exception.code, 2)

    def test_fail_on_gates_ci(self) -> None:
        src = self.copy_traces()
        # 24 of 30 has a high end of 90.5%, under a 95% target: below target on the range, so the gate trips.
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            run.main([str(src), "--feature", "x", "--target", "95", "--out", str(self.tmp / "run"), "--judge-scores", str(JUDGE), "--fail-on", "below-target"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertTrue((self.tmp / "run" / "report.md").exists())
        # An unconfirmed run (no judge calibration) is not below target, but it is not met either.
        with redirect_stdout(io.StringIO()):
            run.main([str(src), "--feature", "x", "--target", "80", "--out", str(self.tmp / "u"), "--fail-on", "below-target"])
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            run.main([str(src), "--feature", "x", "--target", "80", "--out", str(self.tmp / "v"), "--fail-on", "not-met"])
        self.assertEqual(ctx.exception.code, 2)

    def test_fail_on_blocking_trips_only_on_a_blocking_finding(self) -> None:
        src = self.copy_traces()
        with redirect_stdout(io.StringIO()):
            run.main([str(src), "--feature", "x", "--target", "85", "--out", str(self.tmp / "a"), "--judge-scores", str(JUDGE), "--fail-on", "blocking"])
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            run.main([str(src), "--feature", "x", "--target", "95", "--out", str(self.tmp / "b"), "--judge-scores", str(JUDGE), "--fail-on", "blocking"])
        self.assertEqual(ctx.exception.code, 2)

    def test_an_edit_after_sealing_blocks_the_next_run(self) -> None:
        src = self.copy_traces()
        with redirect_stdout(io.StringIO()):
            run.main([str(src), "--feature", "x", "--out", str(self.tmp / "run")])
        held = sorted(json.loads(SEAL.read_text())["ids"])[0]
        rows = read_rows(src)
        for r in rows:
            if r["id"] == held:
                r["input"] += " (easier)"
        write_rows(rows, src)
        with redirect_stdout(io.StringIO()), self.assertRaises(EvalError):
            run.main([str(src), "--feature", "x", "--out", str(self.tmp / "run2")])


BANNED = re.compile(r"\b(AI-powered|unlock|supercharge|seamless(ly)?|robust|get started|disrupting|revolutionizing)\b", re.I)
LEVERAGE_VERB = re.compile(r"\bleverag(e|es|ed|ing) (the|our|your|a|an|this|these|it)\b", re.I)


class Hygiene(unittest.TestCase):
    def text_files(self) -> list[Path]:
        skip = {".git", "__pycache__", ".ruff_cache"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.parts) and p.suffix in {".py", ".md", ".json", ".yml", ".csv", ""}]

    def test_no_em_dashes(self) -> None:
        for p in self.text_files():
            with self.subTest(path=str(p.relative_to(ROOT))):
                self.assertNotIn(EM_DASH, p.read_text(encoding="utf-8"))

    def test_no_banned_words(self) -> None:
        for p in self.text_files():
            if p.name == "test_eval_kit.py":
                continue
            text = p.read_text(encoding="utf-8")
            with self.subTest(path=str(p.relative_to(ROOT))):
                self.assertIsNone(BANNED.search(text))
                self.assertIsNone(LEVERAGE_VERB.search(text))

    def test_report_text_is_clean(self) -> None:
        md = report.markdown(report.build(args()))
        self.assertNotIn(EM_DASH, md)
        self.assertIsNone(BANNED.search(md))

    def test_ci_reference_uses_real_flags(self) -> None:
        text = (ROOT / "skills" / "eval-kit" / "references" / "ci-gate.md").read_text(encoding="utf-8")
        for flag in re.findall(r"(--[a-z-]+)", text):
            with self.subTest(flag=flag):
                self.assertIn(flag, (SCRIPTS / "run.py").read_text(encoding="utf-8"))

    def test_versions_in_step(self) -> None:
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        skill = (ROOT / "skills" / "eval-kit" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(plugin["version"], "0.3.7")
        self.assertIn('version: "0.3.7"', skill)


if __name__ == "__main__":
    unittest.main()
