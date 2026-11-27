# Eval kit: honest evals for one feature

A free Claude skill that turns your AI feature's traces into a pass rate and an autonomy rate you can defend, judged against the feature's landing brief.

**Why it matters:** an eval you tuned against tells you the prompt memorised its practice cases. This kit seals a holdout, tests the judge with cases built to be rejected, and refuses the claims the data can't carry.

**How it works:** Python computes every figure from your CSV and writes a ledger row for each. Claude reads the results and writes the words.

## Install

In Claude Code:

```text
/plugin marketplace add darrencard/landing-loop
/plugin install eval-kit@landing-loop
```

Standalone, paste this into Claude Code:

```text
Install the eval-kit Claude skill from https://github.com/darrencard/eval-kit (copy skills/eval-kit into ~/.claude/skills/eval-kit) and run its tests with python3 -m unittest discover -s evals. Then run it on my traces CSV with run.py: map my column names with --map, split the eval rows if they have no split, and use my target pass rate. Tell me the status, the held-out pass rate with its case count and interval, autonomy beside it, cost per task if cost-budget-check has written it, and the top failure cluster with its example traces.
```

## Your first report in 2 minutes

```bash
cd skills/eval-kit
python3 scripts/run.py ../../evals/fixtures/acme_quote_traces.csv --feature "Quote drafting" --target 80 --out run --illustrative
```

The first run seals the holdout and writes blind calibration cases for your judge. Score them, rerun with `--judge-scores`, and the report can say meets target. Your own export: add `--map id=trace_id` (and so on) instead of editing the file. CSV or JSONL both work. In CI: add `--fail-on blocking`; a ready GitHub Actions job is in [references/ci-gate.md](skills/eval-kit/references/ci-gate.md).

## Sample

[examples/acme/eval-kit.html](examples/acme/eval-kit.html) is one bet, Acme's quote drafting, run end to end: the canonical brief from the landing-loop repo, quote-drafting traces and a sealed holdout. Every figure is illustrative. It starts from the record cost-budget-check wrote for the same bet ([examples/acme/upstream](examples/acme/upstream)), so the cost tile cites that figure, and writes only the `evals` key of [examples/acme/landing/quote-drafting.json](examples/acme/landing/quote-drafting.json) and a Markdown twin. Regenerate it from the repo root:

```bash
python3 examples/acme/sample.py
```

Same inputs, same bytes: a test checks the command reproduces the committed files exactly. `--into DIR` writes them elsewhere.

## What it does

| Feature | What it does | What it does for you |
|---|---|---|
| Holdout split and seal | Splits cases by a stable hash, fingerprints the holdout, refuses a run where it moved | Your headline pass rate comes from cases nobody tuned against |
| Promotion rule | A new version wins only by gaining on the same held-out cases with no new failure | A higher average can't hide a case you broke |
| Intervals | A 95% Wilson interval on every rate, and a flag when a gain sits inside the noise | 24 of 30 never reads as a precise 80% |
| Judge calibration | 8 Acme cases, 6 written to be rejected, each on one axis, plus a template for your own; checks your judge's blind scores | You know your judge rejects bad answers before you trust its pass rate |
| Failure clusters | Groups failures by shared terms, with no categories set in advance, and 2 example traces each | Error analysis starts from what actually went wrong |
| Autonomy with its pair | Tasks finished without a person, only beside the held-out pass rate; the report names it when quality fell meanwhile | Autonomy can't rise unseen while quality falls |
| CI gate | `--fail-on blocking` or `below-target` exits 2 after writing the report | A regression stops the merge, with the reason to read |
| Landing Loop | Reads pass rate or autonomy against the landing brief's bar, and writes only the `evals` key of `landing/<bet>.json` | One brief, one record, eleven skills and the Leader Report reading the same figures |
| Live data | Reads OpenAI Evals, Langfuse and PostHog LLM exports; CSV as the fallback | No retyping traces into a spreadsheet |
| One page for leaders | A self-contained HTML page in the Leader Report's style, with a Markdown twin | Send it as it is; it opens offline |
| One owner for cost | Computes no cost of its own; cites cost per task from cost-budget-check's `cost` key, or says "cost not checked: run cost-budget-check" | One cost figure across the loop, never two that disagree |
| Leader Report source | Writes `evals.csv` in the Product & Technology Leader Report's columns | One run feeds your board update |
| Build check | meets target (only when the 95% interval's low end clears the target), not confirmed: inside noise (with the interval and the cases that would settle it), or below target, with every reason. landed, watch and stalled are a bet's status and only did-it-land sets them | A build check never reads as a bet's result |

The fixture is Acme, an invented invoicing company for trades businesses, and its quote-drafting assistant. Every figure it produces is illustrative.

Python 3.11 or later, standard library only. No network calls. MIT licensed. Status: v0.3.3. The live-data readers are tested on documented response shapes, not yet on a live account.

Claude and Claude Code are trademarks of Anthropic, PBC. These skills are independent and not affiliated with or endorsed by Anthropic.
