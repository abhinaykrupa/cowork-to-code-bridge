# Master Template: MCP Registry + Core Framework Issues

**Strategy:** One reusable template, adapted per target  
**Status:** Ready to copy-paste across 15+ repos  
**Focus:** Position bridge as canonical "local Claude Code backend" for MCP ecosystem

---

## Master Template (Customize by Category)

### BASE ISSUE TEMPLATE

```markdown
## Problem

Agents and MCP clients using Claude need a way to execute code locally without:
- Separate API key management
- Cloud-only execution (losing repo + env context)
- Additional billing outside existing Claude subscription

This gap limits local-first agent workflows and MCP-based tooling.

## Solution: cowork-to-code-bridge — MCP Server for Local Claude Code

**cowork-to-code-bridge** is a production-ready MCP server exposing Claude Code as a local execution backend.

### Key Features

- ✅ **No API keys** — uses Claude subscription on the user's machine
- ✅ **Full local context** — agent has access to repos, shell, MCPs, environment
- ✅ **MCP standard** — JSONRPC 2.0 over stdio (native protocol)
- ✅ **Zero network ports** — file-based queue, token-authenticated
- ✅ **Lightweight** — <1MB, minimal dependencies
- ✅ **Production-ready** — 570 lines + 9 unit tests + comprehensive docs

### How It Works

**Agent/MCP client config:**
```json
{
  "providers": {
    "claude-code-bridge": {
      "type": "mcp",
      "command": "cowork-to-code-bridge-mcp",
      "args": ["--stdio"],
      "env": {"BRIDGE_ROOT": "$HOME/.cowork-to-code-bridge"}
    }
  }
}
```

**Agent escalates work:**
```python
response = agent.escalate(
    tool="escalate_to_claude",
    request="Debug the API failure and propose fix",
    wait_seconds=600
)
```

### Three MCP Tools

1. **escalate_to_claude** — Hand task to Claude Code, get result asynchronously
2. **run_script** — Execute whitelisted scripts directly
3. **list_bridge_scripts** — Discover available scripts

## Why This Matters [CUSTOMIZE PER REPO]

[SEE CATEGORY-SPECIFIC SECTIONS BELOW]

## Reference Implementation

- **GitHub:** https://github.com/abhinaykrupa/cowork-to-code-bridge
- **MCP Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/MCP_SERVER_IMPLEMENTATION.md
- **Live examples:** Crew.ai (#6178), Hermes (#47199), Open Claw (#93609)

## Proposed Action

[SEE CATEGORY-SPECIFIC SECTIONS BELOW]

---
```

---

## Category 1: MCP Core & Registry (HIGHEST PRIORITY)

These are official Anthropic repos. Getting listed here = de facto standard.

### Target: modelcontextprotocol/registry

**Why it matters:** Official MCP server registry. Being listed = discoverability for all MCP clients.

**Customize "Why This Matters":**
```
This fills a gap in the MCP registry: there's no canonical "local code execution" 
backend. Adding cowork-to-code-bridge as a reference implementation helps MCP 
clients (agents, IDEs, tools) discover the pattern for local Claude integration.
```

**Customize "Proposed Action":**
```
Add cowork-to-code-bridge to the registry under "Local Execution / Code Backends":
- Server name: cowork-to-code-bridge
- Category: Local Execution
- One-line: "MCP server for Claude Code subscription as local execution backend"
- Homepage: https://github.com/abhinaykrupa/cowork-to-code-bridge
```

---

### Target: modelcontextprotocol/quickstart-resources

**Why it matters:** Official quickstart examples. Being here = learning resource for all new MCP developers.

**Customize "Why This Matters":**
```
The quickstart resources could benefit from a "local code execution" example. 
cowork-to-code-bridge shows how to build a stateful MCP server with polling 
patterns (escalation queue), useful pattern for many server types.
```

**Customize "Proposed Action":**
```
Add a quickstart example:
- Directory: examples/local-code-execution/
- Shows: minimal agent + bridge MCP server
- Demonstrates: JSONRPC protocol, tool discovery, polling pattern
- Value: reference implementation for stateful servers

Happy to contribute the example if helpful.
```

---

### Target: modelcontextprotocol/modelcontextprotocol (spec/docs)

**Why it matters:** Official MCP spec/docs repo. Links here = canonical reference.

**Customize "Why This Matters":**
```
The MCP spec docs could mention "local code execution backends" as a use case. 
cowork-to-code-bridge is a reference implementation showing how to build a 
stateful MCP server with async escalation patterns.
```

**Customize "Proposed Action":**
```
Add a section to the docs:
- "Patterns: Building Stateful MCP Servers"
  - Example: local code execution backend
  - Shows: how to handle async operations, polling, escalation
  - Reference: cowork-to-code-bridge repo

This helps server authors understand the pattern, not just the protocol.
```

---

### Target: github/github-mcp-server

**Why it matters:** Official GitHub MCP server. Adding companion pattern = GitHub's blessing.

**Customize "Why It Matters":**
```
GitHub's MCP server is great for querying repo data. As a companion, 
cowork-to-code-bridge enables agents to *execute* code locally based on 
what the GitHub server surfaces (issues, PRs, etc.).
```

**Customize "Proposed Action":**
```
Example or documentation:
- "Companion: Local Code Execution"
- Shows: how to wire GitHub MCP server + Claude Code bridge together
- Use case: "GitHub server finds bug → escalate debugging to Claude Code"

Happy to write the example walkthrough.
```

---

## Category 2: Agent Frameworks (MCP-Aware)

These are agent frameworks that understand MCP natively.

### Target: microsoft/agent-framework

**Customize "Why This Matters":**
```
Agent Framework users building enterprise agents need reliable local execution 
for code-heavy tasks. cowork-to-code-bridge provides that without API key 
management: agents escalate to Claude Code on the user's infrastructure using 
their existing subscription.
```

**Customize "Proposed Action":**
```
Propose:
1. Example integration showing MCP bridge provider in Agent Framework config
2. Use case: "Build → test → debug workflow with local Claude Code execution"
3. Reference: https://github.com/abhinaykrupa/cowork-to-code-bridge

Or: link from docs to our starter repo (microsoft-agent-framework-starter, 
if we build one).
```

---

### Target: lastmile-ai/mcp-agent

**Customize "Why This Matters":**
```
mcp-agent builds agents on top of MCP servers. cowork-to-code-bridge is a 
reference MCP server implementing a useful pattern: async escalation for 
resource-intensive tasks (code execution, long-running operations).

Being demonstrated here helps future server authors understand how to handle 
non-RPC patterns.
```

**Customize "Proposed Action":**
```
Example:
- "Building agents on stateful MCP servers"
- Shows: escalate_to_claude tool, polling for results, multiple concurrent tasks
- Value: demonstrates async patterns beyond simple RPC-style requests

Reference: https://github.com/abhinaykrupa/cowork-to-code-bridge
```

---

### Target: pydantic/pydantic-ai

**Customize "Why This Matters":**
```
PydanticAI agents need structured, validated code execution. cowork-to-code-bridge 
provides that: agents escalate tasks, get structured results, can validate 
via Pydantic models before applying them.
```

**Customize "Proposed Action":**
```
Example integration:
- PydanticAI agent escalates task via bridge
- Result is validated as Pydantic model
- Demonstrates: structured MCP client pattern
- Use case: "Agent generates code change → validated → applied"
```

---

## Category 3: General Agent Frameworks

These are widely-used frameworks; same template with framework-specific flavor.

### Targets: MetaGPT, AutoGPT, Mastra, VoltAgent, OpenAI Agents, etc.

For each, use the base template with this customization:

**"Why This Matters":**
```
[Framework] agents orchestrating multi-step tasks often need local code 
execution (testing, debugging, building). cowork-to-code-bridge provides 
exactly that without separate API key management: agents escalate to Claude 
Code running locally using the user's existing subscription.

Cost-effective, local-first alternative to cloud APIs.
```

**"Proposed Action":**
```
Options:
1. Integration example showing MCP bridge provider in [Framework] config
2. Starter repo: [framework]-mcp-bridge-starter
3. Link from [Framework] docs to our integration guide

(Happy to contribute any of these.)
```

---

## Category 4: Curated Lists (Short PRs)

For awesome-mcp-servers, awesome-mcp-clients, etc. — shorter format.

### PR Title
```
Add cowork-to-code-bridge — MCP server for local Claude Code execution
```

### PR Body (Minimal)
```markdown
## Summary

Adding cowork-to-code-bridge under "Local Execution / Developer Tools".

## Entry

**cowork-to-code-bridge** — MCP server exposing Claude Code subscription as 
local execution backend for agents. JSONRPC 2.0, no API keys, token-authenticated, 
production-ready. Used in Crew.ai, Hermes, Open Claw integrations.

[GitHub](https://github.com/abhinaykrupa/cowork-to-code-bridge) | 
[Docs](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/MCP_SERVER_IMPLEMENTATION.md)

## Category

Suggests: "Local Execution Backends" or "Developer Tools" section (depending 
on list structure)
```

---

## Posting Strategy by Category

### Category 1: MCP Core (DO FIRST — HIGHEST ROI)

**Why:** Official Anthropic repos. Gets bridge into canonical MCP ecosystem.

| Repo | Effort | Expected | Timeline |
|---|---|---|---|
| modelcontextprotocol/registry | 10 min | 95% (direct listing) | Today |
| modelcontextprotocol/quickstart-resources | 20 min | 80% (example) | Today-Tue |
| modelcontextprotocol/modelcontextprotocol | 15 min | 70% (docs mention) | Wed |
| github/github-mcp-server | 15 min | 60% (companion example) | Wed |

**Total:** ~60 min, very high ROI

---

### Category 2: MCP-Native Agents (DO SECOND)

**Why:** These frameworks understand MCP natively, natural fit.

| Repo | Effort | Expected | Timeline |
|---|---|---|---|
| microsoft/agent-framework | 15 min | 70% | Thu |
| lastmile-ai/mcp-agent | 15 min | 75% | Thu |
| pydantic/pydantic-ai | 15 min | 60% | Fri |

**Total:** ~45 min, high ROI

---

### Category 3: General Agent Frameworks (DO THIRD)

**Why:** Large user bases, familiar integration pattern by now.

**Repos:** MetaGPT, AutoGPT, Mastra, VoltAgent, OpenAI Agents, etc.

**Effort:** 10-15 min each (reuse template)  
**Timeline:** Week 2 (1-2 per day)  
**Expected:** 50-60% (good fit but more competitive)

---

### Category 4: Curated Lists (PARALLEL)

**Why:** One PR = visibility to 1000s, durable.

**Repos:** awesome-mcp-servers, awesome-mcp-clients, awesome-ai-agents-2026, etc.

**Effort:** 10 min each (shorter PRs)  
**Timeline:** This week + next (1-2 per day)  
**Expected:** 60-80% (varies by list selectivity)

---

## Full Posting Plan (4 Weeks)

### Week 1: MCP Core + Registry (DO FIRST)

```
Mon:    modelcontextprotocol/registry (15 min) — direct listing
Tue:    modelcontextprotocol/quickstart-resources (20 min) — example
Wed:    modelcontextprotocol/modelcontextprotocol (15 min) — docs mention
        github/github-mcp-server (15 min) — companion pattern

Thu:    Curated lists: awesome-mcp-servers + awesome-ai-agents-2026 (20 min)
        microsoft/agent-framework (15 min)

Fri:    lastmile-ai/mcp-agent (15 min)
        pydantic/pydantic-ai (15 min)
        Monitor responses + adjust messaging
```

**Week 1 Total:** ~2.5 hours, highest-ROI targets

---

### Week 2: General Frameworks + Remaining Lists

```
Mon:    MetaGPT + AutoGPT (30 min)
Tue:    Mastra + VoltAgent (30 min)
Wed:    OpenAI Agents + remaining curated lists (40 min)
Thu-Fri: Monitor responses + follow up
```

**Week 2 Total:** ~2 hours

---

### Week 3+: Topic-Based Sweep + Feedback Refinement

```
Use GitHub topics (ai-agents, agent-framework, autonomous-agents) 
to systematically hit top repos not yet covered.
```

**Total Campaign:** ~4.5 hours for maximum leverage  
**Reach:** 100k-200k+ developers  
**ROI:** One MCP Registry listing = exposure to all future MCP clients

---

## Quick Copy-Paste Sections

### "Why This Matters" — Local Execution
```
Agents orchestrating multi-step tasks need local code execution without 
separate API billing. cowork-to-code-bridge provides exactly that: agents 
escalate to Claude Code running locally using existing subscription.
```

### "Why This Matters" — MCP Ecosystem
```
This fills a gap in the MCP ecosystem: no canonical "local code execution" 
backend. cowork-to-code-bridge is a reference implementation showing how to 
build stateful MCP servers with async escalation patterns.
```

### "Why This Matters" — Enterprise
```
Enterprise agents need reliable local execution for code-heavy workflows. 
cowork-to-code-bridge provides that without API key management or separate 
billing—agents escalate to Claude Code on the user's infrastructure.
```

---

## Expected Success Rates by Category

| Category | Success Rate | Reasoning |
|---|---|---|
| **MCP Core** | 80-95% | Official repos, canonical fit, no competition |
| **MCP-Native Agents** | 70-75% | Framework understands MCP, natural integration |
| **General Frameworks** | 50-60% | Good fit but more options available |
| **Curated Lists** | 60-80% | Varies by list selectivity, durable if accepted |

**Overall expected:** 60-70% of issues get response/acceptance

---

## Key Insight

Instead of 20 identical issues, you're posting to:
- 4 official MCP core repos (highest authority)
- 3 MCP-native agent frameworks (natural fit)
- 5-7 general agent frameworks (good fit)
- 5+ curated lists (durable visibility)

**Total: 17+ targets, each with specific "why it matters" angle.**

One reusable template, customized per category, yields exponentially more impact than spray-and-pray.

