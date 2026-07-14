#!/usr/bin/env bash
# open_browser.sh — open a URL in the machine's default browser.
# Args: <url>   e.g. call_remote("scripts/open_browser.sh", args=["http://localhost:3000"])
set -uo pipefail
URL="${1:-}"
if [ -z "$URL" ]; then
  echo "usage: open_browser.sh <url>" >&2; exit 1
fi
# Only allow http(s) and localhost-style targets; reject file:// and bare paths.
if ! [[ "$URL" =~ ^https?:// ]] \
   && ! [[ "$URL" =~ ^(localhost|127\.0\.0\.1)(:[0-9]+)?(/.*)?$ ]]; then
  echo "refusing to open non-http URL: $URL" >&2; exit 1
fi
# normalise a bare localhost:PORT into a full URL
[[ "$URL" =~ ^https?:// ]] || URL="http://$URL"
if [ "$(uname)" = "Darwin" ]; then
  open "$URL" && echo "opened: $URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 && echo "opened: $URL"
else
  echo "no display / no opener available — open manually: $URL"
fi
exit 0
