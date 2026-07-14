#!/usr/bin/env bash
# mac_top.sh — top processes by CPU and memory (macOS or Linux).
# Args: [count] [--json]   (count default 15).
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads()
# JSON fields: count, by_cpu[], by_mem[]   (each entry: pid, cpu_pct, mem_pct, name)
# No external dependencies (no jq, no python).
set -u
JSON=0; N=15
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) [[ "$arg" =~ ^[0-9]+$ ]] && N="$arg" ;;
  esac
done
if [ "$JSON" -eq 1 ]; then
  # Emit a JSON array of the top-N rows, sorted by the given column ($1=cpu, $2=mem).
  emit_procs() {
    ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k"$1" -rn | head -"$N" \
      | awk 'BEGIN{first=1; printf "["}
             {
               name=$4; for(i=5;i<=NF;i++) name=name" "$i;
               gsub(/\\/,"\\\\",name); gsub(/"/,"\\\"",name);
               if(!first) printf ",";
               printf "{\"pid\":%d,\"cpu_pct\":%s,\"mem_pct\":%s,\"name\":\"%s\"}", $1, $2, $3, name;
               first=0
             }
             END{printf "]"}'
  }
  printf '{\n  "count": %d,\n  "by_cpu": %s,\n  "by_mem": %s\n}\n' \
    "$N" "$(emit_procs 2)" "$(emit_procs 3)"
else
  echo "=== by CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -"$((N+1))"
  echo "=== by MEM ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k3 -rn | head -"$((N+1))"
fi
exit 0
