# Traces CSV or JSONL

One file per AI feature, as CSV or as JSONL (one JSON object per line; nested keys read as dotted columns such as `metadata.version`). Map other column names with `--map SCHEMA=YOURS`. One row per eval case result or production task, for every version you want compared. Column names are lower case. Extra columns are ignored.

| Column | Rows | Required | Meaning |
|---|---|---|---|
| `kind` | all | Yes | `eval` (a case from the eval set) or `production` (a real task). Also read: test, offline, evaluation as eval; prod, live, online as production |
| `id` | all | Yes | Case id for eval rows (the same case keeps the same id across versions); task id for production rows |
| `version` | all | Yes | The prompt, model or pipeline version that produced the row |
| `run_at` | all | Yes | YYYY-MM-DD. A version's run date is its latest row |
| `split` | eval | Yes | `development` or `holdout`. A case never changes split |
| `passed` | eval | One of | `true` or `false`, a person's label. Wins over `score` |
| `score` | eval | One of | A judge's score, 0 to 1. A pass from 0.6 |
| `succeeded` | production | Yes | `true` when the task ended in the right result |
| `human_stepped_in` | production | Yes | `true` when a person edited, approved by hand or took over |
| `cost_usd` | production | No | Model and tool cost for the task. Kept for cost-budget-check; eval-kit computes no cost from it |
| `input` | all | No | What the feature was given. Part of the seal for held-out cases |
| `output` | all | No | What it produced. Read for failure clusters |
| `note` | all | No | A reviewer's note on what went wrong. Read for failure clusters |

## The figures

| Figure | Computed as |
|---|---|
| Held-out pass rate | holdout eval rows that pass, over holdout eval rows, latest version |
| Development pass rate | the same on development rows, shown beside the held-out rate, never as the headline |
| Tasks finished without a person (autonomy) | production rows with `succeeded` true and `human_stepped_in` false, over production rows |
| Cost per task | Not computed. Cited from the loop record's `cost` key (cost-budget-check owns it), or "cost not checked: run cost-budget-check" |

`evals.csv` carries these as the Leader Report's `evals` columns: `cases` and `passed` (held-out), `tasks` and `tasks_unassisted` (production), and `cost_per_task` only when cited from the cost key (empty otherwise).

The seal hashes ids and inputs with 32-bit FNV-1a over UTF-8 bytes. For ASCII ids and inputs it matches Throughline's `holdout.ts`, which hashes UTF-16 code units.
