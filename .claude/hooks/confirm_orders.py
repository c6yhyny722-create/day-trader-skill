#!/usr/bin/env python3
"""PreToolUse hook: any tool that could place, change or cancel a real broker order always asks first.

The user's rule: analysis and simulation only; no broker order unless he asks for it.
"""
import json
import re
import sys

ORDER_TOOL = re.compile(r"(place|submit|replace|cancel|close)_?[a-z_]*(order|position)", re.I)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    name = data.get("tool_name") or ""
    if name.startswith("mcp__") and ORDER_TOOL.search(name):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "ORDEN REAL AL BRÓKER: solo análisis y simulación salvo que tú la pidas. Confírmala tú.",
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
