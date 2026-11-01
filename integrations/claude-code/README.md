# Claude Code hook: jev route

A `UserPromptSubmit` hook that asks jev's built-in `route` spec about each prompt and adds a
one-line **advisory** to the context, e.g.

```text
jev route hint (advisory, from a cheap classifier; ignore if wrong): handler=code (p=0.80), complexity=困难多步骤, needs_web=no, needs_private_data=no
```

It never blocks or rewrites a prompt and fails open: no jev, no key, network error, timeout or
bad output all mean no hint and exit 0. Prompts under 12 characters and those starting with `/`,
`!` or `#` are skipped. Cost is about $0.00002 and 0.5-1 s per prompt.

**Privacy:** the prompt text is sent to your jev provider (TypeSafe or OpenRouter). It is not
enabled by default; you opt in by adding it to settings.

## Install

1. Install jev and set a key: see the top-level README (`jev auth set`, then `jev auth check`).
2. Merge `settings.example.json` into `~/.claude/settings.json` (all projects) or
   `.claude/settings.json` / `.claude/settings.local.json` (one project), replacing the path with
   the absolute path of `jev-route-hook.py`.

If an entry for jev already exists in your settings, merge rather than duplicating it, or the hint
appears twice.

## Configure (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `JEV_BIN` | `jev` on PATH, then `~/.local/share/jev/scripts/jev` | CLI location |
| `JEV_ROUTE_DISABLE` | unset | `1` turns the hook off |
| `JEV_ROUTE_TIMEOUT` | `5` | seconds to wait for jev |
| `JEV_ROUTE_MIN_CHARS` | `12` | skip shorter prompts |
| `JEV_ROUTE_MIN_CONF` | `0.5` | show `handler` only at or above this confidence |
| `JEV_ROUTE_SPEC` | `route` | spec name or path; a custom spec must keep the same question names |

## Test

```sh
python -m unittest discover -s tests -v
```
