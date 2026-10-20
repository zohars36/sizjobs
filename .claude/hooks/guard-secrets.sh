#!/usr/bin/env bash
# PreToolUse hook: block any Claude Code tool call that points at
# ~/.config/sizjobs, where the local secrets live.
#
# Claude Code pipes the tool call as JSON on stdin, for example
#   {"tool_name":"Bash","tool_input":{"command":"head ~/.config/sizjobs/.env"}}
# Exit 2 blocks the call and shows stderr to Claude; exit 0 lets it run.
#
# Only the fields that name what a tool touches are checked: command
# (Bash), file_path (Read, Edit, Write), path (Grep, Glob) and pattern
# (Glob only, since a Glob pattern can be an absolute path). File contents
# being written are not checked, so editing docs that mention the folder
# still works. This is a guardrail against mistakes, not a sandbox: a
# deliberately obfuscated path would get through.
#
# No jq on purpose: bash and grep only.

set -uo pipefail

input=$(cat)

# One JSON string field: "name" : "value", where the value may contain
# escaped characters such as \" (the ([^"\\]|\\.)* part).
fields='"(command|file_path|path)"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"'
if grep -qE '"tool_name"[[:space:]]*:[[:space:]]*"Glob"' <<<"$input"; then
  fields='"(command|file_path|path|pattern)"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"'
fi

if grep -oE "$fields" <<<"$input" | grep -qE '\.config/sizjobs'; then
  echo "Blocked: ~/.config/sizjobs holds local secrets. Never read, copy or print it; use 'task secrets' (DRY_RUN=1 for names only)." >&2
  exit 2
fi
exit 0
