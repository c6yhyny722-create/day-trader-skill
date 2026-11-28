#!/usr/bin/env python3
"""PostToolUse hook: after Claude edits a file in a trader-* skill, run that skill's tests.

A failure is reported back to Claude (exit 2) so it is fixed before moving on.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    path = (data.get("tool_input") or {}).get("file_path") or ""
    rel = os.path.relpath(os.path.realpath(path), ROOT) if path else ""
    parts = rel.split(os.sep)
    if not parts or not parts[0].startswith("trader-"):
        if parts and parts[0] == "tests" and rel.endswith(".py"):
            target = parts[-1][:-3] if parts[-1].startswith("test_") else None
        else:
            return 0
    else:
        target = "test_" + parts[0][len("trader-"):]
    tests = ["test_repo"]
    if target and os.path.exists(os.path.join(ROOT, "tests", target + ".py")):
        tests.insert(0, target)
    proc = subprocess.run([sys.executable, "-m", "unittest", "-q", *tests],
                          cwd=os.path.join(ROOT, "tests"), capture_output=True, text=True, timeout=110)
    if proc.returncode != 0:
        sys.stderr.write("Tests failed after this edit (%s):\n%s" % (", ".join(tests), proc.stderr[-3000:]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
