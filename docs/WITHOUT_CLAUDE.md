# Using the bridge without Claude

The bridge is often described as "Cowork talks to Claude Code", because that is
the workflow it ships with. The mechanism underneath is narrower and more
boring than that, and it does not involve Claude at all:

> A daemon watches a directory. You drop a JSON file naming an allowlisted
> script. It runs the script on the host and writes the result back as JSON.

`run_claude.sh` is one of the bundled scripts. Twenty-three of the twenty-five
have nothing to do with Claude. Anything that can write a file into a directory
can drive the host — a cron job, a CI runner, a Python script, an agent
framework, an MCP client, a shell one-liner.

This page shows the bridge used with no Claude anywhere in the loop.

---

## The transport is a directory

```
$BRIDGE_ROOT/
  queue/       # you write   {"id", "script", "args", "timeout", "token"}
  results/     # daemon writes back {"exit_code", "stdout", "stderr", …}
  processed/   # consumed requests, kept for audit
  scripts/     # the allowlist — only these can run
```

There is no port, no socket, and no persistent connection. That is the whole
protocol. It survives the writer sleeping, the daemon restarting, and the
machine rebooting, because a file on disk does not care that either end went
away.

---

## From plain Python

No framework, no agent, no Claude:

```python
from cowork_to_code_bridge.client import call_remote, queue_task, poll_task_result

# Synchronous: block until the host finishes.
r = call_remote("scripts/port_check.sh", ["8080"], timeout=20)
print(r["exit_code"], r["stdout"])

# Asynchronous: queue it, poll when convenient.
task_id = queue_task("scripts/mac_disk.sh", [], timeout=20)["task_id"]
...
result = poll_task_result(task_id)
if result["status"] == "completed":
    print(result["exit_code"], result["stdout"])
```

`poll_task_result` is idempotent — polling a finished task keeps returning the
same result, so a caller that crashes mid-wait can pick up where it left off.

## From a shell

```bash
ID="$(date +%s)_$RANDOM"
cat > "$BRIDGE_ROOT/queue/$ID.json" <<JSON
{"id": "$ID", "script": "scripts/git_status.sh", "args": [],
 "timeout": 30, "token": "$BRIDGE_TOKEN"}
JSON

# Result appears in results/$ID.json
until [ -f "$BRIDGE_ROOT/results/$ID.json" ]; do sleep 1; done
cat "$BRIDGE_ROOT/results/$ID.json"
```

That is the entire client. Any language that can write JSON is a client.

---

## Adding your own scripts

The allowlist *is* the security boundary. A request names a path relative to
`scripts/`; anything outside it is rejected before execution, and the resolved
path is re-checked against the directory to block traversal.

```bash
cat > "$BRIDGE_ROOT/scripts/deploy_staging.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/src/myapp" && ./deploy.sh staging
SH
chmod +x "$BRIDGE_ROOT/scripts/deploy_staging.sh"
```

It is now callable as `scripts/deploy_staging.sh`. Nothing else changed, and no
process gained any capability it did not already have — the script runs as you,
on your machine, doing exactly what you wrote.

---

## What Claude actually adds

`run_claude.sh` hands a task to a Claude Code agent on the host, which is useful
when the work needs judgement ("fix whatever's failing") rather than a fixed
command. It is a script like any other: it can be deleted, replaced, or ignored,
and the bridge keeps working.

If you want the local-execution transport and none of the agent behaviour, the
above is the whole story.

## See also

- [Bundled scripts](RECIPES.md) — what ships in `scripts/` and what each does
- [Security model](../SECURITY.md) — the allowlist, tokens, and output redaction
- [External agent integration](EXTERNAL_AGENT_INTEGRATION.md) — MCP and framework wiring
