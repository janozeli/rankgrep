"""PreToolUse hook that limits an agent's Bash to one program and its files to one folder.

Usage as a hook command: guard.py PROGRAM ROOT, where PROGRAM is "rg" or the
absolute path of a launcher. A deny decision on stdout blocks the call and shows
only its reason to the agent. Exit code 2 would also show the hook command line,
which names this file.

A permission rule alone cannot do this: in dontAsk mode Claude Code still runs
read-only commands such as grep, sed, cat and find without any rule.
"""

import json
import os
import re
import shlex
import sys

SHELL_OPERATORS = set("|&;<>()")
HARMLESS_REDIRECT = re.compile(r"\s2>(&1|\s*/dev/null)(?=\s|$)")


def refusal(event: dict, program: str, root: str) -> str | None:
    tool = event.get("tool_name")
    arguments = event.get("tool_input") or {}
    if tool == "Read":
        if _inside(_resolve(arguments.get("file_path", ""), root), root):
            return None
        return "Read only works on files inside the project folder."
    if tool != "Bash":
        return None
    shown = "rg" if program == "rg" else "the rankgrep launcher"
    rule = f"This shell runs only {shown}, as one command with no pipes, redirection or chaining."
    command = HARMLESS_REDIRECT.sub("", arguments.get("command", ""))
    if "\n" in command or "`" in command or "$(" in command:
        return rule
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return rule
    if not words or any(set(word) <= SHELL_OPERATORS for word in words):
        return rule
    if not _is_program(words[0], program, root):
        return rule
    for word in words[1:]:
        if word.startswith("-"):
            continue
        path = _resolve(word, root)
        if os.path.exists(path) and not _inside(path, root):
            return "Search only inside the project folder."
    return None


def _is_program(word: str, program: str, root: str) -> bool:
    if program == "rg":
        return word == "rg"
    return os.path.realpath(_resolve(word, root)) == os.path.realpath(program)


def _resolve(path: str, root: str) -> str:
    return os.path.realpath(os.path.join(root, os.path.expanduser(path)))


def _inside(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def main() -> int:
    program, root = sys.argv[1], sys.argv[2]
    reason = refusal(json.load(sys.stdin), program, root)
    if reason is not None:
        decision = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": decision}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
