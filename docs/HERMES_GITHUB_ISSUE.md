# GitHub Issue Template: Post to Nous Research Hermes repo

## Issue Title
```
Escalate from Hermes to Claude Code subscription via file-based bridge (no API keys)
```

## Issue Body

### Problem

You can't connect Hermes directly to Claude Max/Pro subscription anymore (as of April 4, 2026). Current options:
- **API key:** Billed separately from subscription; loses local context (repos, shell, MCPs).
- **OAuth:** Only works on "extra usage" credits, not base allowance.
- **Alternative model:** Use OpenAI/Copilot instead of Claude.

This means Hermes agents either run on separate billing or lose Claude's capabilities.

### Solution

**cowork-to-code-bridge** — a file-based async queue that lets Hermes hand off complex tasks to Claude Code running on your machine, using your subscription with zero extra cost and zero API keys.

#### How it works

1. **Hermes detects an issue** (failed build, anomalous metrics, etc.)
2. **Hermes escalates** via `escalate_to_claude.sh "Debug X"` (writes JSON to local queue folder)
3. **Claude Code picks it up** from inbox when a Cowork chat is open
4. **Agent debugs/fixes** with full file/shell/MCP access
5. **Result written back** to reply folder
6. **Hermes resumes** with the fix applied

#### Example

```python
# In a Hermes agent
result = subprocess.run([
    "escalate_to_claude.sh",
    f"API health check failing. Fix /Users/me/projects/api/health.py and restart.",
    "--wait", "600"
], capture_output=True, text=True)

# Claude Code just debugged and fixed it; Hermes applies the result
```

#### Why this matters

| Metric | Hermes + API Key | Hermes + Bridge |
|---|---|---|
| Billing | Separate from subscription | Uses your Max quota (no extra cost) |
| Context | Generic Claude API | Full Claude Code (your repos, shell, MCPs) |
| Setup | Paste API key into config | `curl install.sh \| bash` (once) |
| Auth | API key in config/env (secret) | Bridge token local-only (secure) |
| Best for | Quick stateless queries | Complex debugging, code review, multi-step |

### Reference Implementation

The bridge is production-ready:
- ✅ Token-authenticated file-based queue
- ✅ Idempotent, crash-resilient (journal + markers)
- ✅ macOS (launchd), Linux (systemd/manual), WSL2
- ✅ PyPI + Homebrew
- ✅ Full test suite

**GitHub:** https://github.com/abhinaykrupa/cowork-to-code-bridge  
**Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/HERMES_PITCH.md  
**Installation:** One-liner; then agents can call `escalate_to_claude.sh`

### What we're proposing

1. **Link from Hermes docs** to the bridge as a recommended way to reach Claude Code subscription (vs. API key or alternatives).
2. **Add integration example** to Hermes docs if you adopt it (how to detect error → escalate → resume).
3. **We link back** to Hermes as a reference implementation (helps both repos gain visibility).

### No ask of Hermes repo

You don't have to maintain anything or add code to Hermes. The bridge is standalone and independent. We're just proposing that your docs mention it as an option for users who want to use Claude Code subscription with Hermes.

### Questions?

Open an issue on the bridge repo: https://github.com/abhinaykrupa/cowork-to-code-bridge/issues
