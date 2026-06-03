# Cowork Recipes

These examples show concrete requests you can paste into a connected Cowork chat.
Each recipe lists the bridge script that should run on your machine and the shape
of the arguments it needs.

Before using these, connect Cowork to the bridge folder and confirm the bridge is
live as described in the README.

## Build and test a Python project on my machine

Say this in Cowork:

```text
Have Claude Code work in /Users/me/projects/api, install the project dependencies,
run the test suite, and summarize any failures.
```

Bridge script:

```python
call_remote(
    script="scripts/run_claude.sh",
    args=[
        "Install dependencies, run the test suite, and summarize any failures.",
        "/Users/me/projects/api",
    ],
    timeout=600,
    idempotency_key="api-test-run-2026-06-04",
)
```

Use `run_claude.sh` when the task needs judgment, code edits, dependency setup,
or follow-up debugging.

## Run my Docker containers and show me what is up

Say this in Cowork:

```text
Show me the Docker containers currently running on my machine.
```

Bridge script:

```python
call_remote(
    script="scripts/docker_ps.sh",
    timeout=30,
)
```

This is a fixed, read-only check. It does not need the Claude Code agent.

## Check git status and draft a changelog entry

Say this in Cowork:

```text
Check the git status in /Users/me/projects/site, then have Claude Code draft a
short changelog entry from the current diff.
```

Bridge scripts:

```python
call_remote(
    script="scripts/git_status.sh",
    args=["/Users/me/projects/site"],
    timeout=30,
)

call_remote(
    script="scripts/run_claude.sh",
    args=[
        "Review the current git diff and draft a concise changelog entry. Do not commit.",
        "/Users/me/projects/site",
    ],
    timeout=300,
    idempotency_key="site-changelog-draft-2026-06-04",
)
```

Use the fixed `git_status.sh` script for the snapshot, then `run_claude.sh` for
the writing task.

## Find disk space problems

Say this in Cowork:

```text
Check disk usage for /Users/me and tell me whether anything looks close to full.
```

Bridge script:

```python
call_remote(
    script="scripts/mac_disk.sh",
    args=["/Users/me"],
    timeout=30,
)
```

For a broader investigation, follow up with a `run_claude.sh` task that asks the
agent to inspect a specific project or directory.

## Check whether my app is listening on a port

Say this in Cowork:

```text
Check what process is listening on port 3000.
```

Bridge script:

```python
call_remote(
    script="scripts/port_check.sh",
    args=["3000"],
    timeout=30,
)
```

This works well before asking Claude Code to start, stop, or debug a local dev
server.

## Run my test suite and fix the first failure

Say this in Cowork:

```text
Have Claude Code run tests in /Users/me/projects/cli-tool, fix the first failing
test only, and report the exact command it used.
```

Bridge script:

```python
call_remote(
    script="scripts/run_claude.sh",
    args=[
        "Run the tests, fix the first failing test only, and report the exact command used.",
        "/Users/me/projects/cli-tool",
    ],
    timeout=900,
    idempotency_key="cli-tool-first-test-fix-2026-06-04",
)
```

Keep the prompt narrow when the agent can edit files. A focused first-failure
task is easier to review than a broad "fix everything" request.

## Check outdated packages

Say this in Cowork:

```text
List outdated packages on my machine.
```

Bridge script:

```python
call_remote(
    script="scripts/pkg_outdated.sh",
    timeout=60,
)
```

This script detects common package managers such as Homebrew, apt, dnf, yum, and
pacman.
