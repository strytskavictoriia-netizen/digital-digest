"""Збір матеріалів: сайти й блоги (RSS), Telegram-канали, YouTube-канали, Reddit, Hacker News.

Типи джерел у config.yaml:
    rss        — будь-яка RSS/Atom-стрічка: сайти, блоги, YouTube, Reddit, Google News (url)
    telegram   — публічний Telegram-канал (channel: назва без @)
    hackernews — Hacker News (min_points; tags: show_hn — лише проєкти, які автори показують самі)
Спільні опції: tier — рівень довіри (T1 офіційні, T2 преса, T3 дослідження, T4 інсайдери, UA…);
limit — макс. матеріалів з джерела; keywords — брати лише матеріали, де є хоч одне
з цих слів (регулярні вирази, без урахування регістру); undated — стрічка без дат; delay — пауза
перед запитом у секундах (для Reddit, який обмежує частоту).

detect() за будь-яким посиланням визначає тип джерела — цим користуються команди
check-source / add-source.
"""
import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DEFAULT_LIMIT = 25
MAX_TOTAL_ITEMS = 450
SNIPPET_CHARS = 350


@dataclass
class Item:
    source: str
    title: str
    url: str
    published: datetime
    summary: str = ""
    id: str = ""
    tier: str = ""  # рівень довіри джерела (T1–T4, UA…), якщо заданий у config.yaml


def clean(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape(text))
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "ref"))])
    return urlunsplit(("https", host, parts.path.rstrip("/"), query, ""))


def normalize_title(title: str) -> str:
    title = re.sub(r"\s+[-–|]\s+[^-–|]{2,40}$", "", title)  # " - Reuters" у Google News
    return " ".join(re.findall(r"\w+", title.lower()))


def matches(src: dict, text: str) -> bool:
    words = src.get("keywords")
    return not words or any(re.search(w, text, re.IGNORECASE) for w in words)


def _get(url: str) -> requests.Response:
    for delay in (10, 20, 0):  # Reddit часто відповідає 429 — чекаємо й пробуємо ще
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        if resp.status_code != 429 or not delay:
            break
        time.sleep(delay)
    resp.raise_for_status()
    return resp


# ── Збирачі за типами ─────────────────────────────────────────

def fetch_rss(src: dict, since: datetime) -> list[Item]:
    feed = feedparser.parse(_get(src["url"]).content)
    items = []
    for e in feed.entries:
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        if stamp:
            published = datetime(*stamp[:6], tzinfo=timezone.utc)
        elif src.get("undated"):  # стрічка без дат — дублі відсіє seen-стан
            published = datetime.now(timezone.utc)
        else:
            continue
        if published < since:
            continue
        title = clean(e.get("title", ""), 300)
        summary = clean(e.get("summary") or e.get("media_description", ""))  # media_description — YouTube
        if not matches(src, f"{title} {summary}"):
            continue
        source = src["name"]
        if "news.google.com" in src["url"] and e.get("source"):
            source = f"{source} / {e.source.get('title', '')}".strip(" /")
        items.append(Item(source, title, e.get("link", ""), published, summary))
    return items


TG_POST = re.compile(r'data-post="([\w]+/\d+)"(.*?)(?=data-post="|\Z)', re.S)
TG_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TG_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')


def fetch_telegram(src: dict, since: datetime) -> list[Item]:
    """Публічний канал через його веб-версію t.me/s/<канал> (останні ~20 дописів)."""
    page = _get(f"https://t.me/s/{src['channel']}").text
    items = []
    for post, body in TG_POST.findall(page):
        stamp, text = TG_TIME.search(body), TG_TEXT.search(body)
        if not (stamp and text):
            continue  # допис без тексту (лише фото/відео)
        published = datetime.fromisoformat(stamp.group(1))
        full = clean(text.group(1), 2000)
        if published < since or not full or not matches(src, full):
            continue
        title = full.split(". ")[0][:150]
        items.append(Item(src["name"], title, f"https://t.me/{post}", published, full[:SNIPPET_CHARS]))
    return items


def fetch_hackernews(src: dict, since: datetime) -> list[Item]:
    ts = int(since.timestamp())
    url = (
        f"https://hn.algolia.com/api/v1/search?tags={src.get('tags', 'story')}&hitsPerPage=300"
        f"&numericFilters=created_at_i>{ts},points>={src.get('min_points', 80)}"
    )
    items = []
    for hit in _get(url).json().get("hits", []):
        title = hit.get("title") or ""
        if not matches(src, title):
            continue
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        info = f"{hit.get('points', 0)} балів, {hit.get('num_comments', 0)} коментарів на Hacker News"
        published = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
        items.append(Item(src["name"], title, link, published, info))
    items.sort(key=lambda i: int(i.summary.split()[0]), reverse=True)
    return items


FETCHERS = {"rss": fetch_rss, "telegram": fetch_telegram, "hackernews": fetch_hackernews}


def _fetch_one(src: dict, since: datetime) -> tuple[dict, list[Item], str | None]:
    try:
        time.sleep(src.get("delay", 0))
        items = FETCHERS[src.get("type", "rss")](src, since)[: src.get("limit", DEFAULT_LIMIT)]
        for item in items:
            item.tier = str(src.get("tier", ""))
        return src, items, None
    except Exception as exc:  # одне зламане джерело не повинно ламати весь дайджест
        return src, [], f"{type(exc).__name__}: {str(exc)[:150]}"


def collect(sources: list[dict], since: datetime, seen: set[str]) -> tuple[list[Item], list[str]]:
    """Повертає (нові унікальні матеріали, список помилок джерел)."""
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda s: _fetch_one(s, since), sources))

    errors, items, urls, titles = [], [], set(), set()
    for src, found, err in results:
        label = src["name"]
        if err:
            errors.append(f"{label}: {err}")
            log.warning("✗ %s — %s", label, err)
            continue
        log.info("✓ %-28s %3d", label[:28], len(found))
        for item in found:
            url_key, title_key = normalize_url(item.url), normalize_title(item.title)
            if not item.title or url_key in seen or url_key in urls or title_key in titles:
                continue
            urls.add(url_key)
            titles.add(title_key)
            items.append(item)

    items.sort(key=lambda i: i.published, reverse=True)
    items = items[:MAX_TOTAL_ITEMS]
    for n, item in enumerate(items, 1):
        item.id = f"n{n}"
    return items, errors


# ── Визначення джерела за посиланням ──────────────────────────

FEED_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml", "/feed/", "/blog/feed", "/blog/rss.xml")


def _is_feed(url: str) -> bool:
    try:
        return bool(feedparser.parse(_get(url).content).entries)
    except requests.RequestException:
        return False


def detect(url: str, name: str | None = None) -> dict:
    """Перетворює посилання (сайт, t.me/…, youtube.com/@…, reddit.com/r/…, RSS) на запис джерела."""
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url.lstrip("@")
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/")

    if host in ("t.me", "telegram.me"):
        channel = path.strip("/").removeprefix("s/").split("/")[0]
        if not channel or channel.startswith("+"):
            raise ValueError("Це приватне посилання-запрошення — читати можна лише публічні канали (t.me/назва).")
        return {"name": name or f"TG @{channel}", "type": "telegram", "channel": channel}

    if host.endswith("youtube.com") or host == "youtu.be":
        m = re.search(r"/channel/(UC[\w-]{22})", path)
        channel_id = m.group(1) if m else None
        if not channel_id:  # @handle, /c/…, /user/… — шукаємо channelId на сторінці каналу
            page = _get(url).text
            m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', page) or \
                re.search(r"youtube\.com/channel/(UC[\w-]{22})", page)
            if not m:
                raise ValueError("Не вдалося знайти ID YouTube-каналу на сторінці.")
            channel_id = m.group(1)
            title = re.search(r'<meta property="og:title" content="([^"]+)"', page)
            name = name or (f"YouTube {html.unescape(title.group(1))}" if title else None)
        return {"name": name or f"YouTube {channel_id}", "type": "rss", "limit": 5,
                "url": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"}

    if host.endswith("reddit.com"):
        m = re.search(r"/r/([\w+]+)", path)
        if not m:
            raise ValueError("Для Reddit потрібне посилання на спільноту: reddit.com/r/назва.")
        return {"name": name or f"r/{m.group(1)}", "type": "rss", "limit": 10, "delay": 15,
                "url": f"https://www.reddit.com/r/{m.group(1)}/top/.rss?t=day"}

    if _is_feed(url):  # це вже стрічка
        return {"name": name or host, "type": "rss", "url": url}

    page = _get(url).text  # шукаємо стрічку на сторінці сайту
    for link in re.findall(r"<link[^>]+>", page, re.I):
        if re.search(r'type="application/(rss|atom)\+xml"', link, re.I):
            href = re.search(r'href="([^"]+)"', link)
            if href and _is_feed(feed := urljoin(url, html.unescape(href.group(1)))):
                return {"name": name or host, "type": "rss", "url": feed}
    base = f"{parts.scheme}://{parts.netloc}"
    for candidate in (url + p for p in FEED_PATHS) if path else (base + p for p in FEED_PATHS):
        if _is_feed(candidate):
            return {"name": name or host, "type": "rss", "url": candidate}

    # стрічки немає — читаємо сайт через Google News (лише заголовки)
    return {"name": name or host, "type": "rss", "limit": 15,
            "url": f"https://news.google.com/rss/search?q=site:{quote_plus(host)}+when:2d&hl=uk&gl=UA&ceid=UA:uk"}


def preview_source(src: dict, days: int = 7) -> list[Item]:
    """Що джерело дало за останні дні — для перевірки перед додаванням."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    _, items, err = _fetch_one({**src, "limit": 50, "delay": 0}, since)
    if err:
        raise RuntimeError(err)
    return items
