#!/usr/bin/env bash
# DeerFlow Audit Hook — logs every tool call to a local file.
# Protocol: stdin=JSON, env=HOOK_EVENT/HOOK_TOOL_NAME/HOOK_TOOL_INPUT
# exit 0 = allow, exit 2 = deny

LOG_FILE="${DEERFLOW_AUDIT_LOG:-logs/hook_audit.log}"
mkdir -p "$(dirname "$LOG_FILE")"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] EVENT=$HOOK_EVENT TOOL=$HOOK_TOOL_NAME" >> "$LOG_FILE"

# Allow everything — this is a pure audit hook
exit 0
