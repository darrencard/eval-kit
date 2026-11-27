#!/usr/bin/env python3
"""Hold eval-kit 0.2's Landing Loop additions to their promises.

Usage:
  python3 -m unittest discover -s evals -v

Groups:
  Vendored      the vendored Leader Report files are byte for byte what VENDORED.json names.
  AgainstBrief  pass rate and autonomy judged against the brief's definition of good, with its own rule.
  LoopRecord    only the `evals` key of landing/<bet>.json is written; every other key is kept.
  Page          one self-contained HTML page in the style guide, every trace text escaped.
  LiveData      OpenAI Evals, Langfuse and PostHog exports to traces.

Standard library only. Runs on Python 3.11 or later.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import shutil
import subprocess
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
import svgkit  # noqa: E402
from evalcore import BELOW, EVALS_COLUMNS, MEETS, NOISE, EvalError, load_traces  # noqa: E402


def _old_python() -> str | None:
    """A Python older than 3.11 on this machine, to prove the guard runs first; None when there is none."""
    for name in ("python3.9", "python3.10", "/usr/bin/python3"):
        exe = shutil.which(name)
        if not exe:
            continue
        done = subprocess.run([exe, "-c", "import sys; print(sys.version_info < (3, 11))"], capture_output=True, text=True, check=False)  # noqa: S603
        if done.stdout.strip() == "True":
            return exe
    return None


OLD_PYTHON = _old_python()


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
        pins = json.loads((VENDOR / "VENDORED.json").read_text(encoding="utf-8"))
        self.assertRegex(pins["commit"], r"^[0-9a-f]{40}$")
        svgkit_pin = pins["landing-loop"]
        self.assertRegex(svgkit_pin["commit"], r"^[0-9a-f]{40}$")
        files = {**pins["files"], **svgkit_pin["files"]}
        on_disk = {p.name for p in VENDOR.iterdir() if p.name not in ("VENDORED.json", "README.md", "__pycache__")}
        self.assertEqual(on_disk, set(files))
        for name, pin in files.items():
            with self.subTest(name=name):
                digest = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
                self.assertEqual(digest, pin["sha256"], f"{name} changed. Copy it again from its pinned commit and update VENDORED.json.")

    def test_svgkit_is_pinned_at_1_3_0(self) -> None:
        pin = json.loads((VENDOR / "VENDORED.json").read_text(encoding="utf-8"))["landing-loop"]
        self.assertEqual(pin["commit"], "211866e426169d876a9ed752d4224a685f826b53")
        self.assertEqual(pin["files"]["svgkit.py"]["sha256"], "b8d197ded449247830f9ad6a4d90182663793f85e7a89c5bc42fbfa1724159df")
        self.assertEqual(svgkit.VERSION, "1.3.0", "range_line(interval=...) needs svgkit 1.3.0")

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
        self.assertEqual((a["judged"], a["status"], a["value"], a["prior"]), ("pass_rate", "not confirmed: too close to call", 80.0, 70.0))
        self.assertIn("62.7%", a["note"])
        self.assertEqual(key["status"], "not confirmed: too close to call")
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
                self.assertIn(status, {"meets target", "below target", "not confirmed: too close to call", None})

    def test_combined_status(self) -> None:
        judged = {"judged": "pass_rate"}
        cases = [
            (("meets target", "meets target"), "meets target"),
            (("meets target", "not confirmed: too close to call"), "not confirmed: too close to call"),
            (("not confirmed: too close to call", "meets target"), "not confirmed: too close to call"),
            (("not confirmed: too close to call", "below target"), "below target"),
            ((None, "meets target"), None),
        ]
        for (own, theirs), want in cases:
            with self.subTest(own=own, theirs=theirs):
                self.assertEqual(landing.combined(own, {**judged, "status": theirs}), want)
        self.assertEqual(landing.combined("not confirmed: too close to call", {"judged": None, "status": None}), "not confirmed: too close to call")

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
        self.assertEqual(rec["evals"]["status"], "not confirmed: too close to call")
        self.assertEqual(rec["evals"]["as_of"], "2026-11-15")
        self.assertIn("Against the landing brief: **not confirmed: too close to call**", (out / "report.md").read_text(encoding="utf-8"))
        self.assertIn("The plan's number", (out / "report.html").read_text(encoding="utf-8"))

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
        self.assertIn('<span class="status">not confirmed: too close to call</span>', text)
        body = text.split('<main class="solo">', 1)[1]
        for word in ("landed", "watch", "stalled", "var(--landed)", "var(--watch)", "var(--stalled)"):
            self.assertNotIn(word, body, "green, grey-white and red belong to did-it-land's words, which this page never prints")
        self.assertIn("Illustrative", text)

    def test_on_the_leader_report_template(self) -> None:
        text = self.page()
        template = render_html.floor_fonts(render_html.STYLE.search((VENDOR / "template.html").read_text(encoding="utf-8")).group(1))
        self.assertIn(template, text, "the page carries the template's whole stylesheet, with only its font sizes floored at 11px")
        self.assertIn('<span translate="no">DACARD</span>', text)
        self.assertIn('<span class="sk-ill">Illustrative</span>', text)
        self.assertIn(":root{--ill:#74A5DA}", text, "the Illustrative tag is blue")
        css = text.split(template, 1)[1].split("</style>", 1)[0]
        for rule in ("::selection{background:var(--t1)", ":focus-visible{outline-color:var(--t1)}"):
            self.assertIn(rule, css, "the page's own rules come after the template's, so they win")
        self.assertNotIn('class="ok"', text, "the template's healthy-side band is green, a status colour")
        brass = [r for r in re.findall(r"[^}]*var\(--brass[^}]*}", css)]
        # Brass is a person's call only: the next step's owner and decider, and svgkit's person_call (.sc-o, .sc-pm).
        self.assertTrue(brass and all(r.lstrip("}\n ").startswith((".next", ".scg .sc-o", ".sc-pm")) for r in brass), brass)

    def test_the_page_follows_the_sample_anatomy(self) -> None:
        text = self.page()
        body = text.split('<main class="solo">', 1)[1]
        order = [
            'class="sk-hdr"',
            "<h1>Quote drafting is too close to call.</h1>",
            'class="status"',
            '<div class="sc scg"',
            "What to do next",
            'class="cols"',
            "For your engineers",
        ]
        at = [body.index(x) for x in order]
        self.assertEqual(at, sorted(at))
        self.assertIn('<span class="o">Head of Product, Acme</span>', render_html.render(build(), None, landing.read_brief(BRIEF)))
        owned = render_html.render(build(), None, landing.read_brief(BRIEF), "Tech lead, Acme")
        self.assertIn('<span class="who"><span class="w">Tech lead, Acme</span><span class="o">Head of Product, Acme</span>', owned)
        self.assertIn("<details><summary>For your engineers</summary>", body)

    def test_the_visual_draws_only_figures_the_page_prints(self) -> None:
        text = self.page()
        self.assertEqual(svgkit.unprinted(text), [])
        frame = svgkit.frames_in(text)[0]
        self.assertIn('<span class="sc-l"><b>21 OF 30</b> · 70% · RANGE 52.1 TO 83.3%</span>', frame)
        self.assertIn('<span class="sc-l"><b>24 OF 30</b> · 80% · RANGE 62.7 TO 90.5%</span>', frame)
        self.assertIn('<span class="sc-k"><i class="k-tg"></i>target 80%</span>', frame, "the target prints once, in the legend")

    def test_the_visual_states_the_answer(self) -> None:
        r = build()
        labels = re.findall(r'role="img" aria-label="([^"]+)"', self.page())
        self.assertEqual(len(labels), 1)
        self.assertIn("passes 24 of 30 test cases kept back, 80%", labels[0])
        self.assertIn("62.7% to 90.5%", labels[0])
        self.assertTrue(labels[0].endswith("against a 80% target, so it is not confirmed: too close to call."), labels[0])
        self.assertIn("with no target set.", render_html.scorecard(r["versions"], None, None, True))

    # The scorecard grammar (landing-loop tools/SCORECARD-ROLLOUT.md, svgkit 1.3.0)

    def css(self, text: str) -> str:
        return text.split("<style>", 1)[1].split("</style>", 1)[0]

    def test_one_frame_one_row_per_version_with_its_check_word(self) -> None:
        r = build()
        frames = svgkit.frames_in(self.page())
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].count('<div class="sc-r">'), len(r["versions"]))
        self.assertEqual(re.findall(r'<span class="sc-n">([^<]+)</span>', frames[0]), ["Version v1.3, 2026-10-15", "Version v1.4, 2026-11-15"])
        words = re.findall(r'<span class="sc-w[^"]*">([^<]+)</span>', frames[0])
        self.assertEqual(words, ["NOT CONFIRMED: TOO CLOSE TO CALL"] * 2, "v1.3's range, 52.1% to 83.3%, crosses the 80% target")

    def test_every_version_row_reads_on_one_range_rule(self) -> None:
        def v(lo: float, hi: float) -> dict:
            return {"pass_ci": [lo, hi]}

        self.assertEqual(render_html.range_word(v(81, 95), 80), MEETS)
        self.assertEqual(render_html.range_word(v(80, 95), 80), MEETS)
        self.assertEqual(render_html.range_word(v(60, 79.9), 80), BELOW)
        self.assertEqual(render_html.range_word(v(52.1, 83.3), 80), NOISE)
        self.assertIsNone(render_html.range_word(v(52.1, 83.3), None))
        old, new = v(60, 70), v(70, 90)
        self.assertEqual(render_html.version_word(old, new, 80, NOISE), '<span class="sc-w ink">BELOW TARGET</span>')
        self.assertEqual(render_html.own_rule(new, 80, NOISE), "", "the newest row agrees with the range rule: no caption note")
        self.assertIn("the newest prints the run's status", render_html.own_rule(new, 80, None))

    def test_the_figure_column_is_numerals_and_uppercase_words(self) -> None:
        figures = re.findall(r'<span class="sc-l">(.*?)</span>', svgkit.frames_in(self.page())[0])
        self.assertTrue(figures)
        for f in figures:
            self.assertEqual(re.sub(r"<[^>]+>", "", f), re.sub(r"<[^>]+>", "", f).upper(), f)

    def test_no_text_inside_a_picture_and_no_scaled_picture(self) -> None:
        text = self.page()
        self.assertEqual(svgkit.svgs_with_text(text), [])
        self.assertEqual(svgkit.scaled_svgs_in(text), [])

    def test_labels_render_12px_and_names_14px(self) -> None:
        css = self.css(self.page())
        self.assertEqual(set(svgkit.font_sizes(css)), {"var(--sc-m)", "var(--sc-n)"})
        self.assertIn("--sc-m:calc(12px / var(--sc-z))", css)
        self.assertIn("--sc-n:calc(14px / var(--sc-z))", css)
        self.assertIn(".scg{--sc-z:1;", css, "a sample page has no zoom")

    def test_text_runs_the_full_column(self) -> None:
        # The template caps .lede at 62ch; the page's own rules come last and lift every cap on text.
        for rule in re.findall(r"([^{}]+)\{([^}]*max-width:[^}]*)\}", render_html.PAGE_CSS):
            selector, body = rule
            if re.search(r"(^|[\s,])(h1|\.lede|p|\.next)([\s,:.]|$)", selector):
                self.assertIn("max-width:none", body, selector)
        self.assertIn(".solo h1,.solo .lede,.solo .next,.solo .slide p,.solo .slide li,.solo .sc-c,.sk figcaption{max-width:none}", render_html.PAGE_CSS)
        css = self.css(self.page())
        self.assertGreater(css.rindex("{max-width:none}"), css.index("max-width:62ch"), "the override comes after the template's cap")
        self.assertIn("text-wrap:balance", render_html.PAGE_CSS)
        self.assertIn(".solo .slide p,.solo .slide li,.solo .sc-c{text-wrap:pretty}", render_html.PAGE_CSS)

    def test_no_box_inside_the_frame_and_no_overlap(self) -> None:
        text = self.page()
        self.assertEqual(svgkit.boxes_in_frames(text, self.css(text)), [])
        self.assertNotIn("position:absolute", svgkit.SCORECARD_CSS)
        self.assertNotIn('class="chip"', text.split("For your engineers", 1)[0])
        self.assertNotIn('class="panel"', text, "no card around the frame")

    def test_no_legacy_svgkit_primitive_draws_on_the_page(self) -> None:
        import warnings

        self.assertEqual(svgkit.legacy_in(self.page()), [])
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            self.page()

    def test_no_status_colour_in_the_frame(self) -> None:
        frame = svgkit.frames_in(self.page())[0]
        self.assertNotIn('class="ac ', frame)
        self.assertNotIn('class="st ', frame)

    def test_every_version_row_draws_its_likely_range(self) -> None:
        r = build()
        rows = svgkit.frames_in(self.page())[0].split('<div class="sc-r">')[1:]
        self.assertEqual(len(rows), len(r["versions"]))
        for row, v in zip(rows, r["versions"], strict=True):
            with self.subTest(version=v["version"]):
                svg = re.search(r"<svg.*?</svg>", row, re.S).group(0)
                self.assertEqual(svg.count('class="iv"'), 3, "one segment and two end caps")
                self.assertNotIn("<text", svg)
                lo, hi = v["pass_ci"]
                self.assertIn(f"RANGE {lo:g} TO {hi:g}%", row, "the interval's ends print as figures in the row")
        self.assertEqual(svgkit.svgs_with_text(self.page()), [])

    def test_one_scale_for_the_frame_so_every_target_tick_lines_up(self) -> None:
        frame = svgkit.frames_in(self.page())[0]
        ticks = set(re.findall(r'class="tg" x="([^"]+)"', frame))
        self.assertEqual(len(ticks), 1, ticks)

    def test_public_copy_uses_plain_words(self) -> None:
        # The header prints the skill's plain name, "Eval kit"; the words below are checked in everything after it.
        public = svgkit.page_text(self.page().split("</header>", 1)[1].split("For your engineers", 1)[0]).lower()
        for word in ("held-out", "holdout", "95% interval", "inside noise", "eval ", "evals ", "judge", "autonomy", "traces"):
            self.assertNotIn(word, public)
        for word in (r"\brecords?\b", r"\bbets?\b", r"\bthe bar\b", r"\bprds?\b", r"\barr\b", r"\btokens?\b"):
            self.assertIsNone(re.search(word, public), word)

    def test_no_text_is_smaller_than_11px(self) -> None:
        text = self.page()
        css = " ".join(re.findall(r"<style>(.*?)</style>", text, re.DOTALL)) + " " + " ".join(re.findall(r'style="([^"]*)"', text))
        sizes = re.findall(r"font-size\s*:\s*([\d.]+)px", css) + re.findall(r"font\s*:[^;{}]*?(?<![\w.-])([\d.]+)px", css)
        sizes += re.findall(r'font-size="([\d.]+)"', text)
        self.assertTrue(sizes)
        self.assertEqual([s for s in sizes if float(s) < 11], [])
        self.assertNotRegex(css, r"font-size\s*:\s*[\d.]+r?em")
        before, after = (
            ".a{font:400 10px/16px var(--mono)}.b{font-size:10.5px}.c{font-size:13px}",
            ".a{font:400 11px/16px var(--mono)}.b{font-size:11px}.c{font-size:13px}",
        )
        self.assertEqual(render_html.floor_fonts(before), after)

    def test_the_header_prints_the_plain_name_and_the_code_name_is_for_engineers(self) -> None:
        text = self.page()
        self.assertEqual(re.search(r'<span class="sk-meta"><span>(.*?)</span>', text).group(1), "Eval kit")
        public, fold = text.split("For your engineers", 1)
        self.assertNotIn("eval-kit", svgkit.page_text(public).lower())
        self.assertIn(f"Built by eval-kit {landing.VERSION}.", fold)

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

    def test_upstream_brief_path_is_the_records(self):
        # The landing-loop record holds the brief path relative to examples/acme; the copy must match it exactly.
        upstream = json.loads((ROOT / "examples" / "acme" / "upstream" / "cost-budget-check.json").read_text(encoding="utf-8"))
        self.assertEqual(upstream["brief"]["path"], "briefs/quote-drafting.md")

    def test_a_failed_run_leaves_the_record_alone(self):
        sys.path.insert(0, str(ROOT / "examples" / "acme"))
        import sample

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "landing" / "quote-drafting.json"
            record.parent.mkdir()
            record.write_text('{"evals": "kept"}\n', encoding="utf-8")

            def crash(argv):
                raise RuntimeError("crash mid-run")

            real, sample.run.main = sample.run.main, crash
            try:
                with self.assertRaises(RuntimeError):
                    sample.main(["--into", tmp])
            finally:
                sample.run.main = real
            self.assertEqual(record.read_text(encoding="utf-8"), '{"evals": "kept"}\n')
            self.assertFalse((Path(tmp) / "eval-kit.html").exists())


CANDIDATES = [*SCRIPTS.glob("*.py"), *(ROOT / "examples").rglob("*.py"), ROOT / "evals" / "make_fixture.py"]
ENTRY_SCRIPTS = sorted(p for p in CANDIDATES if '__name__ == "__main__"' in p.read_text(encoding="utf-8"))


class Floor(unittest.TestCase):
    """Python 3.11 or later, checked before anything is read or written."""

    def test_every_entry_script_checks_the_version_first(self):
        self.assertGreaterEqual(len(ENTRY_SCRIPTS), 9)
        for path in ENTRY_SCRIPTS:
            with self.subTest(script=path.name):
                body = ast.parse(path.read_text(encoding="utf-8")).body
                body = [n for n in body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
                body = [n for n in body if not (isinstance(n, ast.ImportFrom) and n.module == "__future__")]
                self.assertEqual(ast.unparse(body[0]), "import sys")
                self.assertIsInstance(body[1], ast.If)
                self.assertIn("sys.version_info < (3, 11)", ast.unparse(body[1].test))
                self.assertIn("python3.12", ast.unparse(body[1]))

    @unittest.skipUnless(OLD_PYTHON, "no Python older than 3.11 on this machine")
    def test_an_old_python_is_refused_and_the_record_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "landing" / "quote-drafting.json"
            record.parent.mkdir()
            record.write_text('{"evals": "kept"}\n', encoding="utf-8")
            for script in (ROOT / "examples" / "acme" / "sample.py", SCRIPTS / "run.py"):
                with self.subTest(script=script.name):
                    done = subprocess.run([OLD_PYTHON, str(script), "--into", tmp], capture_output=True, text=True, check=False)  # noqa: S603
                    self.assertEqual(done.returncode, 1)
                    self.assertIn("needs Python 3.11 or later; try python3.12", done.stderr)
            self.assertEqual(record.read_text(encoding="utf-8"), '{"evals": "kept"}\n')

    def test_skill_description_fits(self):
        text = (ROOT / "skills" / "eval-kit" / "SKILL.md").read_text(encoding="utf-8")
        description = re.search(r"^description: (.*)$", text, re.M).group(1)
        self.assertLess(len(description), 1024)


if __name__ == "__main__":
    unittest.main()
