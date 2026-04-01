#!/usr/bin/env bash
# Simple audit hook: logs tool calls to a file and always allows (exit 0)
echo "[$(date '+%H:%M:%S')] EVENT=$HOOK_EVENT TOOL=$HOOK_TOOL_NAME" >> /Users/fang/Desktop/startup/deer-flow/tmp/hook_audit.log
echo "audit logged"
exit 0
