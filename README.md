# Eval kit: honest evals for one feature

A free Claude skill that turns your AI feature's traces into a pass rate, an autonomy rate and a cost per task you can defend.

**Why it matters:** an eval you tuned against tells you the prompt memorised its practice cases. This kit seals a holdout, tests the judge with cases built to be rejected, and refuses the claims the data can't carry.

**How it works:** Python computes every figure from your CSV and writes a ledger row for each. Claude reads the results and writes the words.

## Install: paste this into Claude Code

```text
Install the eval-kit Claude skill from https://github.com/darrencard/eval-kit (copy skills/eval-kit into ~/.claude/skills/eval-kit) and run its tests with python3 -m unittest discover -s evals. Then run it on my traces CSV with run.py: map my column names with --map, split the eval rows if they have no split, and use my target pass rate. Tell me the status, the held-out pass rate with its case count and interval, autonomy beside it, cost per successful task and the top failure cluster with its example traces.
```

## Your first report in 2 minutes

```bash
cd skills/eval-kit
python3 scripts/run.py ../../evals/fixtures/acme_quote_traces.csv --feature "Quote drafting" --target 80 --out run --illustrative
```

The first run seals the holdout and writes blind calibration cases for your judge. Score them, rerun with `--judge-scores`, and the report can say landed. Your own export: add `--map id=trace_id` (and so on) instead of editing the file. CSV or JSONL both work. In CI: add `--fail-on stalled`; a ready GitHub Actions job is in [references/ci-gate.md](skills/eval-kit/references/ci-gate.md).

## What it does

| Feature | What it does | What it does for you |
|---|---|---|
| Holdout split and seal | Splits cases by a stable hash, fingerprints the holdout, refuses a run where it moved | Your headline pass rate comes from cases nobody tuned against |
| Promotion rule | A new version wins only by gaining on the same held-out cases with no new failure | A higher average can't hide a case you broke |
| Intervals | A 95% Wilson interval on every rate, and a flag when a gain sits inside the noise | 24 of 30 never reads as a precise 80% |
| Judge calibration | 8 Acme cases, 6 written to be rejected, each on one axis, plus a template for your own; checks your judge's blind scores | You know your judge rejects bad answers before you trust its pass rate |
| Failure clusters | Groups failures by shared terms, with no categories set in advance, and 2 example traces each | Error analysis starts from what actually went wrong |
| Autonomy with its pair | Tasks finished without a person, only beside the held-out pass rate; stalled names it when quality fell meanwhile | Autonomy can't rise unseen while quality falls |
| CI gate | `--fail-on watch` or `stalled` exits 2 after writing the report | A regression stops the merge, with the reason to read |
| Leader Report source | Writes `evals.csv` in the Product & Technology Leader Report's columns | One run feeds your board update |
| Status | landed, watch or stalled, with every reason | One word a leader can act on |

The fixture is Acme, an invented invoicing company for trades businesses, and its quote-drafting assistant. Every figure it produces is illustrative.

Python 3.11 or later, standard library only. No network calls. MIT licensed. Status: v0.1, private until reviewed.
