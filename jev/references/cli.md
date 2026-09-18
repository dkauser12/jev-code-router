# CLI reference

`jev --help` and `jev <verb> --help` print the same information from the tool itself. This page adds exit codes, error shapes and the spec file format.

## Verbs

### `yes` — yes/no with a calibrated probability

```text
jev yes QUESTION [-s STATE] [--true DESC] [--false DESC] [-t P] [--quiet]
```

Plain stdout: `yes\t0.97` or `no\t0.02`. `--quiet` prints nothing; use the exit code. `-t` sets the yes/no threshold (default `0.5`). `--true`/`--false` describe what each side means. The API requires both sides once `criteria` is present, so giving only one sends the other as an empty description.

### `pick` — one of N options

```text
jev pick QUESTION OPTION[=DESC] OPTION[=DESC]... [--other] [-p] [--min-confidence C]
```

At least two options. `--other` appends an `other` option meaning "none of the above". Plain stdout is the chosen option name; `-p` prints every option with its probability, high to low. `--min-confidence` sets exit code 1 (not an error) when `confidence` is below the threshold.

### `score` — ordinal scale

```text
jev score QUESTION LABEL LABEL... [-p]
jev score QUESTION --range A-B [-p]
```

2–10 labels, low to high, or `--range A-B` (inclusive integers, same 2–10 limit) instead of naming them. Plain stdout: `VALUE\tLABEL` — the expected value under the returned distribution, then the argmax label. `-p` prints every level with its probability.

### `filter` — semantic grep

```text
jev filter QUESTION [--true DESC] [--false DESC] [-t P] [-v] [--with-prob]
```

Always line-based (no `-l` needed). Prints matching lines to stdout, one call per input line. `-v` inverts (print non-matching lines). `--with-prob` prefixes each line with its probability. Exit 0 if at least one line matched, 1 if none matched, 2 if any line errored (matches found so far are still printed).

### `run` — a named or ad hoc spec

```text
jev run                 # list available specs: NAME<TAB>description
jev run SPEC [-s STATE]
jev run /path/to/custom.json
```

`SPEC` is a built-in name, a name under `<config dir>/specs/`, or a path to a spec file. Runs every question in the spec in one API call. Plain stdout is one `name  value  stats` row per question, columns aligned (CJK-width aware); `--json` gives `{"model", "id", "answers": {...}, "usage"}` with every question enriched the same way as single-question JSON output.

### `raw` — the request body, verbatim

```text
jev raw < body.json
```

Reads a complete `{"model", "state", "questions"}` request body from stdin (`model` defaults to `-m`/`$JEV_MODEL`/`~typesafe/jev-latest` if omitted) and prints the API's response JSON unmodified. No client-side validation, no `criteria` normalization — use this to debug a spec or exercise a feature the typed verbs do not expose yet.

## Common options

| Option | Applies to | Meaning |
|---|---|---|
| `-s, --state TEXT\|@FILE\|-` | all but `raw` | State source. Default: read stdin. `-` also means stdin. `@path` reads a file. Missing `-s` with stdin attached to a terminal is an error. |
| `--text` | all but `raw` | Always send state as a plain string; skip JSON auto-detection. |
| `-l, --lines` | `yes`, `pick`, `score`, `run` | One decision per non-empty input line, concurrent, order-preserved, streamed. (`filter` is always line-based.) |
| `--field KEY` | line mode | If a line is a JSON object, judge only `KEY` (coerced to a JSON-safe scalar; see below). |
| `-j, --jobs N` | line mode | Concurrency. Default 8. Keep at or below 16 (see Limits). |
| `--json` | all | Machine-readable output (JSONL in line mode) with every probability and field, input order preserved. |
| `-m, --model ID` | all | Overrides `$JEV_MODEL` / `~typesafe/jev-latest` (or a spec's own `model`). |
| `--timeout SECONDS` | all | Per-request timeout. Default 60. |
| `--retries N` | all | Retries for 429/5xx/network errors, exponential backoff with jitter, `Retry-After` respected. Default 3. |
| `--verbose` | all | stderr: model, latency, tokens, cost (line mode: one summary at the end). |
| `--version` | — | Print `jev X.Y.Z` and exit. |

State auto-detection (without `--text`): if the trimmed input starts with `{` or `[` and parses as JSON, it is sent as a structured `state` (object or array); otherwise it is sent as a string.

`--field` coercion: a JSON object field that is itself a `str`/`dict`/`list` is sent as-is; a JSON `bool` or `null` is sent as its JSON text (`"true"`, `"null"`); a number is sent via `str()` (`"42"`, `"3.5"`). This keeps every field type on the wire as a scalar or JSON-composite `state`, never a bare number/bool that the API would reject.

## Environment variables

| Variable | Effect |
|---|---|
| `OPENROUTER_API_KEY` | The key. See lookup order below. |
| `JEV_ENV_FILE` | An additional `.env`-style file to check for the key, before the config-dir default. |
| `JEV_MODEL` | Default model ID, below an explicit `-m`. |
| `JEV_BASE_URL` | Overrides the decisions endpoint (default `https://openrouter.ai/api/alpha/decisions`); used by this project's own tests, and useful if the alpha path moves. |
| `XDG_CONFIG_HOME` | Overrides the config dir's parent (default `~/.config`); the config dir is `$XDG_CONFIG_HOME/jev` or `~/.config/jev`. |
| `JEV_DEBUG=1` | Print each outgoing request body to stderr. Never prints the key. |

Key lookup order: environment `OPENROUTER_API_KEY` → `$JEV_ENV_FILE` → `<config dir>/.env`. There is no repository-local `./.env` lookup — a key belongs to the user, not a checkout. `<config dir>/.env` is a plain `KEY=value` file, one line: `OPENROUTER_API_KEY=sk-or-...`. Set its permissions to `600`.

Every request also carries `X-Title: jev-cli` and `HTTP-Referer: https://github.com/okooo5km/jev` — OpenRouter's attribution headers, not authentication.

## Exit codes

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `yes` | yes | no | error |
| `pick` | ran | below `--min-confidence` | error |
| `score` | ran | — | error |
| `filter` | ≥1 line matched | 0 lines matched | any line errored |
| `run`, `raw` | ran | — | error |
| line mode (`-l`) | all lines ok | — | ≥1 line failed (detail on stderr; `--json` also emits `{"input","error"}` for that line) |
| any command, Ctrl-C | — | — | 130 |

A client-side validation failure (bad arguments, an out-of-range `score` label count, an unreadable spec) exits 2 without making a request.

## Error shapes

API errors print to stderr as `jev: API 错误 (HTTP n): <detail>` and exit 2. `<detail>` is extracted from the response body, which takes one of three shapes:

1. **A Zod issue array**, serialized as a JSON string inside `error.message` — e.g. `error.message == '[{"path":["questions","answer","criteria"],"message":"Required"}]'`. Rendered as `path: message` pairs joined by `; `.
2. **`HTTP 400: {"detail": ...}`** — `error.message` itself starts with `HTTP `; the remainder is parsed as JSON and its `detail` (a string, or an object with a `message`) is used.
3. **A plain string** — used verbatim.

`HTTP 401` additionally appends a line: `jev: 提示：请检查 OPENROUTER_API_KEY 是否正确。` A missing key never reaches the network: `jev: 未找到 OPENROUTER_API_KEY. ...` prints immediately, exit 2.

`429` and `5xx`/`529` are retried (`--retries`, default 3) with exponential backoff and jitter, honoring a `Retry-After` header when present; only a retry exhausted this way becomes a printed error.

## Spec files

A spec mirrors the API request body plus a `description` and an optional `threshold` (the yes/no cutoff `run`'s plain output uses for `noul` questions, default `0.5`).

```json
{
  "description": "One line shown by `jev run`",
  "model": "typesafe/jev-1.13",
  "threshold": 0.5,
  "questions": {
    "category": {
      "type": "choice",
      "instructions": "Which kind of request is this?",
      "criteria": { "bug": "Reports a crash or a broken feature", "billing": "Payment, refund or license problem", "other": "None of the above" }
    },
    "urgency": {
      "type": "score",
      "instructions": "How soon must someone act?",
      "criteria": ["can wait", "this week", "today", "now"]
    },
    "needs_reply": {
      "type": "noul",
      "instructions": "The sender expects a personal reply",
      "criteria": { "true": "Expects a decision or response", "false": "Pure notice, no response needed" }
    }
  }
}
```

Field rules, enforced before any request is sent: every question needs `type` (`choice`/`score`/`noul`) and non-empty `instructions`. `choice.criteria` is an object with ≥2 entries. `score.criteria` is an array of 2–10 labels, low to high. `noul.criteria` is optional, but if present must have both `true` and `false` — the API rejects one-sided criteria. A question may hold only `type`, `instructions` and `criteria`; any other key (for example `true`/`false` placed beside `instructions` instead of inside `criteria`) is an error, never silently dropped.

Lookup order for `jev run NAME` (first match wins): `<config dir>/specs/NAME.toml` or `.json` → the skill's own `specs/NAME.json`. `jev run /any/path.json` bypasses discovery. TOML needs Python ≥ 3.11 (`tomllib`); on older Python a same-named `.json` wins, and a TOML-only spec fails with a clear "needs 3.11+" error instead of a traceback. The five built-ins ship as JSON so they work on Python 3.9 out of the box: `mail`, `feedback`, `signal`, `commit`, `route` — see [SKILL.md](../SKILL.md) for what each judges.

## Limits

- `score` allows at most 10 levels (an API limit, checked client-side too).
- State plus the longest question is best kept under ~32K tokens; over ~30K estimated tokens, jev prints a non-blocking warning to stderr.
- The endpoint is OpenRouter's **alpha** `https://openrouter.ai/api/alpha/decisions` and may change; override with `JEV_BASE_URL` if it does.
- Roughly 1,200 requests/minute; keep `-j`/line-mode concurrency at 16 or below.
