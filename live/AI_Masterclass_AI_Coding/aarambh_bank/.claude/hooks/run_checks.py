#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write): format + lint + run tests after edits. Non-blocking."""
import os
import shutil
import subprocess
import sys


def _tail(text, n=15):
    return "\n".join(text.splitlines()[-n:])


def main():
    # repo root = two levels up from this file (.claude/hooks/ -> repo root)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    if shutil.which("ruff"):
        subprocess.run(
            ["ruff", "format", "."],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("--- ruff check ---")
        result = subprocess.run(
            ["ruff", "check", "."], cwd=repo_root, capture_output=True, text=True
        )
        print(_tail(result.stdout + result.stderr))

    if shutil.which("pytest"):
        print("--- pytest ---")
        result = subprocess.run(
            ["pytest", "-q"], cwd=repo_root, capture_output=True, text=True
        )
        print(_tail(result.stdout + result.stderr))

    sys.exit(0)


if __name__ == "__main__":
    main()
