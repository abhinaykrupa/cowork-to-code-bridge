#!/usr/bin/env bash
# disk_hogs.sh — biggest files and folders in a directory (default: home).
# Args: [path] [count] [--json]   e.g. call_remote("scripts/disk_hogs.sh", args=["~/Downloads","15"])
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads()
# JSON fields: path, count, items[] (each: size_bytes, size_human, name)
set -uo pipefail
JSON=0; POS=()
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) POS+=("$arg") ;;
  esac
done
TARGET="${POS[0]:-$HOME}"
COUNT="${POS[1]:-15}"
# expand a leading ~ since args arrive as literal strings
case "$TARGET" in "~"|"~/"*) TARGET="$HOME${TARGET#\~}";; esac
if ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
  echo "count must be a number, got: $COUNT" >&2; exit 1
fi
if [ ! -d "$TARGET" ]; then
  echo "not a directory: $TARGET" >&2; exit 1
fi
if [ "$JSON" -eq 1 ]; then
  # `du -k` gives sizes in 1K blocks (portable across macOS/Linux); convert to bytes.
  ITEMS="$(du -k "$TARGET"/* "$TARGET"/.[!.]* 2>/dev/null \
    | sort -rn \
    | head -n "$COUNT" \
    | awk 'BEGIN{first=1; printf "["}
           {
             bytes=$1*1024; name=$2; for(i=3;i<=NF;i++) name=name" "$i;
             gsub(/\\/,"\\\\",name); gsub(/"/,"\\\"",name);
             # compact human size
             h=$1; u="K"; if(h>=1048576){h=h/1048576; u="G"} else if(h>=1024){h=h/1024; u="M"}
             hs=sprintf("%.1f%s", h, u);
             if(!first) printf ",";
             printf "{\"size_bytes\":%d,\"size_human\":\"%s\",\"name\":\"%s\"}", bytes, hs, name;
             first=0
           }
           END{printf "]"}')"
  cat <<EOF
{
  "path": "$TARGET",
  "count": $COUNT,
  "items": ${ITEMS:-[]}
}
EOF
else
  echo "=== TOP $COUNT LARGEST ITEMS IN $TARGET ==="
  # du over immediate children; sort by size desc; human-readable.
  du -sh "$TARGET"/* "$TARGET"/.[!.]* 2>/dev/null \
    | sort -rh \
    | head -n "$COUNT"
fi
exit 0
