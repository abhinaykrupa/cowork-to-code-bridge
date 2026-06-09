# Cowork Recipes

Copy-paste these into a Cowork chat **after** the bridge is connected (`BRIDGE LIVE`).
Swap `/Users/me/...` paths for your machine. Want more? Ask Cowork to run
`list_scripts.sh` — it lists every script the bridge can call, with descriptions.

---

## Build and run a FastAPI app, then hit `/health`

**Say this in Cowork:**

```text
In /Users/me/projects/myapi, scaffold a small FastAPI app with a /health route,
install dependencies, start the server, and confirm /health returns 200. Show me
the curl command and output.
```

**What the bridge does:**

- Hands the task to **Claude Code on your machine** via `run_claude.sh` — a full
  local agent that can create files, run pip, start the server, and curl `/health`.
- Streams progress back to Cowork as the agent works (installing, running, testing).
- Uses an idempotency key under the hood so a dropped connection does not run the
  whole build twice.

---

## Find and fix the failing test in my repo, then commit

**Say this in Cowork:**

```text
In /Users/me/projects/myapp, run the test suite, find the first failing test, fix
it, re-run tests to confirm green, then commit with a clear message. Show me the
diff before you commit.
```

**What the bridge does:**

- Delegates to `run_claude.sh` — Claude Code runs your project's test command,
  edits code, and can `git commit` when you ask it to.
- Cowork sees stdout from the agent (which tests failed, what changed, commit hash).
- Ask to review the diff first if you want a human gate before the commit lands.

---

## What's eating my disk? Clean up the top offender after I confirm

**Say this in Cowork:**

```text
What's eating disk space in my home folder? Show me the biggest offenders first.
Do not delete anything until I confirm which path to clean up.
```

**What the bridge does:**

- First pass: runs **`disk_hogs.sh`** — a fixed, read-only scan of the largest
  files and folders (no agent, fast).
- When you reply with something like *"yes, clean up ~/Downloads/old-backups"*,
  Cowork hands a follow-up task to **`run_claude.sh`** to remove only what you
  approved.
- Nothing is deleted until you explicitly confirm — the bridge does not auto-purge.

---

## Bump the version, tag a release, and push

**Say this in Cowork:**

```text
In /Users/me/projects/mylib, bump the patch version in pyproject.toml (or
package.json), update the changelog, create an annotated git tag, and push to
origin. Show me every file you changed before pushing.
```

**What the bridge does:**

- Uses `run_claude.sh` so Claude Code edits version files, commits, tags, and
  runs `git push` on your machine.
- You can narrow scope ("bump only, don't push yet") or ask to see the diff first.
- Real git operations on your repo — review the summary Cowork returns before
  you say "looks good, push."

---

## Spin up the dev server and screenshot the homepage

**Say this in Cowork:**

```text
In /Users/me/projects/mywebapp, install deps, start the dev server, wait until
the homepage loads, take a screenshot, and tell me the URL and where you saved
the image.
```

**What the bridge does:**

- `run_claude.sh` runs Claude Code locally — it can `npm run dev` (or your stack's
  command), hit the homepage, and capture a screenshot (e.g. macOS `screencapture`).
- Cowork relays the URL, file path, and any errors (port in use, missing deps).
- Pair with the **open localhost** recipe below if you also want the page opened in
  your browser.

---

## Quick machine health snapshot

**Say this in Cowork:**

```text
Give me a quick health snapshot of my Mac — CPU, memory, disk, and what's using
the most resources.
```

**What the bridge does:**

- Runs **`mac_health.sh`** directly — no Claude Code agent, no file edits.
- Returns a read-only snapshot in seconds (CPU, RAM, disk, battery, top processes).
- Good first ask when you want facts before delegating a bigger task.

---

## What Docker containers are running?

**Say this in Cowork:**

```text
Show me the Docker containers currently running on my machine.
```

**What the bridge does:**

- Calls **`docker_ps.sh`** — lists running containers via your local Docker CLI.
- Fixed script, read-only; fails clearly if Docker is not installed or not running.
- No agent needed for this quick check.

---

## Git status in my repo

**Say this in Cowork:**

```text
What's the git status in /Users/me/projects/myrepo? Short summary only.
```

**What the bridge does:**

- Runs **`git_status.sh`** with your repo path — `git status --short --branch`.
- Fast, read-only; no commits or checkouts.
- Useful before asking Claude Code to fix tests or cut a release in the same repo.

---

## Is anything listening on port 3000?

**Say this in Cowork:**

```text
Check what process is listening on port 3000 on my machine.
```

**What the bridge does:**

- Uses **`port_check.sh`** — reports which process (if any) owns that TCP port.
- Read-only; handy before starting a dev server or debugging "address already in use."
- No agent required.

---

## Open localhost in my browser after the server is up

**Say this in Cowork:**

```text
Open http://localhost:3000 in my default browser.
```

**What the bridge does:**

- Runs **`open_browser.sh`** — opens an `http://` or `https://` URL (or bare
  `localhost:PORT`) in your system browser.
- Fixed script; does not start the server — combine with the dev-server recipe if
  you need both.
- Rejects unsafe URLs (`file://`, bare paths) by design.
