---
name: jev-code-router
description: "Use Jev through OpenRouter for an explicitly requested bounded coding judgment: task-profile routing, filtering an already-generated candidate list, or deciding one post-failure escalation. Do not activate automatically for ordinary coding work or routine tool calls."
license: Apache-2.0; see LICENSE.txt
metadata:
  author: okooo5km(十里) and dkauser12
  version: "0.3.2-router.1"
---

# Jev Code Router

Requires Python 3.9+, network access to `openrouter.ai`, and an `OPENROUTER_API_KEY` configured
interactively with the bundled Jev CLI.

Use the bundled `scripts/jev-code` only for bounded judgments with explicit options. Call it with
Python on Windows and pass state through `--state-file PATH` or stdin (`--state-file -`); never put
state or credentials in shell interpolation.

- Run `route` once before a substantial new task only when its result can affect a configured
  launch/profile choice. An in-session result is advisory: only an external launcher can change the
  current model or reasoning effort.
- Run `context` only after deterministic retrieval has produced at least six bounded candidate IDs
  whose short metadata is expensive enough that filtering can materially reduce context. Jev filters;
  deterministic search discovers. Invalid, uncertain, or failed filtering keeps every candidate.
- Run `escalate` once only after observable failure evidence. It may recommend at most one level and
  must never invoke itself recursively.
- Skip Jev when deterministic logic answers the question, all candidates are cheap to inspect, or the
  judgment cannot change behavior. Never call Jev before routine reads, searches, commands, edits,
  tests, or web requests.
- Send only the current task, a short already-known summary, bounded candidate metadata, or concise
  failure evidence. Never send secrets, full transcripts, repositories, full files, or unnecessary
  source content.
- Treat `standard` as the routing fallback and `stay` as the escalation fallback. A valid fallback is
  success and must not block normal Codex work.
- Do not claim token or cost savings without an empirical manual-selection baseline.

Commands:

```text
python <skill>/scripts/jev-code route --state-file request.json
python <skill>/scripts/jev-code context --state-file request.json
python <skill>/scripts/jev-code escalate --state-file request.json
```

Before paid use, the user—not the agent—must run `python <skill>/scripts/jev auth set --provider
openrouter`, `python <skill>/scripts/jev provider default openrouter`, `python <skill>/scripts/jev auth
status`, and `python <skill>/scripts/jev auth check` in an interactive terminal. Never ask for, read,
echo, log, or pipe the key.

Read [references/coding-policy.md](references/coding-policy.md) only when preparing state, interpreting
normalized output, or configuring profiles.
