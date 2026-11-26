# Live data

Read traces from the tools that already hold them. `scripts/from_traces.py traces` turns each saved response into the traces file; the CSV columns in `trace-schema.md` stay the fallback. Every reader reads files you saved and makes no network call. A response missing a field it needs is refused with what is missing.

| Source | What to save | Becomes |
|---|---|---|
| OpenAI Evals | `GET /v1/evals/{eval_id}/runs/{run_id}/output_items`, one file per run, with `--version` per file | Eval rows. Case id is the dataset item's `id` (or its index), so a case keeps its id across runs. Passes when every grader passed. `split` comes from the dataset item when it has one |
| Langfuse | `GET /api/public/traces` and `GET /api/public/scores` | Production rows. `succeeded` and `human_stepped_in` are two scores you record on each trace (rename with `--success-score`, `--human-score`); cost is `totalCost` |
| PostHog LLM analytics | The result of the HogQL query below | Production rows |
| Anthropic, OpenAI cost reports | The Admin API cost report and `/v1/organization/costs`, read by the Leader Report's own `from_ai_spend.py` (vendored) | `from_traces.py spend`: provider-billed spend in a window. `report.py --spend` checks trace costs against it, outside the Landing Loop |

## PostHog query

Run in PostHog's SQL editor or the query API, then save the JSON response. Name the columns exactly as below; the reader refuses any other names.

```sql
SELECT
  properties.$ai_trace_id AS id,
  properties.prompt_version AS version,
  toDate(min(timestamp)) AS run_at,
  max(properties.task_succeeded = true) AS succeeded,
  max(properties.human_edited = true) AS human_stepped_in,
  sum(toFloat(properties.$ai_total_cost_usd)) AS cost_usd,
  any(properties.$ai_output_choices) AS output
FROM events
WHERE event = '$ai_generation' AND timestamp >= '2026-11-01'
GROUP BY id, version
```

`prompt_version`, `task_succeeded` and `human_edited` are properties your app sends; use your own names in the query and keep the aliases.

## Tested against

The readers are tested on responses built from each vendor's documented shape, not yet against a live account. If yours differs, the reader names the missing field; open an issue with a redacted sample.
