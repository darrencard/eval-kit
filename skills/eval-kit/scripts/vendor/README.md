# Vendored, unchanged

These files are copied byte for byte from the Product & Technology Leader Report at the commit in `PINS.json`, so eval-kit reads the landing brief, the vendors' cost exports and the style guide exactly as the Leader Report does. Never edit them here. To update: copy them again from a newer commit, then update the commit and hashes in `PINS.json`. A test checks every hash.

| File | Used for |
|---|---|
| `landing_brief.py` | Parsing the landing brief (the one format, never forked) |
| `from_ai_spend.py` | Reading Anthropic and OpenAI cost exports, to check trace costs against what the provider billed |
| `from_posthog.py` | Reading PostHog responses as they stand |
| `collect.py`, `convert.py` | What the two collectors import |
| `template.html` | The style guide's fonts and colour tokens, read at render time |
