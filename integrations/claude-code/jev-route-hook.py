#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: cheap `jev run route` hint for each prompt.

Reads the hook payload (JSON) on stdin, asks jev's built-in `route` spec about
the prompt, and prints a one-line advisory as `additionalContext`. It never
blocks or rewrites the prompt, and it fails open: any problem (no jev, no key,
network error, timeout, odd output) means no output and exit 0.

Environment:
  JEV_BIN                 path to the jev CLI (default: `jev` on PATH, then
                          ~/.local/share/jev/scripts/jev)
  JEV_ROUTE_DISABLE=1     turn the hook off
  JEV_ROUTE_TIMEOUT       seconds to wait for jev (default 5)
  JEV_ROUTE_MIN_CHARS     skip prompts shorter than this (default 12)
  JEV_ROUTE_MIN_CONF      only show the handler when confidence >= this (default 0.5)
  JEV_ROUTE_SPEC          spec name or path (default `route`)

Privacy: the prompt text is sent to the configured jev provider (TypeSafe or
OpenRouter). Do not enable this hook where that is not acceptable.
"""
import json
import os
import shutil
import subprocess
import sys

MAX_CHARS = 4000


def find_jev():
    explicit = os.environ.get("JEV_BIN")
    if explicit:
        return explicit
    found = shutil.which("jev")
    if found:
        return found
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    candidate = os.path.join(data, "jev", "scripts", "jev")
    return candidate if os.access(candidate, os.X_OK) else None


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def format_hint(answers, min_conf):
    handler = answers.get("handler") or {}
    parts = []
    choice = handler.get("choice")
    if choice and float(handler.get("confidence") or 0) >= min_conf:
        parts.append("handler=%s (p=%.2f)" % (choice, float(handler.get("confidence") or 0)))
    complexity = answers.get("complexity") or {}
    if complexity.get("label"):
        parts.append("complexity=%s" % complexity["label"])
    for key in ("needs_web", "needs_private_data"):
        ans = answers.get(key) or {}
        if "yes" in ans:
            parts.append("%s=%s" % (key, "yes" if ans["yes"] else "no"))
    if not parts:
        return None
    return "jev route hint (advisory, from a cheap classifier; ignore if wrong): " + ", ".join(parts)


def main():
    if os.environ.get("JEV_ROUTE_DISABLE") == "1":
        return
    try:
        prompt = (json.load(sys.stdin).get("prompt") or "").strip()
    except Exception:
        return
    if len(prompt) < env_float("JEV_ROUTE_MIN_CHARS", 12) or prompt[0] in "/!#":
        return
    jev = find_jev()
    if not jev:
        return
    timeout = env_float("JEV_ROUTE_TIMEOUT", 5)
    try:
        proc = subprocess.run(
            [jev, "run", os.environ.get("JEV_ROUTE_SPEC", "route"), "--json",
             "--text", "--timeout", str(timeout), "-s", prompt[:MAX_CHARS]],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout + 1, stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            return
        hint = format_hint(json.loads(proc.stdout)["answers"], env_float("JEV_ROUTE_MIN_CONF", 0.5))
    except Exception:
        return
    if hint:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": hint}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
