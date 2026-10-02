# Troubleshooting

Start by finding out what actually happened: `archive/daily/<year>/<date>.json` exists → the issue
was published; then look at the latest workflow runs and their logs (see `operations.md`).

| Symptom | Likely cause | Fix |
|---|---|---|
| No issue, no runs at all today | GitHub cron is late (common for new repos); cron-job.org job missing or failing | check cron-job.org history (needs 204); set it up if missing |
| Run failed: `401 OAuth access token is invalid` | subscription token created in the Claude app's terminal, copied incompletely, expired, or revoked | user regenerates with `setup-token` in a standalone terminal; update `.env` + secret |
| Run failed: usage limit / rate limit from Claude | subscription limits exhausted (other usage or several digests at once) | rerun later; space digests apart; use `claude-sonnet-5` |
| Same news as yesterday | the previous issue was published but not archived/pushed (e.g. a local test publish before `publish-preview` archived) | make sure archive/ and state/ are pushed; backfill the archive for that day |
| Issue is off-topic / noisy | `topic` too vague; broad sources without `keywords` | tighten include/exclude lists; add `keywords`; remove noisy sources |
| Few items, thin issue | dead sources; weekend; `lookback_hours` too small | `python -m digest sources`; add practitioner sources |
| A source shows `✗ … 429` | Reddit rate limit | combine subreddits with `+`; add `delay: 15+` |
| A source shows `✗ … 403/404/410` | site blocks bots or moved its feed | `check-source` the site again; replace or drop |
| Telegram channel gives 0 items | channel is private, or posts are media without text | only public channels with text posts work |
| Message too long / items dropped | too many items for one message | lower `format.max_items` (≤14) |
| `TELEGRAPH_TOKEN не задано` in logs | secret missing | user adds it; titles link to sources meanwhile |
| Hub bot silent | `HUB_*` secrets missing, or user never pressed Start | check secret names; ask to press Start |
| Watchdog did nothing | it only acts if the issue is missing; it waits if a run is <25 min old | expected; see its log |
| Watchdog "3 невдалі спроби" | the digest keeps failing for the same reason | read the failing run's log, fix the cause |

When something was published by mistake or twice, tell the user plainly; they can delete posts in
the channel themselves.
