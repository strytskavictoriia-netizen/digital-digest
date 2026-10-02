# Finding sources for a topic

The quality of a digest is mostly the quality of its sources. Look for a mix: primary sources
(where news is born), practitioners (where people show what they did — the most valuable part for
"кейси"), and a safety net (aggregators that catch big events).

## Where to look

| Type | How to find | How to add |
|---|---|---|
| Official blogs of key companies/tools | the products the audience uses; "<product> blog" | site URL → `add-source` finds the RSS |
| Specialist media | web search "<topic> news", "best <topic> blogs 2026" | site URL |
| Newsletters (Substack, beehiiv) | "<topic> newsletter"; they almost always have `/feed` | site URL |
| Telegram channels | web search "<тема> telegram канал", tgstat.com / telemetr catalogues | `t.me/<name>` — public only |
| YouTube channels | "<topic> youtube channel" — practitioners showing their work | `youtube.com/@handle` |
| Reddit | "reddit <topic>" → find 3–8 active communities | `reddit.com/r/<name>` |
| Hacker News | only for tech topics; needs `keywords` | see below |
| Google News | safety net for big events, 1–3 queries | see below |
| Ukrainian sources | if the audience is in Ukraine: relevant UA media, TG channels | as above |

Use WebSearch/WebFetch for discovery, then **always** confirm with `python -m digest check-source <url>`
— many sites have no feed, many channels are dead. Keep a candidate only if it produced items in the
last 7 days (official blogs that post rarely but matter a lot are the exception — keep them).

## Adding with options

`add-source` writes a one-line entry; edit it afterwards if you need options:

```yaml
  - {name: "Reddit AI video", type: "rss", limit: 20, delay: 15, url: "https://www.reddit.com/r/aivideo+StableDiffusion+comfyui/top/.rss?t=day"}
  - {name: "Show HN", type: "hackernews", tags: "show_hn", min_points: 30, keywords: ["\\bAI\\b", "LLM", "agent"]}
  - {name: "Google News", type: "rss", limit: 15, url: "https://news.google.com/rss/search?q=Runway+OR+Kling+OR+Midjourney+when:1d&hl=en-US&gl=US&ceid=US:en"}
  - {name: "Verge", type: "rss", keywords: ["\\bAI\\b", "artificial intelligence"], url: "https://www.theverge.com/rss/index.xml"}
```

- `tier` — trust level shown to the model (T1 official, T2 press, T3 research/data, T4 insiders, UA).
  Set it when the digest uses trust tiers (see interview.md).
- `keywords` — regexes, case-insensitive; an item is kept if any matches. Use for broad media and HN.
- **Query strategy for Google News**: tie queries to mechanisms, not events — words like
  `revenue share`, `RPM`, `rate card`, `price per hour`, `payout`, `terms`, `cost per episode`,
  `deadline`, `grant` bring conditions and numbers; "<company> news" brings PR noise. No dates in the
  query except `when:Nd`.
- `limit` — cap per source (default 25). Keep loud sources (Google News, Reddit) at 10–20.
- **Reddit** rate-limits hard (HTTP 429): combine communities into one feed with `+`
  (`r/a+b+c/top/.rss?t=day`) and give every additional Reddit feed `delay: 15` or more.
- Google News: `when:1d` keeps it fresh; `hl/gl/ceid` choose language/region
  (Ukrainian: `hl=uk&gl=UA&ceid=UA:uk`). Its links are redirects — fine for the digest.
- `undated: true` — for feeds without dates (e.g. GitHub Trending RSS); repeats are filtered by state.

## What a good final list looks like

- 15–30 sources; at least a third are practitioner sources (Reddit, YouTube, TG, HN Show) if the
  user wants cases; 1–3 Google News queries as a net.
- `python -m digest sources` shows 60–200 fresh items per day and no broken sources.
- Nothing obviously off-topic dominates (if a general media floods the input, add `keywords` or drop it).

## Presenting the shortlist to the user

Group by type, one line per source: **назва** — чому корисне — активність («~5 дописів на день»).
Then ask for their own sources (sites, Telegram, YouTube, Reddit) and which to drop. Private
Telegram channels (`t.me/+…`) can't be read — say so and suggest a public alternative.
X/Twitter, Instagram, TikTok and LinkedIn can't be read reliably for free — say so honestly
and look for the same author's blog, newsletter, YouTube or Telegram instead.
