#!/usr/bin/env python3
"""Hold eval-kit 0.2's Landing Loop additions to their promises.

Usage:
  python3 -m unittest discover -s evals -v

Groups:
  Vendored      the vendored Leader Report files are byte for byte what PINS.json names.
  AgainstBrief  pass rate and autonomy judged against the brief's definition of good, with its own rule.
  LoopRecord    only the `evals` key of landing/<bet>.json is written; every other key is kept.
  Page          one self-contained HTML page in the style guide, every trace text escaped.
  LiveData      OpenAI Evals, Langfuse and PostHog exports to traces.

Standard library only. Runs on Python 3.11 or later.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "eval-kit" / "scripts"
VENDOR = SCRIPTS / "vendor"
FIX = ROOT / "evals" / "fixtures"
TRACES = FIX / "acme_quote_traces.csv"
SEAL = FIX / "acme_holdout.seal.json"
JUDGE = FIX / "acme_judge_scores.csv"
BRIEF = FIX / "acme_brief.md"
BRIEF_PRODUCT = FIX / "acme_brief_product_metric.md"
BRIEF_AUTONOMY = FIX / "acme_brief_autonomy.md"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(VENDOR))

import from_traces  # noqa: E402
import landing  # noqa: E402
import landing_brief  # noqa: E402
import render_html  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402
from evalcore import EVALS_COLUMNS, EvalError, load_traces  # noqa: E402


def build(**kw) -> dict:
    base = {"traces": str(TRACES), "feature": "Quote drafting", "seal": str(SEAL), "judge_scores": str(JUDGE), "calibration_cases": None}
    base.update({"target": 80.0, "illustrative": True, "map": None})
    base.update(kw)
    return report.build(argparse.Namespace(**base))


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class Vendored(unittest.TestCase):
    def test_every_vendored_file_matches_its_pin(self) -> None:
        pins = json.loads((VENDOR / "PINS.json").read_text(encoding="utf-8"))
        self.assertRegex(pins["commit"], r"^[0-9a-f]{40}$")
        on_disk = {p.name for p in VENDOR.iterdir() if p.name not in ("PINS.json", "README.md", "__pycache__")}
        self.assertEqual(on_disk, set(pins["files"]))
        for name, pin in pins["files"].items():
            with self.subTest(name=name):
                digest = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
                self.assertEqual(digest, pin["sha256"], f"{name} changed. Copy it again from the Leader Report and update PINS.json.")

    def test_the_acme_brief_parses_with_the_vendored_parser(self) -> None:
        brief = landing_brief.parse(BRIEF.read_text(encoding="utf-8"))
        self.assertEqual((brief.metric, brief.bar, brief.unit, brief.line), ("Held-out pass rate", 80.0, "%", "model call"))
        self.assertEqual(brief.tokens_per_task, 9000)


class AgainstBrief(Temp):
    def test_the_brief_sets_the_target(self) -> None:
        brief = landing.read_brief(BRIEF)
        self.assertEqual(landing.target_from(brief, None), 80.0)
        with self.assertRaises(EvalError) as ctx:
            landing.target_from(brief, 90.0)
        self.assertIn("Drop --target", str(ctx.exception))

    def test_a_product_metric_leaves_the_target_to_the_flag(self) -> None:
        self.assertEqual(landing.target_from(landing.read_brief(BRIEF_PRODUCT), 70.0), 70.0)

    def test_pass_rate_read_against_the_briefs_bar(self) -> None:
        key = landing.evals_key(build(), landing.read_brief(BRIEF), "2026-11-26")
        a = key["against_brief"]
        self.assertEqual((a["judged"], a["status"], a["value"], a["prior"]), ("pass_rate", "meets target", 80.0, 70.0))
        self.assertIn("62.7%", a["note"])
        self.assertEqual(key["status"], "meets target")
        self.assertFalse(key["blocking"])

    def test_autonomy_below_the_bar_reads_below_target(self) -> None:
        key = landing.evals_key(build(), landing.read_brief(BRIEF_AUTONOMY), "2026-11-26")
        a = key["against_brief"]
        self.assertEqual((a["judged"], a["status"], a["value"]), ("autonomy_rate", "below target", 71.5))
        self.assertEqual(key["status"], "below target")
        self.assertTrue(any("against the brief" in r for r in key["reasons"]))

    def test_never_a_bets_status_word(self) -> None:
        for brief in (BRIEF, BRIEF_AUTONOMY, BRIEF_PRODUCT):
            key = landing.evals_key(build(), landing.read_brief(brief), "2026-11-26")
            for status in (key["status"], key["against_brief"]["status"]):
                self.assertIn(status, {"meets target", "below target", None})

    def test_a_passed_date_is_named(self) -> None:
        key = landing.evals_key(build(), landing.read_brief(BRIEF_AUTONOMY), "2027-01-15")
        self.assertIn("has passed", key["against_brief"]["note"])

    def test_a_product_metric_is_left_to_did_it_land(self) -> None:
        a = landing.evals_key(build(), landing.read_brief(BRIEF_PRODUCT), "2026-11-26")["against_brief"]
        self.assertIsNone(a["judged"])
        self.assertIn("did-it-land", a["note"])

    def test_a_fixed_code_brief_is_flagged(self) -> None:
        text = BRIEF.read_text(encoding="utf-8").replace("model call.", "fixed code.")
        path = self.tmp / "brief.md"
        path.write_text(text, encoding="utf-8")
        key = landing.evals_key(build(), landing.read_brief(path), "2026-11-26")
        self.assertTrue(any("fixed code" in w for w in key["warnings"]))

    def test_every_figure_carries_the_contract_fields(self) -> None:
        key = landing.evals_key(build(), landing.read_brief(BRIEF), "2026-11-26")
        self.assertEqual(len(key["figures"]), 6)
        for name, f in key["figures"].items():
            with self.subTest(name=name):
                self.assertTrue({"value", "unit", "source", "window", "as_of"} <= set(f))
                self.assertEqual(set(f["window"]), {"from", "to"})
                self.assertIn("acme_quote_traces.csv", f["source"])

    def test_rows_are_the_leader_report_evals_columns(self) -> None:
        key = landing.evals_key(build(), landing.read_brief(BRIEF), "2026-11-26")
        self.assertEqual(key["columns"], list(EVALS_COLUMNS))
        self.assertEqual(
            key["rows"][-1],
            {
                "version": "v1.4",
                "run_at": "2026-11-15",
                "cases": 30,
                "passed": 24,
                **{c: key["rows"][-1][c] for c in ("cost_per_task",)},
                "tasks": 200,
                "tasks_unassisted": 143,
            },
        )

    def test_a_bad_brief_is_refused_whole(self) -> None:
        path = self.tmp / "brief.md"
        path.write_text("## Landing brief\n\n- **Metric:** Held-out pass rate\n", encoding="utf-8")
        with self.assertRaises(EvalError) as ctx:
            landing.read_brief(path)
        self.assertIn("missing", str(ctx.exception))


class LoopRecord(Temp):
    def key(self) -> dict:
        return landing.evals_key(build(), landing.read_brief(BRIEF), "2026-11-26")

    def test_creates_the_record(self) -> None:
        path = landing.write_record(self.tmp, "quote-drafting-assistant", BRIEF, self.key())
        rec = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(rec["schema"], "landing-loop/1")
        self.assertEqual(rec["brief"]["sha256"], hashlib.sha256(BRIEF.read_bytes()).hexdigest())
        self.assertEqual(sorted(rec), ["bet", "brief", "evals", "schema"])

    def test_keeps_every_other_key_exactly(self) -> None:
        others = {
            "schema": "landing-loop/1",
            "bet": "quote-drafting-assistant",
            "brief": {"path": str(BRIEF), "sha256": hashlib.sha256(BRIEF.read_bytes()).hexdigest()},
            "portfolio": {"rank": 2, "status": "watch", "nested": {"x": [1, 2.5, None]}},
            "spec": {"status": "landed"},
            "cost": {"tokens_per_task": {"value": 9000}},
            "landed": {"status": "watch"},
            "evals": {"stale": True},
        }
        path = self.tmp / "quote-drafting-assistant.json"
        path.write_text(json.dumps(others), encoding="utf-8")
        landing.write_record(self.tmp, "quote-drafting-assistant", BRIEF, self.key())
        rec = json.loads(path.read_text(encoding="utf-8"))
        for k in ("schema", "bet", "brief", "portfolio", "spec", "cost", "landed"):
            self.assertEqual(rec[k], others[k], k)
        self.assertNotIn("stale", rec["evals"])

    def test_refuses_a_changed_brief(self) -> None:
        path = self.tmp / "b.json"
        path.write_text(json.dumps({"schema": "landing-loop/1", "bet": "b", "brief": {"path": "x", "sha256": "0" * 64}}), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(EvalError) as ctx:
            landing.write_record(self.tmp, "b", BRIEF, self.key())
        self.assertIn("brief has changed", str(ctx.exception))
        self.assertEqual(path.read_bytes(), before)

    def test_refuses_another_bets_record_and_a_bad_slug(self) -> None:
        (self.tmp / "b.json").write_text(json.dumps({"schema": "landing-loop/1", "bet": "other"}), encoding="utf-8")
        with self.assertRaises(EvalError):
            landing.write_record(self.tmp, "b", BRIEF, self.key())
        with self.assertRaises(EvalError):
            landing.write_record(self.tmp, "../escape", BRIEF, self.key())

    def test_run_writes_record_page_and_twin(self) -> None:
        traces = self.tmp / "traces.csv"
        traces.write_bytes(TRACES.read_bytes())
        out, folder = self.tmp / "run", self.tmp / "landing"
        args = [str(traces), "--feature", "Quote drafting", "--out", str(out), "--brief", str(BRIEF), "--bet", "quote-drafting-assistant"]
        args += ["--landing", str(folder), "--judge-scores", str(JUDGE), "--illustrative"]
        with redirect_stdout(io.StringIO()):
            run.main(args)
        rec = json.loads((folder / "quote-drafting-assistant.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["evals"]["status"], "meets target")
        self.assertEqual(rec["evals"]["as_of"], "2026-11-15")
        self.assertIn("Against the landing brief: **meets target**", (out / "report.md").read_text(encoding="utf-8"))
        self.assertIn("Against the landing brief", (out / "report.html").read_text(encoding="utf-8"))

    def run_loop(self, record: dict | None) -> dict:
        traces = self.tmp / "traces.csv"
        traces.write_bytes(TRACES.read_bytes())
        folder = self.tmp / "landing"
        if record is not None:
            folder.mkdir()
            (folder / "quote-drafting-assistant.json").write_text(json.dumps(record), encoding="utf-8")
        args = [str(traces), "--feature", "Quote drafting", "--out", str(self.tmp / "run"), "--brief", str(BRIEF), "--bet", "quote-drafting-assistant"]
        with redirect_stdout(io.StringIO()):
            run.main([*args, "--landing", str(folder), "--judge-scores", str(JUDGE)])
        return json.loads((folder / "quote-drafting-assistant.json").read_text(encoding="utf-8"))

    def test_in_the_loop_cost_is_not_computed_here(self) -> None:
        ev = self.run_loop(None)["evals"]
        self.assertTrue(all(r["cost_per_task"] is None for r in ev["rows"]))
        self.assertFalse(any(k.startswith("cost_per_task") for k in ev["figures"]))
        self.assertEqual(ev["cost"]["note"], "cost not checked: run cost-budget-check")
        self.assertTrue(any("cost not checked: run cost-budget-check" in w for w in ev["warnings"]))

    def test_in_the_loop_cost_is_cited_from_the_cost_key(self) -> None:
        digest = hashlib.sha256(BRIEF.read_bytes()).hexdigest()
        cost = {
            "tool": "cost-budget-check 0.2.0",
            "cost_per_successful_task": {
                "value": 0.0281,
                "unit": "USD per task",
                "source": "usage.csv (sha256 abc)",
                "window": {"from": "2026-11-01", "to": "2026-11-15"},
                "as_of": "2026-11-16",
            },
        }
        record = {"schema": "landing-loop/1", "bet": "quote-drafting-assistant", "brief": {"path": str(BRIEF), "sha256": digest}, "cost": cost}
        rec = self.run_loop(record)
        ev = rec["evals"]
        self.assertEqual(rec["cost"], cost)
        self.assertEqual(ev["rows"][-1]["cost_per_task"], 0.0281)
        self.assertIsNone(ev["rows"][0]["cost_per_task"])
        self.assertEqual(ev["figures"]["cost_per_task@v1.4"]["source"], "usage.csv (sha256 abc)")
        self.assertTrue(ev["cost"]["cited"])

    def test_bet_without_brief_is_refused(self) -> None:
        with self.assertRaises(EvalError):
            run.main([str(TRACES), "--feature", "x", "--bet", "b", "--out", str(self.tmp / "run")])


class Page(Temp):
    def page(self, **kw) -> str:
        r = build(**kw)
        return render_html.render(r, landing.evals_key(r, landing.read_brief(BRIEF), "2026-11-26"))

    def test_self_contained(self) -> None:
        text = self.page()
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertIsNone(re.search(r"""(src|href)=["']?https?://""", text))
        self.assertNotIn("<script", text)
        self.assertIn('font-family:"Geist"', text)

    def test_status_prints_as_plain_words_with_no_status_colour(self) -> None:
        text = self.page()
        self.assertIn('<span class="status">meets target</span>', text)
        body = text.split("<main>", 1)[1]
        for word in ("landed", "watch", "stalled", "var(--landed)", "var(--watch)", "var(--stalled)"):
            self.assertNotIn(word, body)
        self.assertIn("Illustrative", text)

    def test_no_cost_figure_without_the_cost_key(self) -> None:
        text = self.page()
        self.assertIn("cost not checked: run cost-budget-check", text)
        self.assertNotRegex(text, r"\$0\.0\d")

    def test_trace_text_is_escaped(self) -> None:
        text = TRACES.read_text(encoding="utf-8").replace("Chase went", "<script>alert(1)</script> Chase went")
        path = self.tmp / "t.csv"
        path.write_text(text, encoding="utf-8")
        text = self.page(traces=str(path), seal=None)
        self.assertNotIn("<script>alert", text)
        self.assertIn("&lt;script&gt;", text)

    def test_every_ledger_row_is_on_the_page(self) -> None:
        r = build()
        text = render_html.render(r)
        for row in r["ledger"]:
            self.assertIn(f">{row['id']}<", text)


class LiveData(Temp):
    def write(self, name: str, data: object) -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def openai_items(self, passed: list[bool]) -> Path:
        items = [
            {
                "id": f"outputitem_{i}",
                "created_at": 1763164800,
                "status": "pass" if ok else "fail",
                "datasource_item_id": i,
                "datasource_item": {"id": f"q{i:03d}", "split": "holdout" if i % 3 == 0 else "development", "job": "tap"},
                "results": [{"name": "price-book-grader", "passed": ok, "score": 1.0 if ok else 0.0}],
                "sample": {"input": [{"role": "user", "content": f"Draft quote {i}"}], "output": [{"role": "assistant", "content": "Quote total $120"}]},
            }
            for i, ok in enumerate(passed, start=1)
        ]
        return self.write("items.json", {"object": "list", "data": items})

    def test_openai_eval_items(self) -> None:
        rows = from_traces.openai_eval_items(self.openai_items([True, False, True]), "v2")
        self.assertEqual(
            [(r["id"], r["passed"], r["split"]) for r in rows], [("q001", "true", "development"), ("q002", "false", "development"), ("q003", "true", "holdout")]
        )
        self.assertEqual(rows[0]["run_at"], "2025-11-15")
        self.assertEqual(rows[1]["note"], "failed graders: price-book-grader")
        self.assertEqual(rows[0]["input"], "Draft quote 1")

    def test_openai_item_with_no_case_id_is_refused(self) -> None:
        path = self.write("items.json", {"data": [{"id": "x", "status": "pass"}]})
        with self.assertRaises(EvalError):
            from_traces.openai_eval_items(path, "v2")

    def langfuse(self, with_human: bool = True) -> tuple[Path, Path]:
        traces = [
            {"id": f"tr{i}", "timestamp": "2026-11-15T10:00:00.000Z", "version": "v1.4", "input": {"job": "tap"}, "output": "Sent", "totalCost": 0.02}
            for i in range(3)
        ]
        scores = [{"traceId": f"tr{i}", "name": "succeeded", "value": 1 if i < 2 else 0, "dataType": "BOOLEAN"} for i in range(3)]
        if with_human:
            scores += [
                {"traceId": f"tr{i}", "name": "human_stepped_in", "value": 1 if i == 1 else 0, "comment": "edited hours" if i == 1 else None} for i in range(3)
            ]
        return self.write("lf_traces.json", {"data": traces}), self.write("lf_scores.json", {"data": scores})

    def test_langfuse_traces_and_scores(self) -> None:
        rows = from_traces.langfuse(*self.langfuse(), "succeeded", "human_stepped_in", None)
        self.assertEqual([(r["succeeded"], r["human_stepped_in"]) for r in rows], [("true", "false"), ("true", "true"), ("false", "false")])
        self.assertEqual(rows[1]["note"], "edited hours")
        self.assertEqual(rows[0]["cost_usd"], "0.020000")

    def test_langfuse_trace_with_no_score_is_refused(self) -> None:
        with self.assertRaises(EvalError) as ctx:
            from_traces.langfuse(*self.langfuse(with_human=False), "succeeded", "human_stepped_in", None)
        self.assertIn("human_stepped_in", str(ctx.exception))

    def test_posthog_query(self) -> None:
        data = {
            "columns": ["id", "version", "run_at", "succeeded", "human_stepped_in", "cost_usd", "output"],
            "results": [["t1", "v1.4", "2026-11-15 09:00:00", 1, 0, 0.03, "Sent"], ["t2", "v1.4", "2026-11-15", 0, 1, None, "Wrong contact"]],
        }
        rows = from_traces.posthog(self.write("ph.json", data))
        self.assertEqual([(r["succeeded"], r["human_stepped_in"], r["cost_usd"]) for r in rows], [("true", "false", "0.030000"), ("false", "true", "")])
        with self.assertRaises(EvalError):
            from_traces.posthog(self.write("bad.json", {"columns": ["id"], "results": []}))

    def test_cli_merges_sources_into_a_loadable_csv(self) -> None:
        out = self.tmp / "traces.csv"
        lf_t, lf_s = self.langfuse()
        with redirect_stdout(io.StringIO()):
            from_traces.main(["traces", "--out", str(out), "--openai-eval-items", str(self.openai_items([True] * 6)), "--version", "v1.4"])
            from_traces.main(["traces", "--out", str(self.tmp / "lf.csv"), "--langfuse-traces", str(lf_t), "--langfuse-scores", str(lf_s)])
        self.assertEqual(len(load_traces(out)), 6)
        self.assertEqual({t.kind for t in load_traces(self.tmp / "lf.csv")}, {"production"})


class SampleTest(unittest.TestCase):
    """The README's sample command reproduces the committed Acme sample byte for byte."""

    def test_sample_reproduces_committed_files(self):
        sys.path.insert(0, str(ROOT / "examples" / "acme"))
        import sample

        acme = ROOT / "examples" / "acme"
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            sample.main(["--into", tmp])
            for name in ("eval-kit.html", "eval-kit.md", "landing/quote-drafting.json"):
                self.assertEqual((Path(tmp) / name).read_bytes(), (acme / name).read_bytes(), name)

    def test_sample_record_adds_only_evals_to_the_cost_record(self):
        acme = ROOT / "examples" / "acme"
        record = json.loads((acme / "landing" / "quote-drafting.json").read_text(encoding="utf-8"))
        upstream = json.loads((acme / "upstream" / "cost-budget-check.json").read_text(encoding="utf-8"))
        self.assertEqual(set(record), {"schema", "bet", "brief", "cost", "evals"})
        self.assertEqual(record["cost"], upstream["cost"])  # read, cited, never rewritten
        self.assertEqual(record["brief"]["sha256"], upstream["brief"]["sha256"])


if __name__ == "__main__":
    unittest.main()
