# Sync Your Fork with Upstream

Your fork at `https://github.com/sureshpegadapelli84/cowork-to-code-bridge` is 102 commits behind the original. Here's how to sync it:

## Option 1: Using Git Command Line (Recommended)

Run these commands **on your Mac** in Terminal:

```bash
# Navigate to your cloned repo
cd ~/path/to/cowork-to-code-bridge

# 1. Add the original repo as upstream (if not already done)
git remote add upstream https://github.com/abhinaykrupa/cowork-to-code-bridge.git

# 2. Fetch all updates from upstream
git fetch upstream

# 3. Checkout your main branch
git checkout main

# 4. Merge upstream into your main
git merge upstream/main

# 5. Push to your fork
git push origin main
```

**That's it!** Your fork is now up-to-date.

---

## Option 2: Using GitHub Web UI (Easiest)

1. Go to **https://github.com/sureshpegadapelli84/cowork-to-code-bridge**
2. Look for the **"Sync fork"** button (usually appears when behind)
3. Click **"Update branch"**
4. GitHub will automatically pull the latest from upstream

**Screenshot:** The button appears at the top of the repo, next to the Code button.

---

## Option 3: Using GitHub CLI

```bash
# Install GitHub CLI (if needed): brew install gh
# Then run:
gh repo sync sureshpegadapelli84/cowork-to-code-bridge --source abhinaykrupa/cowork-to-code-bridge
```

---

## Verify It Worked

After syncing, run:

```bash
git log --oneline origin/main -5
```

You should see the latest commits (starting with `d1a7e16 test: cover approve_plan.sh…`)

---

## Going Forward (Automate Updates)

To keep your fork auto-synced with upstream:

1. Go to your fork's **Settings**
2. Enable **"Automatically sync fork"** (GitHub feature)
3. Or create a GitHub Action to auto-update

---

## What Changed Since You Forked?

Last 10 commits in upstream:

```
d1a7e16 test: cover approve_plan.sh — the last untested allowed_scripts file
7c28539 fix(README): repair dead Homebrew badge link
4764e29 fix: restore process_kill.sh --json parity
b1b113e fix: green CI — repair broken mcp_audit not-found test
401916b fix: restore per-task model/effort/scope routing
f67f317 fix: repair PR #70 rebase regressions
730f35b Merge PR #70: MCP proxy — reach local stdio MCP servers from Cowork
3b4b9bc fix: resolve merge conflicts from rebase onto main
c3303a8 feat: add cowork-to-code-bridge-mcp stdio server + Hermes integration
7eaa628 fix: add from __future__ import annotations to fix ruff I001
```

Key features in those 102 commits:
- ✅ **Live Status Ticker** — streams progress to Cowork
- ✅ **MCP Proxy** — reach local MCP servers from Cowork
- ✅ **Process Management** — kill named processes safely
- ✅ **Homebrew Support** — tap + auto-bumping CI
- ✅ **Health Checks** — mac_health.sh with --json mode

---

## Common Issues

### "fatal: 'upstream' does not exist"
Run: `git remote add upstream https://github.com/abhinaykrupa/cowork-to-code-bridge.git`

### "Permission denied" or merge conflicts
Contact the original author or check branch protection rules.

### Fork shows as "even" or "ahead"
If your fork is **ahead**, it means you have commits not in upstream. This is fine—they'll stay after you sync.

---

**Recommended:** Use **Option 2 (GitHub Web UI)** if you haven't used git remote commands before. It's one click.
