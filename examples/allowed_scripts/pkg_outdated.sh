#!/usr/bin/env bash
# pkg_outdated.sh — list outdated system packages (macOS or Linux).
# Detects the package manager: brew on macOS; apt/dnf/yum/pacman on Linux.
# Usage: pkg_outdated.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
# JSON fields: manager (brew|apt|dnf|yum|pacman|null), count (int),
#   packages (array of package-name strings, best-effort), raw (full output).
set -u

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

manager=""
raw=""

if command -v brew >/dev/null 2>&1; then
  manager="brew"
  raw="$(brew outdated 2>/dev/null || true)"
elif command -v apt >/dev/null 2>&1; then
  manager="apt"
  # Drop the "Listing..." header line apt prints to stdout.
  raw="$(apt list --upgradable 2>/dev/null | grep -v '^Listing' || true)"
elif command -v dnf >/dev/null 2>&1; then
  manager="dnf"
  # dnf check-update exits 100 when updates exist; don't treat that as an error.
  raw="$(dnf check-update 2>/dev/null || true)"
elif command -v yum >/dev/null 2>&1; then
  manager="yum"
  raw="$(yum check-update 2>/dev/null || true)"
elif command -v pacman >/dev/null 2>&1; then
  manager="pacman"
  raw="$(pacman -Qu 2>/dev/null || true)"
fi

# Best-effort package-name extraction (first whitespace/`/`-delimited token per
# non-empty line). brew lists bare names; apt uses "name/suite"; pacman/dnf put
# the name first too.
extract_names() {
  printf '%s\n' "$raw" | awk 'NF { n=$1; sub(/\/.*/,"",n); print n }'
}

if [ "$JSON" -eq 1 ]; then
  jesc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  raw_json() { printf '%s' "$raw" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk 'BEGIN{ORS=""} {if(NR>1) printf "\\n"; print}'; }
  mgr_json() { if [ -z "$manager" ]; then printf 'null'; else printf '"%s"' "$manager"; fi; }

  names=""
  count=0
  if [ -n "$manager" ]; then
    while IFS= read -r name; do
      [ -z "$name" ] && continue
      if [ -z "$names" ]; then
        names="\"$(jesc "$name")\""
      else
        names="$names, \"$(jesc "$name")\""
      fi
      count=$((count + 1))
    done <<EOF
$(extract_names)
EOF
  fi

  printf '{\n'
  printf '  "manager": %s,\n' "$(mgr_json)"
  printf '  "count": %s,\n' "$count"
  printf '  "packages": [%s],\n' "$names"
  printf '  "raw": "%s"\n' "$(raw_json)"
  printf '}\n'
  exit 0
fi

echo "=== OUTDATED PACKAGES ==="
case "$manager" in
  brew)   echo "--- Homebrew (brew outdated) ---" ;;
  apt)    echo "--- APT (apt list --upgradable) ---" ;;
  dnf)    echo "--- DNF (dnf check-update) ---" ;;
  yum)    echo "--- YUM (yum check-update) ---" ;;
  pacman) echo "--- pacman (pacman -Qu) ---" ;;
  *)      echo "No supported package manager found (looked for brew, apt, dnf, yum, pacman)."; exit 0 ;;
esac
printf '%s\n' "$raw"
exit 0
