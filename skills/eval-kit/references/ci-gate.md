# Eval gate in CI

Run the report on every pull request that changes a prompt, model or pipeline, and fail the check on a blocking finding. The report files are written before the exit, so the failed run can be read.

Copy `skills/eval-kit` into your repository (for example under `tools/eval-kit`), commit your traces CSV (or JSONL) and its seal file, then add this job. Pin actions to commit SHAs, as in this repository's own workflow.

```yaml
name: Evals
on:
  pull_request:
permissions:
  contents: read
jobs:
  evals:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.13"
      - name: Eval gate
        run: >
          python3 tools/eval-kit/scripts/run.py evals/traces.csv
          --feature "Quote drafting" --target 85 --out eval-run
          --seal evals/traces.seal.json --judge-scores evals/judge_scores.csv
          --fail-on blocking
      - name: Show the report
        if: always()
        run: cat eval-run/report.md >> "$GITHUB_STEP_SUMMARY"
```

The gate reads the same status the page prints and the project file stores, one rule on the 95% interval: meets target only when its low end clears the target, below target only when its high end is under it, otherwise not confirmed: too close to call. Pick one gate:

1. `--fail-on blocking` exits 2 when the version fails a held-out case the one before passed, or sits more than 10 points under target.
2. `--fail-on below-target` exits 2 only when the status is below target: the range's high end is under the target.
3. `--fail-on not-met` exits 2 unless the status is meets target: too close to call, below target, an unsealed holdout or an uncalibrated judge all fail it.

At an 80% target, 21 of 30 (70%, range 52.1% to 83.3%) is too close to call: it passes `blocking` and `below-target`, and fails `not-met`.

Exit codes: 0 passed the gate, 1 the report was refused (fix the data; nothing is written), 2 the gate failed (the report is written).

Pass `--seal` explicitly in CI. Without it, a first run would write a new seal in the runner and pass a holdout nobody committed.
