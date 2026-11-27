# Changelog

## 0.3.3, 2026-11-26

- README: install through the Landing Loop bundle (`/plugin marketplace add darrencard/landing-loop`, then `/plugin install eval-kit@landing-loop`), with the paste-in prompt kept for a standalone install.
- README: the repository is public, so the private-until-review notes are gone, and the loop is counted as eleven skills plus the Product & Technology Leader Report.
- README: one trademark line for Claude and Claude Code.
- No change to what the skill computes. The version in the sample record's `tool` field moves with the release.
- Fix after review: meets target now needs the 95% interval's low end to clear the target. A rate that meets it only as a point estimate reads `not confirmed: inside noise`, with the interval and the case count that would settle it, so 24 of 30 never reads as a precise 80%. The same rule applies against the brief's bar. A `--fail-on below-target` gate trips on it; `--fail-on blocking` does not. The Acme sample now reads not confirmed: inside noise.
- Fix after review: every entry script checks for Python 3.11 first and exits with a plain message; `examples/acme/sample.py` runs on a copy of the record and renames the result into place only after success, so a crash never drops the `evals` key.
- Fix after review: the HTML page is built on the vendored Leader Report template (its whole stylesheet, pinned at 366da9b in `vendor/VENDORED.json`, renamed from `PINS.json`, hash-tested), with the DACARD wordmark, a one-line answer, a five-line summary, the scorecard and detail under `<details>`. The Illustrative tag, check chips, selection and focus print in ink.
- Fix after review: SKILL.md description under 1,024 characters; `examples/acme/upstream/cost-budget-check.json` holds `brief.path` exactly as the landing-loop record does.
