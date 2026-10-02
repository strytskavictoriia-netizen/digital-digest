---
name: digest-builder
description: Build and maintain daily Telegram news digests on any topic with this repository's digest engine (Python + Claude subscription + GitHub Actions + Telegraph pages + watchdog). Use this skill whenever the user wants to create a new digest, newsletter, news feed or "дайджест" on some topic, set up or launch a digest channel, find sources for a topic, add or remove sources (sites, Telegram channels, YouTube channels, Reddit communities), change what the digest covers or how it looks, or figure out why a digest did not arrive — even if they never say the word "skill" or "digest-builder". Ukrainian requests like «зроби дайджест про…», «додай джерело», «чому не прийшов дайджест» should trigger it.
---

# Digest builder

This repository is a ready digest engine. One copy of the repo = one digest = one Telegram channel.
Your job is to turn a topic the user cares about into a working daily digest, and later to keep it
healthy. The people using this are mostly **non-technical** and speak **Ukrainian** — talk to them in
their language, explain things plainly, and do every technical step yourself unless it requires
their account, their password, or their decision.

## How the engine works (read once)

```
config.yaml (topic, audience, rubrics, format, sources)
  → python -m digest daily  — collects sources, asks Claude (via the user's Claude subscription) to
    pick and write items, creates a Telegraph page per item, posts ONE message to the channel,
    writes archive/ + state/seen.json (that is the memory that prevents repeats)
  → GitHub Actions runs it (daily.yml, weekly.yml, watchdog.yml)
  → cron-job.org triggers the workflows on time (GitHub's own schedule is often hours late)
  → the watchdog restarts a missed/hung run; notifications go to the user's personal "agents hub" bot;
    healthchecks.io raises an alarm if nothing was published by the deadline
```

Key files: `config.yaml` (everything topic-specific), `prompts/daily.md` and `prompts/weekly.md`
(generic instructions, rarely need edits), `digest/` (code), `.github/workflows/` (schedule).

Useful commands (run from the repo root with the venv's python):

| Command | What it does |
|---|---|
| `python -m digest check-source <url>` | detects source type from any link (site, t.me/…, youtube.com/@…, reddit.com/r/…, RSS) and shows what it produced in the last 7 days |
| `python -m digest add-source <url> [--name "…"]` | same check, then appends it to `config.yaml` |
| `python -m digest sources` | fetches every source, reports counts and broken ones |
| `python -m digest daily --dry-run` | full generation without publishing → `out/daily-preview.md` |
| `python -m digest publish-preview` | publishes the last dry-run to the channel **and archives it** |
| `python -m digest find-chat` | shows chat IDs the bot has seen (to get the channel ID) |
| `python -m digest test-telegram` | posts a test message to the channel |

Read `references/operations.md` before running anything locally — it explains the environment
quirks (venv, Windows, running Claude Code from inside a Claude Code session, masked secret checks).

## Which flow?

- **New digest** — the user names a topic, or the repo still has the placeholder `config.yaml`
  (`topic: (опис теми)`). Follow "Flow A".
- **Change an existing digest** — add/remove sources, change format, narrow the topic, fix a problem.
  Follow "Flow B".

---

## Flow A — new digest

Work through the stages in order and tell the user where you are ("Крок 2 з 6: шукаю джерела").
Each stage ends with something the user can see or confirm.

### A1. Interview
Read `references/interview.md` and run it. You need: topic and its boundaries, audience and how
they will use the news, 2–4 rubrics, language, and the format choices (number of items, Telegraph
pages, idea of the day, weekly summary, publication time). Propose concrete defaults so the user
can just say "так". Write the answers into `config.yaml` right away (title, emoji, topic, audience,
rubrics, format) — the user can watch the file take shape.

### A2. Research sources yourself
Read `references/sources.md`. Search the web for the best sources for this topic across all types
(official blogs and media, Telegram channels, YouTube channels, Reddit communities, Hacker News with
keywords, Google News queries as a safety net). Check every candidate with `check-source` and keep
only those that actually return recent items. Aim for roughly 15–30 working sources.

### A3. Ask the user for their sources
Show the shortlist grouped by type, one line each: name — why it is useful — how active it is. Then
ask explicitly: «Чи є конкретні джерела, які ти читаєш і хочеш бачити в дайджесті? Сайти,
Telegram-канали, YouTube-канали, спільноти Reddit — просто надішли посилання.» Add each link with
`add-source` and report the result honestly (works / private channel / nothing in a week). Also ask
whether to drop any of yours. Only after this do you add your shortlist with `add-source`.

### A4. Verify the mix
Run `python -m digest sources`. A healthy digest collects ~60–200 fresh items a day. Too few →
add sources; mostly off-topic → add `keywords` to noisy sources or remove them. Fix broken ones.

### A5. Setup with the user
Read `references/setup.md`. It lists, in order, what the user must do themselves (Telegram channel
and bot, Claude subscription token, Telegraph account, GitHub secrets, agents-hub bot,
healthchecks.io, cron-job.org) and what you do. Point the user to the illustrated checklist page
(link in `references/setup.md`) and walk them through the steps they haven't done yet, verifying
each one before moving on.

### A6. Test issue and launch
1. `python -m digest daily --dry-run`, then read `out/daily-preview.md` yourself: are the items on
   topic? Is anything about the user's company leaking into `details`/`recommendations` (those go to
   public Telegraph pages)? Fix `topic`/rubrics and rerun if needed.
2. Show the user the preview and **ask before publishing** to the channel.
3. `python -m digest publish-preview`, then commit and push (`archive/`, `state/`, `config.yaml`)
   — otherwise the next real run will not know what was already published and will repeat it.
4. Confirm the schedule (cron-job.org jobs + workflow cron times) and tell the user when the first
   automatic issue will arrive and what notifications they will get.

---

## Flow B — change an existing digest

- **Add a source**: `add-source <url>`; show what it produced; commit + push.
- **Remove a source**: delete its line from `sources` in `config.yaml`; commit + push.
- **Too much noise / wrong focus**: tighten `topic` (explicit include/exclude lists work best), adjust
  rubric `hint`s, add `keywords` to broad sources. Do a dry-run to show the effect.
- **Change format**: `format` in `config.yaml` (max_items ≤ 14 so it fits one message,
  item_pages, idea_of_day, weekly). Publication time: see `references/setup.md` → "Schedule".
- **"Дайджест не прийшов" / errors**: read `references/troubleshooting.md`.

Always commit and push after changing `config.yaml`, prompts, archive or state — GitHub runs only
what is in the repository.

## Ground rules (learned the hard way)

- **Secrets never go through the chat.** The user puts tokens into `.env` and GitHub Secrets
  themselves. You verify them only in masked form (length / prefix). If a user pastes a token into
  the chat, tell them to revoke and regenerate it.
- **Accounts are created by the user** (Telegram bot, Telegraph via `telegraph-setup`,
  healthchecks.io, cron-job.org, GitHub tokens). You give precise steps; you don't sign up for them.
- **Ask before anything visible to others**: publishing to the channel, starting a GitHub run,
  creating repositories. One user explicitly rejected an unrequested manual run.
- **Telegraph pages are public by link.** Company names, products, clients and plans belong only in
  `teaser` and `idea` (they stay in the private channel). Check the dry-run for leaks.
- **Anything you publish locally must be archived and pushed**, or the next issue repeats it.
- **The user's Claude subscription has limits.** One issue costs ~35–45k tokens. If they run several
  digests, space their publication times at least 30 minutes apart, and prefer `claude-sonnet-5`.
