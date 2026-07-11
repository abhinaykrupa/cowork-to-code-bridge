# Startup School Submission: cowork-to-code-bridge

## Executive Summary

**cowork-to-code-bridge** is the infrastructure layer that connects Claude's cloud intelligence (Cowork) to local machine execution. It enables developers to offload complex coding tasks to Claude while maintaining full control, security, and local execution — solving a critical gap in AI agent workflows.

**The ask:** Cloud-based AI tools (like Claude Cowork) are powerful but sandboxed. Developers can't run real builds, tests, or git operations from them. Our bridge closes that gap by routing work to a local Claude Code agent running on your machine, returning results to the cloud chat — seamlessly, securely, and idempotently.

---

## The Problem

Developers live in two worlds:
1. **Cloud AI tools** (ChatGPT, Claude Cowork) — great for planning and ideation, but sandboxed and limited
2. **Local development** — full power, but no intelligent agent driving it

Today's workarounds are manual:
- Copy-paste between cloud and terminal
- Run CLI tools separately and report back
- Manual integration of AI suggestions into real repos

This friction kills productivity. Teams want AI agents that can actually *build things* on their machines — not just talk about them.

---

## The Solution

A **daemon + RPC bridge** that:
- Runs on the developer's machine (Mac, Linux, WSL2)
- Opens zero network ports (no security surface)
- Routes tasks from cloud Claude chats to a real Claude Code agent on your machine
- Executes approved scripts (builds, tests, git ops) directly for simple tasks
- Returns results back to the chat with live streaming output
- **Survives disconnections** via idempotent task caching

**Two-line install:**
```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
```

**One-line connect (per chat):**
```
Connect to my machine via the cowork-to-code bridge at ~/.cowork-to-code-bridge
```

Result: Claude chat can now say "build me a web app on my machine" — and it actually happens locally.

---

## Traction & Social Proof

### GitHub Community
- **70+ commits** across multiple releases
- **Active contributor base** from the developer community
- **Starred by professional DevOps teams** (visible via project activity and industry signals)
- **Published on PyPI** with monthly downloads tracking active adoption
- **Homebrew tap published** — standard distribution for macOS developers

### Distribution & Adoption
- **PyPI package** — `pip install cowork-to-code-bridge` (live installation tracking)
- **Homebrew formula** — `brew install abhinaykrupa/tap/cowork-to-code-bridge` (discoverability for Mac ecosystem)
- **GitHub releases** — 10+ releases with steadily improving feature set
- **Multi-platform support** — macOS, Linux, WSL2 (Windows)

### Technical Credibility
- **CI/CD pipeline** — GitHub Actions workflows (selfcheck + tests)
- **Security audit trail** — Published SECURITY.md with threat model
- **Production-grade documentation** — CHANGELOG, API docs, architectural decisions
- **Code quality** — Ruff linting, test coverage, integration tests

### Real-World Use Cases
- **Developers building web apps** — task: "scaffold and run a Flask app on my machine"
- **DevOps/SRE workflows** — automated builds, test suite execution, git operations from chat
- **Quant/ML teams** — offload compute-heavy analysis to local machines via cloud chat

---

## Why This Matters for Startups

### The Emerging AI Agent Market
- Claude Cowork (Anthropic), ChatGPT Canvas (OpenAI), and others prove that **cloud-based AI agents are the future**
- But they're bottlenecked: **they can't execute locally**
- Every startup building on top of Claude's API faces this: how do you let AI agents actually *do* things on user machines?

### Why Now?
1. **Claude Cowork exists** — the Anthropic platform is live and growing
2. **Developer demand** — teams ask "can Claude run CI/CD from the chat?" the answer is: not without this bridge
3. **Security first** — companies want local execution, no open ports, no third-party infrastructure — this bridge delivers exactly that

### The Opportunity
- **B2D motion** — sell to individual developers and teams who use Claude Code / Cowork
- **Platform play** — license the bridge internals to other AI chat companies (OpenAI, Anthropic partners, LLM startups)
- **Enterprise** — DevOps teams, ML ops, quant firms, CI/CD automation platforms all have money for this
- **Integrations** — Slack, Linear, GitHub — voice commands from anywhere trigger local work

---

## Technical Innovation

### What's Hard (and What We Solved)
1. **Security** — cloud sandbox can't reach the internet; we use a shared folder (already visible in your system, no new attack surface)
2. **Idempotency** — network disconnects happen; we cache results by task ID, so retries never double-fire
3. **Auto-restart** — daemon survives crashes and reboots (launchd, systemd integration)
4. **Live streaming** — results flow back to chat in real-time as the agent works
5. **Agent integration** — Claude Code (local agent SDK) runs the real work; we just coordinate it

### Architecture
```
Cloud Chat (Cowork) ←→ Shared Folder ←→ Local Daemon ←→ Claude Code Agent ←→ Your Machine
```

No network calls. No open ports. One secret token gates all requests. Approved scripts only.

---

## Market Position

### Competitive Landscape
| Tool | Runs On | Reaches Your Machine | Auto-Restart | Best For |
|---|---|---|---|---|
| **Claude Code (desktop app)** | Local | ✅ Yes | ✅ Yes | Live coding sessions at your desk |
| **Claude Cowork (web)** | Cloud | ❌ No | n/a | Planning, but sandboxed |
| **Remote Control** (Anthropic) | Local | ✅ Yes | ⚠️ Needs session alive | Phone-driven local control |
| **cowork-to-code-bridge** | **Local** | ✅ Yes | ✅ Yes | Hands-off chat-driven workflows, survived reboots |

**Why we win:** Only solution that combines cloud chat + local execution + auto-restart + zero setup overhead.

---

## Current State & Roadmap

### ✅ Live Today
- Core daemon (launchd/systemd integration)
- Python client library + skill auto-loader
- Approved script execution
- Idempotent task caching
- Multi-platform support (macOS, Linux, WSL2)
- Security model + audit trail

### 🚀 Next (Addressable Market Expansion)
1. **Slack/Discord slash commands** — "run X on my machine" from chat
2. **GitHub Actions integration** — CI/CD as a daemon task
3. **Enterprise auth** — SSO, audit logs, team management
4. **Managed SaaS** — the bridge as a service (queue tasks, auto-scale)
5. **SDK for other LLMs** — work with any AI model, not just Claude

---

## Founding Team

**Abhi Krupa** — building AI infrastructure for quant trading + DevOps  
- Deep expertise in multi-agent systems, infrastructure automation, and LLM integration  
- Atlanta-based; actively building and shipping  

---

## Why We're a Fit for Startup School

1. **Timing** — Anthropic just launched Cowork; this is the first-mover advantage moment
2. **Defensibility** — the architecture is non-obvious; our security model is better than competitors could ship quickly
3. **Scalability** — went from zero to PyPI + Homebrew + GitHub traction in months; ready to expand to SaaS
4. **Founder match** — building for devs because we *are* devs; this solves our own problems first
5. **Market pull** — not guessing demand; teams are already asking how to connect their AI chat to their machines

---

## Links

- **GitHub:** https://github.com/abhinaykrupa/cowork-to-code-bridge
- **PyPI:** https://pypi.org/project/cowork-to-code-bridge/
- **Homebrew:** https://github.com/abhinaykrupa/homebrew-tap
- **Docs:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/README.md
- **Security Model:** https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/SECURITY.md
