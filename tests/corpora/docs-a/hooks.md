---
title: Hooks reference
---

# Hooks reference

Hooks run shell commands at fixed points in a session.

## Configuration

### Structure

Hooks live in settings files. Each entry has a matcher and a list of commands.
The matcher is a pattern compared against tool names.

## Hook events

### PreToolUse

Runs after the agent creates tool parameters and before the tool call runs.
Use a matcher such as `Bash` to limit the hook to one tool.

```bash
# block dangerous commands before they run
# exit code 2 blocks the call
read -r payload
echo "$payload" | jq -r .tool_input.command
```

The hook receives the call as JSON on stdin.

### PostToolUse

Runs after a tool call completes, with the tool output attached.

## Limits

### Output size

Set `max_tokens` in the hook output to cap how much text is returned.

### Truncation

When a reply is too long, the max tokens limit applies and the rest is dropped.

## Identity

The helper getUserById returns the user record for a session.
