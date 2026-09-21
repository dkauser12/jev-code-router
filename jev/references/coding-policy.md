# Coding policy

## State contracts

`route` accepts `task` plus optional `repository_summary`, `changes_code`, and
`safety_sensitivity`. It returns only `economy`, `standard`, or `deep`.

`context` accepts `objective` and up to 50 candidates. Each candidate has a unique `id` and optional
short `path`, `symbol`, `excerpt`, and `reason`. Fewer than six candidates bypasses Jev and keeps all
IDs. The wrapper rejects IDs that were not supplied; any malformed or uncertain result keeps all IDs.

`escalate` accepts `current_profile`, `task`, and a non-empty `failure_evidence` object. Supported
evidence fields are `failed_test_summary`, `unsuccessful_edit_count`, `unresolved_ambiguity`, and
`unable_to_locate_code`. `deep` never escalates further.

## Output and failure policy

All commands emit schema version 1 JSON. `fallback: true` means continue normal work using `standard`,
all context candidates, or `stay`. Machine-safe `reason` values never contain upstream response bodies
or environment values. Exit code 0 covers validated decisions and safe fallbacks; exit code 2 is
reserved for invalid local input or usage.

The wrapper explicitly selects OpenRouter, uses the upstream current model alias, defaults to a
1.5-second deadline (`JEV_CODE_TIMEOUT` may set 0.1–10 seconds), and performs no automatic retries.

## Profile mapping

Jev returns labels, not client flags. Keep label mappings local and allowlisted. The example in
`profile-config.example.json` deliberately leaves model names null. Before a future launcher uses a
non-null model or effort, compare it with the installed client's supported values. If validation fails,
preserve the normal `standard` invocation. Do not change the profile of an active session.

## Trial measurement

For a 20–30 task manual trial, record only a task ID, short category, Jev label and distribution,
manual override label, selected profile, outcome (`success`, `corrected`, or `abandoned`), wall-clock
duration when available, major retry/correction count, and Jev latency/cost when upstream exposes it.
Do not record prompts, code, keys, full transcripts, or raw provider responses. Compare with manual
profile selection; retain the router only if expensive-profile use or latency improves without more
failed attempts or corrections.
