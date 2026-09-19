# jev

[![CI](https://github.com/okooo5km/jev/actions/workflows/ci.yml/badge.svg)](https://github.com/okooo5km/jev/actions/workflows/ci.yml)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](jev/scripts/jev)

**Typed decisions with calibrated probabilities, from the shell — `yes`/`pick`/`score` over TypeSafe Jev, via TypeSafe's own API by default or OpenRouter. CLI + Agent Skill.**

[中文](README.md) · English

`jev` is an unofficial community wrapper supporting two backends: TypeSafe's own API (default) and
OpenRouter; it has no affiliation with TypeSafe or OpenRouter. Single file, standard library only,
Python 3.9+.

By **okooo5km(十里)**. [More skills](https://sink.5km.tech/skills).

```bash
$ jev yes "Is the user asking for a refund?" -s "Zipic crashes on launch. Refund me!"
yes	0.97

$ jev pick "Who should handle this" code="write or change code" research="needs to search the web" --other -s "write me a Python script"
code

$ jev score "How many stars" --range 1-5 -s "Pretty good, minor issues though"
3.73	4

$ jev run mail -s "Subject: Your App Review Has Passed ..."
category     app_review  p=1.00 conf=1.00
urgency      today       score=1.41/3 conf=0.15
needs_reply  no          p=0.05
is_promo     no          p=0.09
```

## 1. Install the CLI (macOS / Linux)

```sh
curl --proto '=https' --tlsv1.2 -fLsS https://github.com/okooo5km/jev/releases/download/v0.3.0/install.sh -o /tmp/jev-install.sh
sh /tmp/jev-install.sh
export PATH="$HOME/.local/bin:$PATH"
jev --version
```

Downloaded first so you can inspect it before running. Requirements: `python3` >= 3.9, `curl`,
`tar`, `shasum` or `sha256sum`. It writes the skill folder (CLI + built-in specs + docs) to
`${XDG_DATA_HOME:-~/.local/share}/jev/`, then symlinks `~/.local/bin/jev` to `scripts/jev` inside
it. No shell profile edits, no sudo, safe to run again (idempotent). Next step: run `jev auth set`
to configure a key (section 3).

Env overrides: `JEV_VERSION` (default `v0.3.0`), `JEV_HOME` (skill folder location),
`JEV_INSTALL_DIR` (symlink location, default `~/.local/bin`), `JEV_ARCHIVE_DIR` (offline install,
a directory already holding the downloaded archive and checksum).

Manual install: download `jev-vX.Y.Z.tar.gz`, its `.sha256` and `install.sh` from
[Releases](https://github.com/okooo5km/jev/releases/latest) into one directory, verify, then install offline:

```sh
shasum -a 256 -c jev-v0.3.0.tar.gz.sha256
JEV_ARCHIVE_DIR=. sh install.sh
```

Windows: untested, use WSL.

Uninstall:

```sh
rm -f ~/.local/bin/jev
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/jev"
rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/jev"   # optional: also removes the key and custom specs
```

## 2. Install the skill

```sh
npx skills add okooo5km/jev -g
```

Node.js is only needed for this installer, not for the CLI itself. Add `-a claude-code codex ...`
to target specific agents. The skill bundles the CLI at `scripts/jev`; an agent links it onto PATH
on first use. Update with `npx skills update jev -g`, remove with `npx skills remove jev -g`.

TypeSafe also publishes its own Agent Skill (`npx skills add typesafe-ai/skills --skill
typesafe-ai`) for building TypeSafe into your own application code -- that's about designing an
integration. `jev` is different: no code to write, it executes judgments directly from a
shell/agent, ready to use right after install.

```text
Use jev to check whether this ticket is asking for a refund.
Run jev run feedback over this batch of reviews and flag anything that needs a human.
```

## 3. Configure a key

The default backend is TypeSafe's own API, keyed by `TYPESAFE_API_KEY`; OpenRouter is also
supported, keyed by `OPENROUTER_API_KEY`. Keys live only in `~/.config/jev/.env` (mode 600); which
provider runs is a separate, non-secret setting in `~/.config/jev/config.ini` (mode 644).
Resolution order: `--provider` -> `JEV_PROVIDER` environment variable -> the pinned default in
`config.ini` -> auto (TypeSafe if that key exists, else OpenRouter, else an error -- never a silent
fallback).

Recommended: run `jev auth set` in your own terminal. Input is hidden, and the key never goes
through chat, a command-line argument, or shell history. No key yet? Create one at
[console.typesafe.ai/settings/keys](https://console.typesafe.ai/settings/keys) first.

```bash
$ jev auth set
TypeSafe API key（输入不回显，创建于 https://console.typesafe.ai/settings/keys）:
已保存到 ~/.config/jev/.env（权限 600）。运行 jev auth check 验证。
当前 provider：TypeSafe（自动）

$ jev auth status
当前 provider：TypeSafe（自动）
[TypeSafe]
  来源：配置文件 ~/.config/jev/.env
  文件：~/.config/jev/.env
  权限：600
[OpenRouter]
  未配置 OPENROUTER_API_KEY。请在你自己的终端运行 jev auth set --provider openrouter（写入 ~/.config/jev/.env）。

$ jev auth check
密钥有效（TypeSafe）
jev-latest
jev-preview
```

For OpenRouter instead: `jev auth set --provider openrouter` (key from
[openrouter.ai/keys](https://openrouter.ai/keys), format `sk-or-...`). Both keys can be configured
at once; `jev provider default openrouter` (or `typesafe`) pins the default so scripts stay
reproducible -- `auth set` suggests this itself once both keys exist and nothing is pinned. `jev
provider default auto` clears the pin; `jev provider list` shows both providers' key status at a
glance. Don't need a provider anymore? `jev auth remove --provider openrouter` deletes its key from
the config file (a key sourced from an environment variable is untouched, and the command says so).

`auth status` reports how the active provider was chosen, plus each provider's source, path and
permissions (and suggests `chmod 600` when the mode is looser); `auth check` verifies the active
provider's key online (read-only, no charge). Neither ever prints a key itself.

CI and other non-interactive environments have no terminal; use an environment variable, or `jev
auth set --stdin` to read a key from a password manager (no TTY needed, no confirmation prompts, a
prefix mismatch errors out without writing anything):

```sh
export TYPESAFE_API_KEY=...          # default provider
export OPENROUTER_API_KEY=sk-or-...  # or this one
# or:
op read "op://vault/typesafe/key" | jev auth set --stdin
```

You can also bypass `auth set` and edit the file yourself:

```sh
mkdir -p ~/.config/jev && ${EDITOR:-vi} ~/.config/jev/.env
# add one line: TYPESAFE_API_KEY=... or OPENROUTER_API_KEY=sk-or-...
chmod 600 ~/.config/jev/.env
```

Lookup order (per provider): environment -> `$JEV_ENV_FILE` -> `~/.config/jev/.env`
(`XDG_CONFIG_HOME` overrides the config dir). There is no `./.env` (current-directory) lookup -- a
key belongs to the user, not a checkout.

**Security note:** mode 600 keeps out other OS users; any program running as you -- agents
included -- can still read any file you can read, and `chmod` does not change that. What `auth
set` actually guarantees is narrower: the key never passes through chat, a command-line argument,
or shell history.

## 4. Quickstart

| Verb | Purpose | Output | Exit code |
|---|---|---|---|
| `yes` | yes/no | `yes\t0.97` | 0 yes · 1 no · 2 error |
| `pick` | one of N | the chosen option | 0 done · 1 below `--min-confidence` · 2 error |
| `score` | ordinal score | `VALUE\tLABEL` | 0 done · 2 error |
| `filter` | semantic grep | matching input lines | 0 some matched · 1 none · 2 a line errored |
| `run` | several questions at once | aligned table | 0 done · 2 error |
| `raw` | the raw request body | response JSON | 0 done · 2 error |

```bash
# Line mode: one decision per line, 8-way concurrent, input order preserved
printf '%s\n%s\n' '{"text":"please add dark mode"}' '{"text":"crashed three times, refund me"}' \
  | jev run feedback -l --field text --json

# --json: full probability distribution and usage, for scripts to consume
jev run route -s "check whether I have any important email today" --json

# Tail a live log, keep only what deserves attention
tail -f app.log | jev filter "log line is a user-visible failure" --false "debug noise, normal requests"
```

## 5. Write questions Jev can answer

Jev reads conditions literally; it does not infer intent.

- State observable conditions, not goals; spell out both sides with `--true`/`--false` or
  `criteria`.
- Cover every case in an option set, or add `--other` when it might not.
- Order score labels low to high, 2-10 of them.
- Ask every question about one piece of state in a single spec (one call, near-zero extra cost).
- Trim the state to what the question needs; don't paste in a whole document.

Measured counter-example: `jev filter "contains specific, actionable information"` matched an ad
("Add me on WeChat for a free AI course, three days only") at about 0.9 -- literally, an ad *is*
actionable. Rewriting it to `jev filter "the message gives specific technical, product or industry
information" --false "small talk, greetings, ads, lead generation, course sales"` excludes the
same message (`exit 1`, no match).

## 6. Templates

`jev run` lists the available specs. Five ship built in, all JSON (readable on any 3.9+):

| Name | Judges |
|---|---|
| `mail` | category, urgency, needs a reply, pure promo |
| `feedback` | intent, sentiment, needs a human, churn risk |
| `signal` | whether a chat message/tweet is worth reading, topic, novelty |
| `commit` | Conventional Commit type, secret leaks, breaking changes, risk |
| `route` | which handler a request needs, complexity, needs web/private data |

Custom specs live in `~/.config/jev/specs/` (`XDG_CONFIG_HOME` overrides the config dir), as JSON
or TOML -- JSON works on any 3.9+, TOML needs 3.11+ (`tomllib`) and fails with a clear message
below that instead of crashing:

```json
{
  "description": "One line shown by `jev run`",
  "threshold": 0.5,
  "questions": {
    "urgent": { "type": "noul", "instructions": "Is this urgent",
                "criteria": { "true": "Needs action now", "false": "Can be scheduled" } }
  }
}
```

```toml
description = "One line shown by `jev run`"
threshold = 0.5

[questions.urgent]
type = "noul"
instructions = "Is this urgent"
[questions.urgent.criteria]
true = "Needs action now"
false = "Can be scheduled"
```

A question accepts only `type`, `instructions` and `criteria`; any other key fails loudly instead of
being dropped. A yes/no question's descriptions go inside `criteria`, with both `true` and `false`.

## 7. Cost and limits

**TypeSafe (default):** $0.042/M input tokens, output free; 64K token context per request, keep
state plus the longest question under ~32K; rate limit about 1,200 requests/minute. **OpenRouter:**
the same Jev model, response carries its own `usage.cost`; documented context is 32K; the endpoint
is OpenRouter's alpha API `https://openrouter.ai/api/alpha/decisions` and may change -- override
with `JEV_BASE_URL` if it does. Speed: a single call opens a new connection, so it pays connection
setup on top of model time -- typically 0.5-1s total. Line mode (`-l`/`filter`/`run -l`) keeps each
worker's connection open, so every call after the first is about 0.3-0.4s, in line with TypeSafe's
documented 70-500ms -- measured on 40 lines with `-j 4`: about 4s reusing connections versus about
7.5s reconnecting every time. For more than a handful of items, use line mode instead of looping
single calls in a shell; put several questions about the same input into one spec (one call answers
them all); raise `-j` for large batches (default 8, keep at or below 16). `score` allows at most 10
levels (an API limit). Jev only decides -- it never generates text, so reading, writing or
summarizing whatever survives the filter is still on you.

## 8. Development and verification

```sh
python3 -m unittest discover -s tests -v      # offline, stdlib only, no real key needed
shellcheck -s sh installers/install.sh .github/package.sh
sh .github/package.sh vX.Y.Z                  # produces dist/jev-vX.Y.Z.tar.gz(.sha256)
gh release create vX.Y.Z dist/* installers/install.sh
```

## License

Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Independent community project, not
affiliated with TypeSafe or OpenRouter. See more of the author's skills at
[sink.5km.tech/skills](https://sink.5km.tech/skills). Stars and PRs welcome.
