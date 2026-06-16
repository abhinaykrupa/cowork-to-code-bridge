# GitHub Issue Template: Post to Open Claw repo

## Issue Title
```
Reach Claude Code subscription from Open Claw via file-based bridge (no tokens)
```

## Issue Body

### Problem

Open Claw can no longer reuse Claude CLI auth to tap your Claude Max/Pro subscription (as of April 4, 2026). Current paths:
- **Agent SDK:** Configure as API provider; billed separately from subscription.
- **Claude CLI proxy:** Workarounds are fragile and may violate ToS.

Open Claw agents either lose subscription access or end up on separate billing.

### Solution

**cowork-to-code-bridge** — a file-based async queue that lets Open Claw hand off work to Claude Code running on your machine, using your subscription with zero tokens and zero API keys.

#### How it works

1. **Open Claw detects a task** that needs local execution (run code, debug, review)
2. **Open Claw writes to bridge queue** via `request_cowork.sh` or `escalate_to_claude.sh`
3. **Claude Code picks it up** from inbox when a Cowork chat is open
4. **Agent executes locally** with full file/shell/MCP access
5. **Result written back** to reply folder
6. **Open Claw resumes** with the output

#### Why this matters

| Need | Open Claw + API Key | Open Claw + Bridge |
|---|---|---|
| **Cost** | Separate from Max quota | Included in Max (no extra billing) |
| **Local execution** | No (cloud-based) | Yes (your machine, full shell/file access) |
| **Setup** | Configure API key provider | `curl install.sh \| bash` (once) |
| **Auth** | API key in config (secret mgmt required) | Bridge token local-only (secure) |
| **Best for** | Cloud-only tasks | Any task that needs local context |

#### Example

```python
# In an Open Claw workflow
if task_needs_local_execution:
    result = subprocess.run([
        "request_cowork.sh",
        f"Build and test the project in {repo_path}",
        "--wait", "900"
    ], capture_output=True, text=True)
    
    # Claude Code just ran the build on your machine
    assert_build_passed(result.stdout)
```

### Reference Implementation

The bridge is production-ready and open-source:
- ✅ Token-authenticated file-based queue
- ✅ Idempotent, crash-resilient (journal + markers)
- ✅ macOS (launchd), Linux (systemd/manual), WSL2
- ✅ PyPI + Homebrew
- ✅ Full test suite

**GitHub:** https://github.com/abhinaykrupa/cowork-to-code-bridge  
**PyPI:** https://pypi.org/project/cowork-to-code-bridge/  
**Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/RECIPES.md

### What we're proposing

1. **Mention in Open Claw docs** as an alternative to API keys for reaching Claude Code on your machine.
2. **Link to reference implementation** (bridge repo).
3. **We link back** to Open Claw as an example use case (mutual visibility).

### No ask of Open Claw repo

The bridge is completely standalone. You don't need to add code or maintain anything. We're suggesting a docs link for users who want to keep their Claude Max subscription separate from Open Claw billing.

### Questions?

Open an issue on the bridge repo: https://github.com/abhinaykrupa/cowork-to-code-bridge/issues
