# Eval kit: honest evals for one feature

A free Claude skill that turns your AI feature's traces into a pass rate, an autonomy rate and a cost per task you can defend.

**Why it matters:** an eval you tuned against tells you the prompt memorised its practice cases. This kit seals a holdout, tests the judge with cases built to be rejected, and refuses the claims the data can't carry.

**How it works:** Python computes every figure from your CSV and writes a ledger row for each. Claude reads the results and writes the words.

## Install: paste this into Claude Code

```text
Install the eval-kit Claude skill from https://github.com/darrencard/eval-kit (copy skills/eval-kit into ~/.claude/skills/eval-kit), then run its tests with python3 -m unittest discover -s evals. Then set up evals for my AI feature from the traces CSV I give you: map my columns to its trace schema, split and seal a holdout, calibrate my judge, run the report with my target pass rate, and tell me the status, the held-out pass rate with its case count, autonomy beside it, cost per successful task and the top failure cluster.
```

## What it does

| Feature | What it does | What it does for you |
|---|---|---|
| Holdout split and seal | Splits cases by a stable hash, fingerprints the holdout, refuses a run where it moved | Your headline pass rate comes from cases nobody tuned against |
| Promotion rule | A new version wins only by gaining on the same held-out cases with no new failure | A higher average can't hide a case you broke |
| Judge calibration | 8 Acme cases, 6 written to be rejected, each on one axis; checks your judge's blind scores | You know your judge rejects bad answers before you trust its pass rate |
| Failure clusters | Groups failures by shared terms, with no categories set in advance | Error analysis starts from what actually went wrong |
| Autonomy with its pair | Tasks finished without a person, only beside the held-out pass rate | Autonomy can't rise unseen while quality falls |
| Leader Report source | Writes `evals.csv` in the Product & Technology Leader Report's columns | One run feeds your board update |
| Status | landed, watch or stalled, with every reason | One word a leader can act on |

## Run it yourself

```bash
cd skills/eval-kit
python3 scripts/report.py ../../evals/fixtures/acme_quote_traces.csv --out run --feature "Quote drafting" --seal ../../evals/fixtures/acme_holdout.seal.json --judge-scores ../../evals/fixtures/acme_judge_scores.csv --target 80 --illustrative
```

The fixture is Acme, an invented invoicing company for trades businesses, and its quote-drafting assistant. Every figure it produces is illustrative.

Python 3.11 or later, standard library only. No network calls. MIT licensed. Status: v0.1, private until reviewed.
