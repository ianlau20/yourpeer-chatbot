# Docs Drift Checker

`scripts/check_docs.py` validates that facts hardcoded in markdown files still match the actual codebase. It can auto-fix test counts and exits with a non-zero code if drift is detected, so it can run in CI.

---

## Why This Exists

Documentation in this project contains hardcoded numbers, model IDs, env var names, and file paths that drift silently when the code changes. We found test counts wrong in three places (TESTING.md said 381, README.md said 379, actual was 444), a model ID that didn't exist in the API (`claude-sonnet-4-6-20260217` caused every message to show crisis resources), and references to `GEMINI_API_KEY` in docs months after Gemini was removed.

None of these were caught by tests. This script exists so they're caught before they reach users or confuse a new engineer reading the docs.

---

## What It Checks

| Check | What It Validates |
|---|---|
| **Test counts** | Total test count in TESTING.md and README.md, plus per-file counts in TESTING.md (e.g. `### test_chatbot.py — 50 tests`), compared against actual `def test_*` function counts in each file. |
| **Model IDs** | Model ID strings in README.md, DEPLOY.md, and CRISIS_DETECTION.md compared against the `*_MODEL` constants in `backend/app/llm/claude_client.py`. Catches outdated or nonexistent model IDs. |
| **Env vars** | Env vars documented in DEPLOY.md verified against `render.yaml`. Flags vars that are documented but don't exist in the deploy config, and flags any lingering references to removed vars (e.g. `GEMINI_API_KEY`). |
| **File references** | Backtick file paths in all markdown files (e.g. `` `tests/test_chatbot.py` ``) verified to exist on disk. Catches references to deleted or renamed files. |
| **Internal links** | Markdown links like `[text](relative/path)` verified to resolve. Catches broken links to other docs or source files after renames or moves. |
| **Line number refs** | Flags any markdown link containing `#L<number>` anchors. These break every time the target file is edited — even adding a blank line shifts all subsequent line numbers. Recommends linking to function names or section headers instead. |
| **Code block commands** | Shell commands inside fenced code blocks (e.g. `python tests/test_foo.py`) verified that the referenced file exists. Catches stale setup instructions. |
| **API routes** | Routes documented in backtick format (e.g. `` `/api/admin/stats` ``) cross-checked against actual FastAPI route decorators. |
| **Dependency versions** | Version numbers mentioned in SETUP.md and DEPLOY.md compared against the versions set in `render.yaml`. Catches docs that say Node 18 when render.yaml deploys Node 24. |

---

## Usage

**Report only** — show drift without changing anything:

```
python scripts/check_docs.py
```

**Auto-fix** — fix test counts automatically, report the rest:

```
python scripts/check_docs.py --fix
```

**In CI** — exits 0 if clean, exits 1 if drift detected:

```yaml
# Example GitHub Actions step
- name: Check docs drift
  run: python scripts/check_docs.py
```

---

## Example Output

```
Checking docs against codebase...

--- Test counts ---
  DRIFT: TESTING.md — says 381 total tests, actual 444
  DRIFT: TESTING.md — test_chatbot.py: says 47, actual 50
  DRIFT: README.md — says 379 unit tests, actual 444

--- Model IDs ---

--- Environment variables ---

--- File references ---

==================================================
3 issue(s) found — review manually or re-run with --fix
```

With `--fix`:

```
  DRIFT: TESTING.md — says 381 total tests, actual 444
  FIXED: TESTING.md — total count 381 → 444
  ...
All issues auto-fixed.
```

---

## What It Can Auto-Fix

Only test counts — these are purely mechanical (count functions, update the number). Model IDs, env vars, and file references require human judgment and are reported but not auto-fixed.

---

## When to Run

Run `check_docs.py` after any of these changes:

- Adding, removing, or renaming test functions
- Changing model constants in `claude_client.py`
- Adding or removing env vars from `render.yaml`
- Renaming or deleting source files referenced in docs
- Refactoring code that shifts line numbers (the checker will flag `#L` anchors)
- Changing Node.js or Python version requirements
- Adding or removing API routes

The script has no dependencies beyond the Python standard library and runs in under a second.
