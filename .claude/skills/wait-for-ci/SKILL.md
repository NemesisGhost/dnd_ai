---
name: wait-for-ci
description: Poll a GitHub Actions run to completion and report only pass/fail, fetching per-job/per-step detail only when the run actually failed.
---

# Wait for CI

Use this instead of hand-rolling a `curl`/GitHub-API polling loop when a
commit has been pushed and its CI run needs to be confirmed green before
reporting a task done, opening/merging a PR, or closing a phase-exit review
(this repo's convention is to never declare something done before a green
pushed-head CI run — see docs/PLAN.md §23.0–23.1).

Invoke via Bash:

```
uv run python scripts/wait_for_ci.py                # current HEAD's most recent run
uv run python scripts/wait_for_ci.py --sha <sha>     # a specific commit
uv run python scripts/wait_for_ci.py --run-id <id>   # a known run id, skip lookup
```

It blocks until the run completes, printing a status line only when the
status actually changes (not once per poll), then one final `PASS: ...` or
`FAIL: ...` line with the run's `html_url`. If the run failed, it
automatically fetches and prints just the non-passing job(s)/step(s) —
don't separately call the GitHub API or `curl` the `/jobs` endpoint to get
that detail; it's already included when relevant, and omitted (to save
context) when the run passed.

Exit code is 0 for `success`, 1 otherwise. This can be a long wait — run it
in the background (`run_in_background: true`) if there's other work to do
meanwhile, and rely on the task-completion notification rather than polling
the output file yourself.

Requires `GITHUB_TOKEN`/`GH_TOKEN` in the environment, or a git credential
stored for `github.com` (via `git credential fill`) — this repo doesn't have
the `gh` CLI installed, so this script is the established credential path.
