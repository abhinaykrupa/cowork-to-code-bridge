# Multi-Framework Outreach Templates

## Master Template (Adapt per Framework)

### For LangChain / LangGraph / AutoGen / n8n / Dify / Langflow

**Title:**
```
Integration: MCP provider for Claude Code subscription — local execution without API keys or separate billing
```

**Body:**
```markdown
## Problem

Multi-agent orchestration frameworks (LangChain, LangGraph, AutoGen, Dify, Langflow, n8n) users want to delegate code-heavy work to Claude Max/Pro without:
- **Separate API billing** (costs money outside existing subscription)
- **Losing local context** (no access to user's repos, shell, MCPs, local files)
- **Complex credential management** (API keys, separate quotas, rate limits)

This is especially painful for workflows that need real execution: testing, building, debugging, deploying, running analytics.

## Solution: cowork-to-code-bridge as MCP Provider

**cowork-to-code-bridge** is a lightweight, production-ready daemon that exposes Claude Code (running on the user's machine) as an MCP provider. Multi-agent workflows can now escalate code-heavy work directly—no API keys, no separate billing, full access to local context.

### Real Use Cases

| Use Case | Before (API Key) | After (MCP Bridge) |
|---|---|---|
| **CrewAI orchestrates debugging** | Uses Claude API (costs $$) | Uses user's Max subscription (free) |
| **LangGraph delegates test writing** | API key + rate limits | Local execution + full repo context |
| **AutoGen multi-turn coding task** | Cloud only (no shell) | Full shell access, local env |
| **n8n workflow triggers code fix** | Slow API calls | Instant local execution |
| **Dify agent builds scripts** | Limited to API constraints | Access to user's full machine |

### How It Works

**MCP Configuration (any framework):**
```json
{
  "providers": {
    "claude-code-bridge": {
      "type": "mcp",
      "command": "cowork-to-code-bridge-mcp",
      "args": ["--stdio"],
      "env": {
        "BRIDGE_ROOT": "$HOME/.cowork-to-code-bridge"
      }
    }
  }
}
```

**Agent Code (pseudocode):**
```python
# Orchestrate work from any framework
response = framework.escalate(
    tool="escalate_to_claude",
    request="Build and test the feature, report results",
    wait_seconds=1800
)
# Returns: {"status": "completed", "result": {...}}
```

### Bridge Strengths

- ✅ **Zero network ports** — file-based queue, no inbound/outbound listeners
- ✅ **Token-authenticated** — HMAC-based, same security as existing bridges
- ✅ **Lightweight** — <1MB, minimal dependencies
- ✅ **Idempotent + crash-safe** — request deduplication, in-flight recovery
- ✅ **Multiplatform** — macOS (launchd), Linux (systemd), WSL2
- ✅ **MCP standard** — JSONRPC 2.0, widely adopted

### Available MCP Tools

1. **escalate_to_claude** — Hand a task to Claude Code, get structured result asynchronously
2. **run_script** — Execute whitelisted scripts directly (health checks, repo inspections, etc.)
3. **list_bridge_scripts** — Discover available scripts

## Reference Implementation

- **Production-ready:** 570 lines of MCP server code + 9 unit tests + comprehensive docs
- **Battle-tested:** Uses same queue/idempotency logic as existing production bridge
- **Validated:** All sanity checks pass; no breaking changes to existing functionality
- **Documented:** MCP spec, config examples, security model, integration guide

**GitHub:** https://github.com/abhinaykrupa/cowork-to-code-bridge  
**MCP Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/MCP_SERVER_IMPLEMENTATION.md  
**Integration Guide:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/EXTERNAL_AGENT_INTEGRATION.md

## Why This Matters for [FRAMEWORK]

[CUSTOM PER FRAMEWORK — see variants below]

## What We're Proposing

1. **Mention in [FRAMEWORK] docs** as an option for users wanting Claude Code backend
2. **Link to reference implementation** (we maintain it fully)
3. **Mutual visibility** — we link back to [FRAMEWORK] as an integration example

## No Maintenance Ask

The bridge is completely self-contained. No code changes needed in [FRAMEWORK], no maintenance obligations for you. We're just asking that your docs mention this as an option for users who want local Claude Code execution without API keys.

---

**Try it now:**
```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
cowork-to-code-bridge-mcp --stdio  # Start MCP server
```
```

---

## Framework-Specific Variants

### LangChain / LangGraph

**Title:** "Integration: MCP provider for Claude Code in LangChain/LangGraph workflows — local execution, zero API billing"

**Why This Matters for LangChain/LangGraph:**
LangChain and LangGraph users orchestrating multi-agent workflows often need to delegate complex coding tasks (test writing, debugging, building) but can't justify separate Claude API costs. This bridge solves that: use Claude Code subscription that users already have, access full local context (repos, shell, MCPs), no extra billing. Especially valuable for LangGraph's state-machine workflows where escalation to a powerful local model is a natural pattern.

---

### AutoGen (Microsoft)

**Title:** "Integration: MCP provider for Claude Code in AutoGen conversations — local execution, no separate API billing"

**Why This Matters for AutoGen:**
AutoGen is designed for multi-agent conversations and task delegation. Users want to bring Claude Code into that conversation without managing separate API keys and billing. This bridge lets AutoGen agents escalate to Claude Code running locally, with full access to the agent's environment (shell, repos, MCPs). Especially powerful for AutoGen's code executor and user proxy patterns.

---

### Dify / Langflow / n8n

**Title:** "Integration: MCP provider for Claude Code workflows — local execution, no API keys"

**Why This Matters for Dify/Langflow/n8n:**
Low-code/no-code workflow platforms need reliable, secure local execution for code-heavy steps (testing, building, debugging, deployment). This bridge provides exactly that: Claude Code runs on the user's machine, no API keys to manage, no separate billing, full local context. Especially valuable for Dify (production workflows) and n8n (automation pipelines) where local execution is a core requirement.

---

### CrewAI Examples

**Title:** "Example: Using cowork-to-code-bridge MCP for local Claude Code execution in CrewAI workflows"

**Body (adapted for examples repo):**

This would be a practical example showing CrewAI orchestrating a coding task (e.g., "Build a feature, write tests, deploy it") with local Claude Code escalation instead of separate API keys.

---

## Posting Strategy

### Tier 1 (Do First - Highest Impact)
1. CrewAI (core) — largest multi-agent user base
2. LangGraph — graph-native agents (growing ecosystem)
3. LangChain — massive user base, tons of agent use cases
4. AutoGen — Microsoft backing, active community
5. n8n — automation + agents (local execution is core need)

### Tier 2 (Do Second - High Visibility)
6. Dify — production workflows (needs local exec)
7. Langflow — low-code agent designer
8. CrewAI Examples — reference implementations

### Tier 3 (Do Third - Curated Lists)
9. awesome-mcp-servers — add bridge to MCP curated list
10. awesome-mcp-clients — mention as compatible client
11. awesome-ai-agents — visibility in agent ecosystem
12. ai-agents / ai-agent / autonomous-agents topics

---

## Tracking

| Repo | Tier | Status | Issue # | Date |
|---|---|---|---|---|
| CrewAI | 1 | ⏳ Ready | — | — |
| LangGraph | 1 | ⏳ Ready | — | — |
| LangChain | 1 | ⏳ Ready | — | — |
| AutoGen | 1 | ⏳ Ready | — | — |
| n8n | 1 | ⏳ Ready | — | — |
| Dify | 2 | ⏳ Ready | — | — |
| Langflow | 2 | ⏳ Ready | — | — |
| CrewAI Examples | 2 | ⏳ Ready | — | — |
| awesome-mcp-servers | 3 | ⏳ Ready | — | — |
| awesome-mcp-clients | 3 | ⏳ Ready | — | — |
| awesome-ai-agents | 3 | ⏳ Ready | — | — |

---

## Notes

- **Adapt title + "Why This Matters" per framework** (provided above)
- **Reuse body template** (same core structure, same reference links)
- **No asks of frameworks** — standalone, self-contained bridge
- **Mutual visibility** — we link back to each as integration example
- **Low friction** — just asking for docs mention + link

