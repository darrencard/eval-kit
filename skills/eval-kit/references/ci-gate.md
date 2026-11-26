# Eval gate in CI

Run the report on every pull request that changes a prompt, model or pipeline, and fail the check when the new version is stalled. The report files are written before the exit, so the failed run can be read.

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
          --fail-on stalled
      - name: Show the report
        if: always()
        run: cat eval-run/report.md >> "$GITHUB_STEP_SUMMARY"
```

`--fail-on stalled` blocks a version that fails a held-out case the one before passed, or sits more than 10 points under target. Use `--fail-on watch` to also block an unsealed holdout, an uncalibrated judge or a pass rate under target. Exit codes: 0 passed the gate, 1 the report was refused (fix the data; nothing is written), 2 the gate failed (the report is written).

Pass `--seal` explicitly in CI. Without it, a first run would write a new seal in the runner and pass a holdout nobody committed.
