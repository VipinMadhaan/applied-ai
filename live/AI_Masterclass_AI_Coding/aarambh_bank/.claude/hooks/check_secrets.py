#!/usr/bin/env python3
"""PreToolUse hook (Edit|Write): block hardcoded secrets; warn on float in money paths.

Claude Code passes the tool call as JSON on stdin. Exit code 2 blocks the tool call
and feeds the stderr message back to Claude.
"""
import re
import sys


def main():
    data = sys.stdin.read()

    secret_patterns = [
        r"sk-[A-Za-z0-9_-]{16,}",                                          # OpenAI-style keys
        r"AKIA[0-9A-Z]{16}",                                               # AWS access key id
        r"(?i)(password|secret|api[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]",   # quoted secret literal
    ]
    for pattern in secret_patterns:
        if re.search(pattern, data):
            print(
                "BLOCKED: possible hardcoded secret detected. "
                "Read secrets from environment variables instead (CLAUDE.md rule 4).",
                file=sys.stderr,
            )
            sys.exit(2)

    if re.search(r"float\s*\(", data):
        print(
            "WARNING: 'float(' detected - money must use Decimal, not float "
            "(CLAUDE.md rule 2).",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
