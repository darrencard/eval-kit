# Evals: Quote drafting

> Illustrative. Sample data for Acme, an invented company. No figure here is a real measurement.

**Status: landed.** Held-out pass rate 80% meets the 80% target on a sealed holdout.

Against the landing brief: The brief's metric, Quote draft acceptance rate, is not an eval figure. did-it-land judges it; these evals are the build check.

Version v1.4 passes 24 of 30 held-out cases (80%, 95% interval 62.7 to 90.5) [L4], against 90% on development [L5].
The interval's low end, 62.7%, is under the 80% target. More held-out cases would settle it.
It finished 143 of 200 production tasks with no person stepping in (71.5%, 95% interval 64.9 to 77.3) [L6].
Cost: cost not checked: run cost-budget-check.

## Promotion

v1.4 may replace v1.3: challenger gains 10 points on held-out cases with no new failure.

It newly passes 3 held-out case(s): q076, q077, q078.

Each rate sits inside the other's 95% interval, so read the gain as direction, not size. More held-out cases would measure it.

## By version

| Version | Run | Held-out pass | Development pass | Without a person | Cost per successful task |
|---|---|---|---|---|---|
| v1.3 | 2026-10-15 | 21/30 (70%) | 52/70 (74.3%) | 118/200 (59%) | not checked |
| v1.4 | 2026-11-15 | 24/30 (80%) | 63/70 (90%) | 143/200 (71.5%) | not checked |

## Failure modes

Clustered from development failures and production tasks that failed or needed a person. No categories were set in advance.

| Cluster | Shared terms | Traces | Share |
|---|---|---|---|
| fc1 | before, changed, edited | 42 | 66% |
| fc2 | finish, left, missed | 15 | 23% |
| fc3 | added, book, expansion | 5 | 8% |
| fc4 | callout, left, missing | 2 | 3% |

Read these before naming a cluster:

- fc1 `production:t0005`: estimator edited labour hours / Estimator changed labour hours before sending.
- fc1 `production:t0013`: estimator edited labour hours / Estimator changed labour hours before sending.
- fc2 `production:t0056`: quote scope missed the return visit / Scope left out the second visit to finish the job.
- fc2 `production:t0060`: quote scope missed the return visit / Scope left out the second visit to finish the job.
- fc3 `eval:q038`: Quote drafted: quote added part not listed in price book / Added expansion tank; no such line in price book.
- fc3 `eval:q054`: Quote drafted: quote added part not listed in price book / Added expansion tank; no such line in price book.
- fc4 `eval:q002`: Quote drafted: callout fee missing from quote total / Total left out the callout fee.
- fc4 `eval:q094`: Quote drafted: callout fee missing from quote total / Total left out the callout fee.

6 held-out failure(s) are counted above and not read, so the holdout stays sealed.

## Judge calibration

The judge agreed with the human verdict on 100% of 8 cases. False accepts: none. False rejects: none.

## What these figures support

- Say: the held-out pass rate for v1.4, with its case count. Quote autonomy only beside it.
- Do not say: a development pass rate as the headline, a gain without a promotion verdict that allows it, or a cause for any change.

## Warnings

- cost not checked: run cost-budget-check. No cost figure is printed until it writes the cost key.

## Ledger

| Row | Figure | Value | Basis | Source | Provenance |
|---|---|---|---|---|---|
| L1 | Held-out pass rate (v1.3) | 70% | 21 of 30 holdout eval rows passed; 95% interval 52.1 to 83.3 | quote-drafting.csv (sha256 ee43a12a2395) | Illustrative |
| L2 | Development pass rate (v1.3) | 74.3% | 52 of 70 development eval rows passed | quote-drafting.csv (sha256 ee43a12a2395) | Illustrative |
| L3 | Tasks finished without a person (v1.3) | 59% | 118 of 200 production rows succeeded with human_stepped_in false; 95% interval 52.1 to 65.6 | quote-drafting.csv (sha256 ee43a12a2395) | Illustrative |
| L4 | Held-out pass rate (v1.4) | 80% | 24 of 30 holdout eval rows passed; 95% interval 62.7 to 90.5 | quote-drafting.csv (sha256 ee43a12a2395) | Illustrative |
| L5 | Development pass rate (v1.4) | 90% | 63 of 70 development eval rows passed | quote-drafting.csv (sha256 ee43a12a2395) | Illustrative |
| L6 | Tasks finished without a person (v1.4) | 71.5% | 143 of 200 production rows succeeded with human_stepped_in false; 95% interval 64.9 to 77.3 | quote-drafting.csv (sha256 ee43a12a2395) | Illustrative |
