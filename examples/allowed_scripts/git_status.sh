#!/usr/bin/env bash
# Example: git status in any repo directory.
#
# Text (default): the familiar `git status --short --branch` output.
# JSON (--json):   a parseable object Cowork can consume without scraping text —
#   { "repo", "branch", "upstream", "ahead", "behind", "clean", "files": [ {x,y,path} ] }
#
# Usage from Cowork:
#   call_remote("scripts/git_status.sh", args=["/path/to/repo"])
#   call_remote("scripts/git_status.sh", args=["/path/to/repo", "--json"])
set -euo pipefail

REPO="$PWD"
JSON=0
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *)      REPO="$arg" ;;
  esac
done
cd "$REPO"

if [ "$JSON" -eq 0 ]; then
  git status --short --branch
  exit 0
fi

# ── JSON mode ────────────────────────────────────────────────────────────────
# Use porcelain v2 + branch headers: stable, machine-oriented, locale-independent.
status="$(git status --porcelain=v2 --branch 2>/dev/null)"

branch=""
upstream=""
ahead=0
behind=0

# Branch headers look like:  "# branch.head main", "# branch.upstream origin/main",
# "# branch.ab +2 -1". A detached HEAD reports "(detached)".
while IFS= read -r line; do
  case "$line" in
    "# branch.head "*)     branch="${line#\# branch.head }" ;;
    "# branch.upstream "*) upstream="${line#\# branch.upstream }" ;;
    "# branch.ab "*)
      ab="${line#\# branch.ab }"           # e.g. "+2 -1"
      a="${ab%% *}"; b="${ab##* }"          # "+2"  "-1"
      ahead="${a#+}"; behind="${b#-}"
      ;;
  esac
done <<< "$status"

# Changed/untracked entries: build a JSON array of {x, y, path}.
# Porcelain v2 entry forms we care about:
#   "1 <XY> ... <path>"          ordinary changed entry
#   "2 <XY> ... <path>\t<orig>"  rename/copy (path is the new name, tab-separated)
#   "u <XY> ... <path>"          unmerged
#   "? <path>"                   untracked
json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

files_json=""
append_file() {
  local x="$1" y="$2" path="$3"
  local entry
  entry="{\"x\":\"$(json_escape "$x")\",\"y\":\"$(json_escape "$y")\",\"path\":\"$(json_escape "$path")\"}"
  if [ -z "$files_json" ]; then files_json="$entry"; else files_json="$files_json,$entry"; fi
}

# Untracked/ignored paths are C-quoted by git when they contain special chars
# (wrapped in "..." with \-escapes). Unwrap to the literal filename.
unquote_path() {
  local p="$1"
  case "$p" in
    \"*\")
      p="${p#\"}"; p="${p%\"}"
      # Undo the common C-style escapes git emits.
      p="${p//\\\"/\"}"; p="${p//\\\\/\\}"
      ;;
  esac
  printf '%s' "$p"
}

while IFS= read -r line; do
  case "$line" in
    # Ordinary changed entry: 8 leading fields, then <path>.
    "1 "*)
      xy="$(printf '%s' "$line" | cut -d' ' -f2)"
      path="$(printf '%s' "$line" | cut -d' ' -f9-)"
      append_file "${xy:0:1}" "${xy:1:1}" "$path"
      ;;
    # Rename/copy entry: 9 leading fields (extra <Xscore>), then
    # <new-path>\t<orig-path>. We report the new path.
    "2 "*)
      xy="$(printf '%s' "$line" | cut -d' ' -f2)"
      rest="$(printf '%s' "$line" | cut -d' ' -f10-)"
      path="${rest%%$'\t'*}"
      append_file "${xy:0:1}" "${xy:1:1}" "$path"
      ;;
    # Unmerged entry: 10 leading fields, then <path>.
    "u "*)
      xy="$(printf '%s' "$line" | cut -d' ' -f2)"
      path="$(printf '%s' "$line" | cut -d' ' -f11-)"
      append_file "${xy:0:1}" "${xy:1:1}" "$path"
      ;;
    # Untracked entry: "? <path>" (path may be C-quoted).
    "? "*)
      append_file "?" "?" "$(unquote_path "${line#\? }")"
      ;;
  esac
done <<< "$status"

clean=true
[ -n "$files_json" ] && clean=false

repo_abs="$(pwd)"
printf '{"repo":"%s","branch":"%s","upstream":"%s","ahead":%s,"behind":%s,"clean":%s,"files":[%s]}\n' \
  "$(json_escape "$repo_abs")" \
  "$(json_escape "$branch")" \
  "$(json_escape "$upstream")" \
  "${ahead:-0}" "${behind:-0}" "$clean" "$files_json"
