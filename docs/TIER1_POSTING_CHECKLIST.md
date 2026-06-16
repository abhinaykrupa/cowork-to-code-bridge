# Tier 1 Framework Outreach — Posting Checklist

Status: Ready to post (all issues drafted)

---

## Tier 1: Core Multi-Agent Frameworks (HIGHEST IMPACT)

### 1. LangChain (langchain-ai/langchain)

**Repository:** https://github.com/langchain-ai/langchain  
**Issue Template:** Feature Request  
**Priority:** ⭐⭐⭐⭐⭐ (massive user base)

**Title:**
```
Integration: MCP provider for Claude Code in LangChain workflows — local execution, zero API billing
```

**Body:**
```markdown
## Problem

LangChain users orchestrating multi-agent workflows often need to delegate complex coding tasks (test writing, debugging, building) but can't justify separate Claude API costs. Current options:
- **Separate Claude API billing** — costs money, loses local context
- **Alternative models** — OpenAI, Copilot, etc. (different capability ceiling)
- **Workarounds** — fragile, may violate ToS

This is especially painful for LangChain's tool-use patterns where delegating to Claude Code would unlock powerful capabilities.

## Solution: cowork-to-code-bridge as MCP Provider

**cowork-to-code-bridge** is a lightweight, production-ready daemon that exposes Claude Code (running on the user's machine) as an MCP provider. LangChain workflows can now escalate code-heavy work directly—no API keys, no separate billing, full local context (repos, shell, MCPs).

### How It Works

**MCP Configuration:**
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

**LangChain Agent Code:**
```python
# Delegate to Claude Code running locally
response = toolkit.escalate(
    tool="escalate_to_claude",
    request="Build and test the feature, report results",
    wait_seconds=1800
)
# Returns: {"status": "completed", "result": {...}}
```

### Why This Matters for LangChain

LangChain users building production agents need reliable, cost-effective code execution. This bridge solves that: use Claude Code subscription users already have, access full local context (repos, shell, MCPs), no extra billing. Especially valuable for agent patterns where escalation to a powerful local model is a natural next step.

### Bridge Strengths

- ✅ **Zero network ports** — file-based queue, no inbound/outbound listeners
- ✅ **Token-authenticated** — HMAC-based, same security as existing bridges
- ✅ **Lightweight** — <1MB, minimal Python dependencies
- ✅ **Idempotent + crash-safe** — request deduplication, in-flight recovery
- ✅ **Multiplatform** — macOS (launchd), Linux (systemd), WSL2
- ✅ **MCP standard** — JSONRPC 2.0, widely adopted

### Available MCP Tools

1. **escalate_to_claude** — Hand a task to Claude Code, get structured result asynchronously
2. **run_script** — Execute whitelisted scripts directly (health checks, repo inspections)
3. **list_bridge_scripts** — Discover available scripts

## Reference Implementation

- **Production-ready:** 570 lines of MCP server code + 9 unit tests + comprehensive docs
- **Battle-tested:** Uses same queue/idempotency logic as existing production bridge
- **Validated:** All sanity checks pass; no breaking changes to existing functionality
- **Documented:** MCP spec, config examples, security model, integration guide

**GitHub:** https://github.com/abhinaykrupa/cowork-to-code-bridge
**MCP Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/MCP_SERVER_IMPLEMENTATION.md
**Integration Guide:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/EXTERNAL_AGENT_INTEGRATION.md

## What We're Proposing

1. **Mention in LangChain docs** as an option for users wanting Claude Code backend without API keys
2. **Link to reference implementation** (we maintain it fully)
3. **Mutual visibility** — we link back to LangChain as a reference integration

## No Maintenance Ask

The bridge is completely self-contained. No code changes needed in LangChain, no maintenance obligations for you. We're just asking that your docs mention this as an option for users who want local Claude Code execution without separate API billing.

---

**Try it now:**
```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
cowork-to-code-bridge-mcp --stdio  # Start MCP server
```
```

---

### 2. LangGraph (langchain-ai/langgraph)

**Repository:** https://github.com/langchain-ai/langgraph  
**Issue Template:** Feature Request  
**Priority:** ⭐⭐⭐⭐⭐ (graph-native agents, growing ecosystem)

**Title:**
```
Integration: MCP provider for Claude Code in LangGraph state machines — local execution, zero API billing
```

**Body:** (Use template above, adapt "Why This Matters for LangGraph")

**Custom Section:**
```
### Why This Matters for LangGraph

LangGraph's state-machine pattern for multi-agent workflows is perfect for escalation: when a task requires Claude Code capabilities (test writing, debugging, building), the graph can escalate to the bridge and wait for results. No API keys, no separate billing, full local context. This is especially powerful for LangGraph's checkpointing and resumability features—failed escalations are naturally recoverable.
```

---

### 3. AutoGen (microsoft/autogen)

**Repository:** https://github.com/microsoft/autogen  
**Issue Template:** Feature Request  
**Priority:** ⭐⭐⭐⭐⭐ (Microsoft backing, active community)

**Title:**
```
Integration: MCP provider for Claude Code in AutoGen conversations — local execution, no API billing
```

**Body:** (Use template above, adapt "Why This Matters")

**Custom Section:**
```
### Why This Matters for AutoGen

AutoGen is designed for multi-agent conversations and task delegation. Users want to bring Claude Code into that conversation without managing separate API keys and billing. This bridge lets AutoGen agents (code executor, user proxy) escalate to Claude Code running locally, with full access to the agent's environment (shell, repos, MCPs). Especially powerful for AutoGen's agent loop patterns.
```

---

### 4. n8n (n8n-io/n8n)

**Repository:** https://github.com/n8n-io/n8n  
**Issue Template:** Feature Request  
**Priority:** ⭐⭐⭐⭐ (automation + agents, local execution is core)

**Title:**
```
Integration: MCP provider for Claude Code in n8n workflows — local execution node, no API keys
```

**Body:** (Use template above, adapt "Why This Matters")

**Custom Section:**
```
### Why This Matters for n8n

n8n automation workflows often need to execute code dynamically. Users want to leverage Claude Code (powerful coding model) without managing separate API keys or paying per-use. This bridge provides exactly that: a local execution node powered by Claude Code subscription, with full access to n8n's workflow context (environment variables, previous steps, local files). Especially valuable for deployment automation, testing pipelines, and script generation.
```

---

### 5. Dify (langgenius/dify)

**Repository:** https://github.com/langgenius/dify  
**Issue Template:** Feature Request  
**Priority:** ⭐⭐⭐⭐ (production workflows, needs local exec)

**Title:**
```
Integration: MCP provider for Claude Code in Dify workflows — local code execution, no API keys
```

**Body:** (Use template above, adapt "Why This Matters")

**Custom Section:**
```
### Why This Matters for Dify

Dify users building production AI workflows need reliable, secure local code execution for testing, building, debugging, deployment steps. This bridge provides exactly that: Claude Code runs on the user's machine, no API keys to manage, no separate billing, full local context. Especially valuable for Dify's workflow orchestration and integration patterns where local execution is a core requirement.
```

---

## Tier 2: Secondary Frameworks

### 6. Langflow (langflow-ai/langflow)
- **Title:** "Integration: MCP provider for Claude Code in Langflow workflows — local execution, no API keys"
- **Key Message:** Low-code/no-code designer needs reliable local execution for code-heavy steps

### 7. CrewAI Examples (crewAIInc/crewAI-examples)
- **Title:** "Example: Using cowork-to-code-bridge MCP for local Claude Code execution in CrewAI workflows"
- **Key Message:** Reference implementation showing practical orchestration pattern

---

## Tier 3: Visibility / Curated Lists

### 8. awesome-mcp-servers
- **Action:** Open PR or issue adding bridge to curated list
- **Rationale:** This is WHERE users discover MCP servers

### 9. awesome-mcp-clients
- **Action:** Open PR or issue mentioning bridge as compatible with MCP clients
- **Rationale:** Visibility in MCP ecosystem

### 10. awesome-ai-agents & 500-AI-Agents-Projects
- **Action:** Open issues proposing bridge as local execution option
- **Rationale:** Broad visibility in agent ecosystem

---

## Posting Strategy

### Manual vs. Automated
- **Recommended:** Post Tier 1 manually (5 repos, ~30 min total)
  - Ensures high-quality, framework-specific messaging
  - Build relationships with maintainers
  - Higher response rate than bulk posts

- **Optional:** Use browser automation for Tier 2/3 (10+ repos)
  - More time-consuming to maintain quality
  - Lower response rate but broader visibility

### Expected Timeline
- **Tier 1:** 2-3 days (post 1-2 per day)
- **Tier 2:** 1 week (batch together)
- **Tier 3:** 2 weeks (curated lists, PRs)

### Success Metrics
- ✅ Issues posted to all Tier 1 repos
- ✅ Responses from 50%+ of Tier 1 maintainers
- ✅ At least 2 Tier 1 repos mention bridge in docs
- ✅ PRs merged to awesome-* repos
- ✅ Mutual visibility established (bridge links back)

---

## Tracking

| Repo | Tier | Status | Issue # | Date | Notes |
|---|---|---|---|---|---|
| Crew.ai | 1 | ✅ Done | #6178 | 2026-06-16 | — |
| Hermes | 1 | ✅ Done | #47199 | 2026-06-16 | — |
| Open Claw | 1 | ✅ Done | #93609 | 2026-06-16 | — |
| LangChain | 1 | ⏳ Ready | — | — | Draft ready |
| LangGraph | 1 | ⏳ Ready | — | — | Draft ready |
| AutoGen | 1 | ⏳ Ready | — | — | Draft ready |
| n8n | 1 | ⏳ Ready | — | — | Draft ready |
| Dify | 1 | ⏳ Ready | — | — | Draft ready |
| Langflow | 2 | ⏳ Ready | — | — | Draft ready |
| CrewAI Examples | 2 | ⏳ Ready | — | — | Draft ready |
| awesome-mcp-servers | 3 | ⏳ Ready | — | — | PR draft |
| awesome-ai-agents | 3 | ⏳ Ready | — | — | Issue draft |

---

## Quick Links

- **Bridge Repo:** https://github.com/abhinaykrupa/cowork-to-code-bridge
- **MCP Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/MCP_SERVER_IMPLEMENTATION.md
- **Integration Guide:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/EXTERNAL_AGENT_INTEGRATION.md
- **Master Templates:** docs/MULTI_FRAMEWORK_OUTREACH.md

