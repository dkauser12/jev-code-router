---
name: jev
description: Make fast, cheap, typed judgments over text or JSON with the jev CLI (TypeSafe Jev decision model via OpenRouter) — a yes/no probability, one choice among labels, or an ordinal score, each with calibrated probabilities instead of prose. Use to classify, triage, route, screen, rank or filter items such as emails, customer feedback, chat or group messages, tweets, logs, git diffs, search results or user requests, especially in bulk (one decision per line) or inside shell scripts and pipelines (exit codes, semantic grep). Also use as a cheap pre-filter before expensive LLM reading, a guardrail check, or a model/agent router. 适用：分类、筛选、分诊、路由、打分、是非判断、批量打标签、语义过滤。Not for writing, summarizing or extracting text, and not for math or date arithmetic.
license: Apache-2.0; see LICENSE.txt
compatibility: Requires Python 3.9+, network access to openrouter.ai and an OPENROUTER_API_KEY.
metadata:
  author: okooo5km(十里)
  version: "0.1.1"
---

# jev

`jev` turns a judgment call into a typed answer with a calibrated probability. It wraps TypeSafe **Jev**, a "System One" decision model on OpenRouter: it reads a state (text or JSON) and answers named questions of three kinds — `noul` (P(yes)), `choice` (one of N), `score` (ordinal scale, at most 10 levels). It never generates text. A call takes about 1 s and costs about $0.00002, so 1,000 decisions cost about 2 cents: use it wherever a script or an agent needs a quick, consistent verdict, and keep LLM reasoning for what survives the filter.

## Setup

1. Run `jev --version`. If the command is missing, the CLI ships with this skill at `scripts/jev` (Python 3.9+, standard library only). Link it with `mkdir -p ~/.local/bin && ln -sf "<this skill's directory>/scripts/jev" ~/.local/bin/jev`, or call it by its absolute path.
2. The key is `OPENROUTER_API_KEY`, looked up in: environment → `$JEV_ENV_FILE` → `<config dir>/.env`, where config dir is `$XDG_CONFIG_HOME/jev` if set, else `~/.config/jev`. On HTTP 401 or `未找到 OPENROUTER_API_KEY`, ask the user to put the key in that `.env` file themselves. Never ask for the key in chat and never print it.

## Choose the verb

| Need | Command | Plain stdout | Exit code |
|---|---|---|---|
| Yes/no | `jev yes "QUESTION"` | `yes\t0.97` | 0 yes · 1 no · 2 error |
| One of N | `jev pick "QUESTION" a="desc" b="desc" [--other]` | `a` | 0 · 1 below `--min-confidence` · 2 error |
| Ordinal score | `jev score "QUESTION" low mid high` or `--range 1-5` | `1.43\tmid` | 0 · 2 error |
| Keep matching lines | `jev filter "QUESTION"` | the matching input lines | 0 some · 1 none · 2 error |
| Several questions at once | `jev run SPEC` | aligned table | 0 · 2 error |
| Raw API body | `jev raw < body.json` | response JSON | 0 · 2 error |

- Input comes from stdin, `-s "TEXT"` or `-s @file`. JSON objects and arrays go out as structured state (`--text` turns that off).
- `-l` makes one decision per input line: concurrent (`-j 8`), order preserved, streamed. For JSONL, `--field KEY` names the field to judge. `filter` always works per line.
- Add `--json` whenever you parse results: it carries every probability and `confidence` (JSONL with `-l`). Plain output suits humans and shell tests.
- `--verbose` prints model, latency, tokens and cost to stderr.
- `yes` and `filter` take `-t P` (threshold, default 0.5) and `--true` / `--false` to spell out what yes and no mean. `pick -p` and `score -p` print the whole distribution.

```bash
jev yes "用户在要求退款吗？" -s "Zipic 一打开就闪退，钱退我！"          # yes	0.97
jev pick "该交给谁处理" code="写代码或改项目" research="需要联网查资料" --other -s "$request" --json
jev score "这条评价给几星" --range 1-5 -s @review.txt                  # 3.30	3
tail -f app.log | jev filter "日志表示用户可见的故障" --false "调试信息、正常请求"
jev run feedback -l --field text --json < tickets.jsonl > labeled.jsonl
```

## Write questions Jev can answer

Jev reads conditions literally and does not infer intent. In testing, `filter "包含具体可行动的信息"` passed an ad ("加微信领取免费 AI 课程，限时三天") at about 0.9, because an ad is literally actionable. `filter "消息给出了具体的技术、产品或行业信息" --false "闲聊、问候、广告、引流、卖课"` excluded it.

- State observable conditions, not goals. Define both sides with `--true` / `--false`.
- Describe every option (`name="description"`); add `--other` when the list may not cover every input.
- Order score labels from low to high, 2–10 of them.
- Put questions about the same input into one spec: one call answers them all.
- Trim the state to what the question needs and stay far below 32K tokens; irrelevant text dilutes the signal.
- Do math and date arithmetic in code and put the result into the state.
- Gate actions on certainty: act on high `confidence` or probability, ask the user or escalate on low ones (`pick --min-confidence 0.7`, `yes -t 0.8`).
- Jev only decides. Narrow the set with it, then read, write or summarize the survivors yourself.

## Specs

`jev run` lists the specs. Built-ins: `mail` (category, urgency, needs reply, promo), `feedback` (intent, sentiment, needs human, churn risk), `signal` (worth reading, topic, novelty for chat messages, tweets, RSS), `commit` (Conventional Commit type, secret leak, breaking change, risk for `git diff --cached`), `route` (handler, complexity, needs web, needs private data for a user request). Built-ins ship as JSON so every Python 3.9+ can load them.

A spec mirrors the API body. Save new ones under `<config dir>/specs/` (`~/.config/jev/specs/` unless `XDG_CONFIG_HOME` is set), which survives reinstalling the skill. JSON works on every supported Python; TOML needs Python 3.11+ (`tomllib`) and errors clearly below that:

```json
{
  "description": "One line shown by `jev run`",
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
      "criteria": { "true": "Asks a question or waits for a decision", "false": "Notice or receipt only" }
    }
  }
}
```

Only `type`, `instructions` and `criteria` are allowed in a question; anything else is rejected before a request is sent. A `noul` question's yes/no descriptions go inside `criteria` (both `true` and `false`).

## Limits

- Decisions only: no text, no field extraction. `score` allows at most 10 levels.
- The endpoint is OpenRouter's alpha `https://openrouter.ai/api/alpha/decisions`; if it moves, set `JEV_BASE_URL`.
- The rate limit is about 1,200 requests/min; keep `-j` at 16 or below. The CLI retries 429 and 5xx with backoff.
- Errors go to stderr as `jev: API 错误 (HTTP n): …` with exit code 2.

Full option reference, exit codes, error shapes and recipes: [references/cli.md](references/cli.md).
