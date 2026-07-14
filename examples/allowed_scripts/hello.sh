#!/usr/bin/env bash
# Example whitelisted script. Save as ~/.cowork-to-code-bridge/scripts/hello.sh
# and chmod +x. Then call from Cowork:
#   call_remote("scripts/hello.sh", args=["world"])
echo "hello from $(hostname) — args: $*"
echo "pwd: $(pwd)"
echo "ts:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
