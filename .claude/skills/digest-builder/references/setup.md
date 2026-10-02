# Setup: what the user does, what you do

Illustrated checklist for the user (with checkboxes): **https://claude.ai/artifact/X7f1cfSZRegG6PsYcBKmdu**
Send this link at the start of setup; then guide step by step and verify each step before the next.
Skip steps that are already done (check `.env` in masked form and the list of GitHub secrets).

Throughout: tokens go into `.env` and GitHub Secrets by the user — never into the chat.
GitHub Secrets page: `https://github.com/<owner>/<repo>/settings/secrets/actions/new`.

## 0. Before the digest (once per person)
- Accounts: GitHub, Telegram, Claude **Pro or Max** subscription.
- Claude desktop app installed; the repo created from the template (**Use this template → Private**)
  and opened in Claude Code. (If you are reading this, that part is done.)

## 1. Telegram channel and publishing bot
User: create a **private** channel; create a bot in @BotFather (`/newbot`); add the bot as channel
admin with **Post messages**; put the token into `.env` as `TELEGRAM_BOT_TOKEN`; **after** adding the
bot, post any message in the channel.
You: `python -m digest find-chat` → write the `-100…` ID into `.env` as `TELEGRAM_CHAT_ID`;
`python -m digest test-telegram`. If find-chat sees nothing: the message was posted before the bot
became admin, or it's a different bot — ask for one more post.
One publishing bot can serve all of a person's digests (different channels) — reuse it if they have one.

## 2. Claude subscription token
User, in a **standalone PowerShell / Terminal window — not the terminal panel inside the Claude
app** (a token created there is invalid outside the session):
`npx @anthropic-ai/claude-code setup-token` → log in → copy the whole `sk-ant-oat01-…` token
(widen the window; it must not be cut at a line break) → `.env` as `CLAUDE_CODE_OAUTH_TOKEN`.
You: verify with the quick check in `operations.md`. The token lives ~1 year.

## 3. Telegraph (only if `format.item_pages: true`)
User runs `python -m digest telegraph-setup` themselves (it creates an anonymous Telegraph account
and writes `TELEGRAPH_TOKEN` to `.env`). One token can serve all of a person's digests.

## 4. GitHub Secrets
User adds: `CLAUDE_CODE_OAUTH_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAPH_TOKEN`
(+ step 5 and 6 values). You verify the names via the API/`gh` (names only — values are never readable).

## 5. Agents hub bot — personal notifications
A separate bot for personal notifications (✅ випуск вийшов / ❌ не вийшов / 🔄 наглядач перезапустив).
One hub bot serves all of a person's digests and future agents — reuse it if they have one.
User: @BotFather → new bot (e.g. "Мої агенти"); press **Start** in it; token → `.env` `HUB_BOT_TOKEN`
and secret `HUB_BOT_TOKEN`.
You: get the private chat ID from `getUpdates` of the hub bot (type `private`) → `.env` `HUB_CHAT_ID`;
send a test message; the user adds secret `HUB_CHAT_ID` (not secret, can be shown in chat).

## 6. healthchecks.io — alarm independent of GitHub
User: sign up; Integrations → Telegram (via @HealthchecksBot); create a check named after the digest;
Schedule → **Cron**, expression = one hour before the deadline they want (e.g. `0 8 * * *`),
time zone `Europe/Kyiv`, grace e.g. 90 min; copy **Ping URL** → `.env` and secret `HEALTHCHECK_URL`.
Note: clicking the check name opens the name dialog; the schedule opens from the Period/Grace column.
One check per digest.

## 7. cron-job.org — reliable start times
GitHub's own cron for new repos is often **hours** late, so cron-job.org starts the workflows.
User: GitHub → Settings → Developer settings → **Fine-grained token**
(`https://github.com/settings/personal-access-tokens/new`): Repository access → **Only select
repositories** → this repo (the Repositories permission block appears only after that) → Add
permissions → **Actions: Read and write** → Generate; keep the token for the next step only.
Then on cron-job.org (time zone Europe/Kyiv) two jobs, both **POST** with headers
`Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
`Content-Type: application/json`, `User-Agent: cron-job-digest`, body `{"ref":"main"}`:
- digest: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily.yml/dispatches`, daily at the publication time;
- watchdog: same URL with `watchdog.yml`, ~50 minutes later.
"Test run" must return **204**. 401/403 → wrong header or permission; 404 → wrong owner/repo/file;
422 → wrong body.
A fine-grained token can cover several repos — if the person already has one for another digest,
they can add this repo to it (token settings → Repository access) instead of creating a new one.

## Schedule
- Daily time = the cron-job.org job. Keep GitHub's cron in `daily.yml` as backup: set its three
  `cron:` lines to ~7 minutes after the target time in UTC (Kyiv is UTC+3 in summer, UTC+2 in
  winter — the three lines cover both) and `MIN_KYIV_HOUR` to the target hour.
- Watchdog: cron-job.org ~50 minutes after publication; `watchdog.yml` backup crons and
  `MIN_KYIV_HOUR` likewise.
- Weekly: `weekly.yml` crons + `MIN_KYIV_HOUR` (default Friday 15:00 Kyiv). Optionally a third
  cron-job.org job for `weekly.yml` on the chosen weekday.
- Several digests on one Claude subscription: space them ≥30 minutes apart.

## Done when
`test-telegram` worked, a dry-run looked right, `publish-preview` was published and pushed, the
cron-job.org test run returned 204, and the hub bot delivered ✅ for that run.
