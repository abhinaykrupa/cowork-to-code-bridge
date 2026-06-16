# Hermes + Claude Code Bridge Integration

## Problem

**You can't connect Hermes (or Open Claw) to your Claude Max subscription directly.**

As of April 4, 2026, Anthropic decoupled Claude Pro/Max subscription usage from third-party agent tools. Hermes integration now requires:
- Anthropic API key (billed at usage rates, not included in Max quota)
- OAuth but only on "extra usage" credits (not base Max allowance)
- Or use an alternative model (OpenAI, etc.)

This means Hermes agents run on separate billing, not your subscription, and lack Claude Code's local context (file access, shell, MCP servers, your repos).

## Solution: cowork-to-code-bridge

The bridge is a **file-based async queue** that lets any external agent (Hermes, daemons, cron jobs, CI/CD) escalate work to Claude Code running on your machine.

| Aspect | Hermes + API key | Hermes + Bridge |
|---|---|---|
| **Billing** | Usage-based API calls (separate from Max) | Uses your Claude Code subscription (no extra cost) |
| **Context** | Generic Claude API; no file/repo/shell access | Full Claude Code: your repos, shell, MCPs, files |
| **Auth** | Requires API key in Hermes config | Uses your authenticated Claude Code session (no secret) |
| **Speed** | Live API call (slow for complex tasks) | Async queue (Hermes doesn't block) |
| **Use case** | Quick, stateless queries | Complex debugging, code review, multi-step tasks |

## How It Works

### From Hermes (or any agent)

```python
# When Hermes detects an error that needs Claude Code debugging:
result = subprocess.run([
    "escalate_to_claude.sh",
    f"Debug why the API is returning 500 on /health. Logs at {log_path}. Fix the code and restart.",
    "--wait", "600"
], capture_output=True, text=True)

if result.returncode == 0:
    reply = json.loads(result.stdout)
    # Claude Code debugged and returned the fix
    apply_fix(reply["fix"])
    restart_service()
```

### What happens inside the bridge

1. **Escalation queued.** Hermes writes JSON to `~/.cowork-to-code-bridge/to_cowork/`
2. **Claude Code picks it up.** Next time a Cowork chat is open, the agent checks its inbox (Step 4 of the skill).
3. **Agent debugs.** Claude Code reads logs, edits code, restarts services, tests — full agent abilities.
4. **Result written back.** Agent writes reply JSON to `~/.cowork-to-code-bridge/cowork_results/`
5. **Hermes resumes.** The `escalate_to_claude.sh` script polls and returns the result.

**No network ports. No API keys. No separate billing.**

## Installation

The bridge is on PyPI and Homebrew:

```bash
# macOS
brew install abhinaykrupa/tap/cowork-to-code-bridge

# or, any OS (macOS/Linux/WSL2)
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash

# Then, once in Cowork chat:
Connect to my machine via the cowork-to-code bridge at ~/.cowork-to-code-bridge
```

Once the bridge is running, Hermes can call `escalate_to_claude.sh` without any further setup.

## Use Cases

### 1. Hermes + Complex Debugging

Hermes detects an anomaly in logs. Instead of making a blind guess with the API, it escalates to Claude Code:
- Claude Code reads the logs, digs into the code, reproduces the issue.
- Suggests a fix, edits the repo, runs tests.
- Returns the fixed code and test results.
- Hermes applies the fix and restarts the service.

### 2. Hermes + Multi-Step Workflows

Hermes orchestrates a release pipeline. At the "manual review" step, it escalates to Claude Code:
- "Review the diff, update the changelog, and tag a release."
- Claude Code does the work, returns the tag hash.
- Hermes picks up and pushes to GitHub.

### 3. CI/CD → Claude Code

GitHub Actions job fails. Instead of re-running the job 5 times, post the error to the bridge:
- Claude Code debugs the failure, suggests a fix, edits the workflow file.
- CI resumes with the fixed workflow.

## Comparison: API Key vs. Bridge

| Factor | API Key | Bridge |
|---|---|---|
| **Cost** | Per-token usage, separate from Max | Included in Max subscription |
| **Setup** | Paste key into Hermes config | Run install.sh (once) |
| **Secret handling** | Key lives in Hermes config (or CI env) | Bridge token in `~/.cowork-to-code-bridge/.env` (local only) |
| **Latency** | Live API call (100ms–1s) | Async queue (seconds to minutes, depends on Cowork availability) |
| **Context** | Generic Claude (no file/shell access) | Full Claude Code (your repos, shell, MCPs, debugger) |
| **Best for** | Quick, stateless tasks | Complex, context-rich debugging & review |

## Roadmap

The bridge currently supports:
- ✅ Async escalation from any agent to Claude Code
- ✅ Structured JSON requests + replies
- ✅ Idempotent, crash-resilient queue
- ✅ Token-authenticated
- ✅ Works on macOS, Linux, WSL2

Future work (not yet shipped):
- Sync (blocking) escalation mode for time-critical use cases
- MCP proxy (so Hermes can reach your local MCPs via the bridge)
- Rate limiting + quota per agent

## Links

- **GitHub:** [abhinaykrupa/cowork-to-code-bridge](https://github.com/abhinaykrupa/cowork-to-code-bridge)
- **Documentation:** [docs/RECIPES.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/RECIPES.md) (includes Hermes integration example)
- **PyPI:** [cowork-to-code-bridge](https://pypi.org/project/cowork-to-code-bridge/)

## Questions?

- **For integration questions:** Open an issue on [the bridge repo](https://github.com/abhinaykrupa/cowork-to-code-bridge/issues)
- **For Hermes-specific setup:** This pattern works with any Hermes agent that can call shell scripts

---

**TL;DR:** Hermes agents can now hand off complex tasks to Claude Code (with your Max subscription, no API keys) via a file-based bridge. No network ports, no new secrets, fully async. If you integrate this, the bridge repo can link back to you as a reference implementation.
