#!/usr/bin/env bash
# stats.sh — quick growth dashboard for the repo (stars, clones, views, downloads).
#
# Usage:
#   ./scripts/stats.sh                       # uses the gh CLI (recommended)
#   GH_TOKEN=ghp_xxx ./scripts/stats.sh      # or a token for the API directly
#
# Traffic endpoints (clones/views) require push access to the repo.
set -euo pipefail
REPO="${REPO:-abhinaykrupa/cowork-to-code-bridge}"

# Prefer gh CLI; fall back to curl + GH_TOKEN.
api() {
  if command -v gh >/dev/null 2>&1; then
    gh api "$1" 2>/dev/null
  elif [[ -n "${GH_TOKEN:-}" ]]; then
    curl -fsSL -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" "https://api.github.com/$1"
  else
    echo "Need the gh CLI (brew install gh; gh auth login) or GH_TOKEN set." >&2
    exit 1
  fi
}

jqf() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null || echo "n/a"; }

echo "📊 $REPO"
echo "────────────────────────────────────"

# Stars / forks / watchers / open issues
REPO_JSON="$(api "repos/$REPO")"
echo "⭐ Stars        : $(echo "$REPO_JSON" | jqf 'd["stargazers_count"]')"
echo "🍴 Forks        : $(echo "$REPO_JSON" | jqf 'd["forks_count"]')"
echo "👀 Watchers     : $(echo "$REPO_JSON" | jqf 'd["subscribers_count"]')"
echo "🐛 Open issues  : $(echo "$REPO_JSON" | jqf 'd["open_issues_count"]')"

# Clones + views (last 14 days) — needs push access.
CLONES="$(api "repos/$REPO/traffic/clones" || echo '{}')"
echo "📥 Clones (14d) : $(echo "$CLONES" | jqf 'd.get("count","n/a")') total, $(echo "$CLONES" | jqf 'd.get("uniques","n/a")') unique"
VIEWS="$(api "repos/$REPO/traffic/views" || echo '{}')"
echo "📈 Views  (14d) : $(echo "$VIEWS" | jqf 'd.get("count","n/a")') total, $(echo "$VIEWS" | jqf 'd.get("uniques","n/a")') unique"

# Release asset downloads (summed across all releases).
REL="$(api "repos/$REPO/releases" || echo '[]')"
echo "⬇️  Release DLs  : $(echo "$REL" | python3 -c 'import sys,json;r=json.load(sys.stdin);print(sum(a["download_count"] for rel in r for a in rel.get("assets",[])))' 2>/dev/null || echo 0)"

# Top referrers (where traffic comes from) — needs push access.
echo "🔗 Top referrers:"
api "repos/$REPO/traffic/popular/referrers" 2>/dev/null \
  | python3 -c '
import sys, json
try:
    rows = json.load(sys.stdin)[:5]
    if not rows:
        print("     (none yet)")
    for r in rows:
        print("     %-24s %5d views (%d uniq)" % (r["referrer"], r["count"], r["uniques"]))
except Exception:
    print("     (none / needs push access)")' || echo "     (n/a)"
echo "────────────────────────────────────"
echo "Tip: run this daily during a launch to see which channel (HN/Reddit/etc.) actually moved traffic."
