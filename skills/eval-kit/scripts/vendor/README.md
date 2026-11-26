# Vendored, unchanged

These files are copied byte for byte from the Product & Technology Leader Report at the commit in `PINS.json`, so eval-kit reads the landing brief, PostHog responses and the style guide exactly as the Leader Report does. Never edit them here. To update: copy them again from a newer commit, then update the commit and hashes in `PINS.json`. A test checks every hash.

| File | Used for |
|---|---|
| `landing_brief.py` | Parsing the landing brief (the one format, never forked) |
| `from_posthog.py` | Reading PostHog responses as they stand |
| `collect.py` | What `from_posthog.py` imports |
| `template.html` | The style guide's fonts and colour tokens, read at render time |
