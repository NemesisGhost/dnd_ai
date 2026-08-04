"""Wait for a GitHub Actions run to finish and report only PASS/FAIL.

Ad hoc CI polling during the Phase 5 exit reviews printed one status line
per poll (mostly repeated "in_progress None") and, on completion, always
fetched every job/step's name and conclusion even when the run was green —
detail that only matters when something failed. This script fixes both: it
prints a status line only when the status actually changes, and it fetches
per-job/per-step detail only when the run's conclusion is not "success", and
even then prints only the steps that did not succeed.

Usage:
  uv run python scripts/wait_for_ci.py                     # current HEAD sha, any workflow
  uv run python scripts/wait_for_ci.py --sha <sha>
  uv run python scripts/wait_for_ci.py --run-id <id>        # skip lookup, poll this run directly
  uv run python scripts/wait_for_ci.py --interval 20 --timeout 1800

Exit code is 0 if the run's conclusion is "success", 1 otherwise (including
timeout or lookup failure). Prints one final line either way:
  PASS: <workflow name> run <id> for <sha> - <html_url>
  FAIL: <workflow name> run <id> for <sha> - <html_url>
followed by the non-passing job/step detail when it failed.

Needs a GitHub token: GITHUB_TOKEN or GH_TOKEN from the environment if set,
otherwise the credential stored for github.com via `git credential fill`
(the same source used ad hoc during the Phase 5 reviews, since the `gh` CLI
is not installed in this environment). Repository owner/name are read from
the `origin` remote.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def _resolve_token() -> str:
    import os

    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]

    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line[len("password=") :]
    raise RuntimeError(
        "No GitHub token found: set GITHUB_TOKEN/GH_TOKEN or configure a git credential for github.com"
    )


def _resolve_repo() -> tuple[str, str]:
    url = _run(["git", "remote", "get-url", "origin"])
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if not match:
        raise RuntimeError(f"Could not parse owner/repo from origin remote: {url}")
    return match.group(1), match.group(2)


def _get(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {exc.code} for {url}: {body}") from exc


def _resolve_run_id(owner: str, repo: str, sha: str, token: str) -> int:
    data = _get(f"{API_ROOT}/repos/{owner}/{repo}/actions/runs?head_sha={sha}", token)
    runs = data.get("workflow_runs", [])
    if not runs:
        raise RuntimeError(f"No workflow runs found for commit {sha}")
    return runs[0]["id"]


_NOISE_CONCLUSIONS = (None, "success", "skipped")


def _print_failure_detail(owner: str, repo: str, run_id: int, token: str) -> None:
    """Prints only the job(s)/step(s) that actually failed — not steps GitHub
    marked "skipped" as downstream fallout from that failure, which name no
    root cause of their own."""
    data = _get(f"{API_ROOT}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs", token)
    for job in data.get("jobs", []):
        if job["conclusion"] in _NOISE_CONCLUSIONS:
            continue
        print(f"  {job['name']}: {job['conclusion']}")
        for step in job.get("steps", []):
            if step["conclusion"] not in _NOISE_CONCLUSIONS:
                print(f"    {step['name']}: {step['conclusion']}")


def wait_for_run(
    owner: str,
    repo: str,
    run_id: int,
    token: str,
    interval_seconds: float,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None
    data: dict = {}

    while True:
        data = _get(f"{API_ROOT}/repos/{owner}/{repo}/actions/runs/{run_id}", token)
        status = data["status"]
        if status != last_status:
            print(status)
            last_status = status
        if status == "completed":
            break
        if time.monotonic() >= deadline:
            print(f"TIMEOUT waiting for run {run_id} after {timeout_seconds:.0f}s", file=sys.stderr)
            return False
        time.sleep(interval_seconds)

    conclusion = data.get("conclusion")
    name = data.get("name", "CI")
    sha = data.get("head_sha", "?")[:7]
    html_url = data.get("html_url", "")
    label = "PASS" if conclusion == "success" else "FAIL"
    print(f"{label}: {name} run {run_id} for {sha} - {html_url}")

    if conclusion != "success":
        _print_failure_detail(owner, repo, run_id, token)

    return conclusion == "success"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sha", default=None, help="Commit SHA to look up a run for (default: current HEAD)"
    )
    parser.add_argument(
        "--run-id", type=int, default=None, help="Poll this run id directly, skipping lookup"
    )
    parser.add_argument(
        "--interval", type=float, default=25.0, help="Seconds between polls (default: 25)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Give up after this many seconds (default: 1800)",
    )
    args = parser.parse_args()

    try:
        token = _resolve_token()
        owner, repo = _resolve_repo()
        run_id = args.run_id
        if run_id is None:
            sha = args.sha or _run(["git", "rev-parse", "HEAD"])
            run_id = _resolve_run_id(owner, repo, sha, token)
        success = wait_for_run(owner, repo, run_id, token, args.interval, args.timeout)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
