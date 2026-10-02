"""Перетворення відповіді моделі на повідомлення Telegram (HTML) і Markdown для архіву.

Випуск — це ОДНЕ повідомлення: кожна новина — заголовок-посилання на сторінку
Telegraph і один рядок під ним. Якщо не вміщається, відкидаються найменш важливі новини.
"""
import logging
import re
from datetime import date
from html import escape, unescape

log = logging.getLogger(__name__)

TG_LIMIT = 4000  # ліміт Telegram — 4096 видимих символів, лишаємо запас

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def human_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def period(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day}–{human_date(end)}"
    return f"{start.day} {MONTHS[start.month - 1]} – {human_date(end)}"


def e(text: str) -> str:
    return escape(text or "", quote=False)


def visible_len(html_text: str) -> int:
    """Ліміт Telegram рахує видимий текст — без HTML-тегів і адрес посилань."""
    return len(unescape(re.sub(r"<[^>]+>", "", html_text)))


def links_html(links: list[dict]) -> str:
    return " · ".join(f'<a href="{escape(l["url"])}">{e(l["name"])}</a>' for l in links)


def title_link(it: dict) -> str:
    url = it.get("page") or (it["links"][0]["url"] if it["links"] else "")
    title = f"<b>{e(it['title'])}</b>"
    return f'<a href="{escape(url)}">{title}</a>' if url else title


def item_line(it: dict) -> str:
    url = it.get("page") or (it["links"][0]["url"] if it["links"] else "")
    title = f"<b>{e(it['title'])}</b>"
    if url:
        title = f'<a href="{escape(url)}">{title}</a>'
    marker = "🔥" if it.get("importance") == 3 else "▪️"
    return f"{marker} {title}\n{e(it['teaser'])}"


def sections(items: list[dict], rubrics: list[dict]) -> list[str]:
    """Новини за напрямами (порядок з config.yaml), головні — першими."""
    out = []
    for r in rubrics:
        found = sorted((i for i in items if i["rubric"] == r["id"]), key=lambda i: -i.get("importance", 2))
        if found:
            out.append(f"{r['emoji']} <b>{e(r['title'].upper())}</b>\n\n" + "\n\n".join(item_line(i) for i in found))
    return out


def one_message(build, items: list[dict]) -> str:
    """Збирає повідомлення; поки не вміщається — прибирає найменш важливу новину з кінця."""
    items = list(items)
    text = build(items)
    while visible_len(text) > TG_LIMIT and items:
        drop = max(range(len(items)), key=lambda n: (-items[n].get("importance", 2), n))
        log.warning("Не вміщається в одне повідомлення — прибираю «%s»", items.pop(drop)["title"][:60])
        text = build(items)
    return text


# ── Блоки, спільні для обох форматів ──────────────────────────
# format.layout: items — кожна новина рядком-посиланням на свою сторінку;
#                issue — топ новини детально + посилання на одну повну сторінку випуску.

def is_issue(cfg: dict) -> bool:
    return cfg["format"].get("layout", "items") == "issue"


def show_idea(d: dict, cfg: dict) -> bool:
    return bool(d.get("idea")) and cfg["format"].get("idea_of_day", True)


def tail_blocks(d: dict, cfg: dict) -> list[str]:
    blocks = []
    if show_idea(d, cfg):
        blocks.append(f"💡 <b>Ідея дня:</b> {e(d['idea'])}")
    if cfg["format"].get("tests") and d.get("tests"):
        blocks.append("🧪 <b>Що протестувати</b>\n" + "\n".join(f"{n}. {e(t)}" for n, t in enumerate(d["tests"], 1)))
    return blocks


def top_card(it: dict, cfg: dict) -> str:
    emoji = {r["id"]: r["emoji"] for r in cfg["rubrics"]}.get(it["rubric"], "▪️")
    text = f"{emoji} <b>{e(it['title'])}</b>"
    if it.get("summary"):
        text += f"\n{e(it['summary'])}"
    text += f"\n💡 <b>Для нас:</b> {e(it['teaser'])}"
    return text + (f"\n🔗 {links_html(it['links'])}" if it["links"] else "")


def top_items(items: list[dict], cfg: dict) -> list[dict]:
    """Головне для поста: спершу importance 3, далі решта — не більше format.top_count."""
    ranked = sorted(items, key=lambda i: -i.get("importance", 2))
    return ranked[: cfg["format"].get("top_count", 3)]


def issue_message(header: str, d: dict, cfg: dict, extra: list[str] | None = None) -> list[str]:
    top = top_items(d["items"], cfg)
    rest = [i for i in d["items"] if i not in top]

    def build(cards: list[dict]) -> str:
        blocks = [header] + [top_card(i, cfg) for i in cards]
        if rest:
            counts = " · ".join(f"{r['emoji']} {e(r['title'])} ({n})" for r in cfg["rubrics"]
                                if (n := sum(1 for i in rest if i["rubric"] == r["id"])))
            if d.get("page"):
                blocks.append(f"➕ <b>Ще у випуску:</b> {counts}")
            else:  # немає сторінки — даємо решту новин рядками з посиланнями на джерела
                blocks.append("➕ <b>Ще у випуску</b>\n" + "\n".join(f"▪️ {title_link(i)}" for i in rest))
        blocks += (extra or []) + tail_blocks(d, cfg)
        if d.get("page"):
            blocks.append(f'📖 <a href="{escape(d["page"])}"><b>Повний випуск — усі новини, деталі й джерела</b></a>')
        return "\n\n".join(blocks)
    return [one_message(build, top)]


# ── Щоденний ──────────────────────────────────────────────────

def daily_telegram(d: dict, cfg: dict, day: date) -> list[str]:
    header = f"{cfg['emoji']} <b>{e(cfg['title'])} · {human_date(day)}</b>  #дайджест"
    if is_issue(cfg):
        return issue_message(header, d, cfg)

    def build(items: list[dict]) -> str:
        return "\n\n".join([header] + sections(items, cfg["rubrics"]) + tail_blocks(d, cfg))
    return [one_message(build, d["items"])]


def item_markdown(it: dict) -> list[str]:
    title = f"[{it['title']}]({it['page']})" if it.get("page") else it["title"]
    links = " · ".join(f"[{l['name']}]({l['url']})" for l in it["links"])
    lines = ["", f"### {'🔥 ' if it.get('importance') == 3 else ''}{title}"]
    if it.get("summary"):
        lines += [f"**{it['summary']}**", ""]
    return lines + [f"💡 _{it['teaser']}_", "", it["details"], "", "**Як використати:**"] + \
        [f"- {r}" for r in it.get("recommendations", [])] + ["", f"🔗 {links}"]


def items_markdown(items: list[dict], cfg: dict) -> list[str]:
    lines = []
    for r in cfg["rubrics"]:
        found = [i for i in items if i["rubric"] == r["id"]]
        if found:
            lines += ["", f"## {r['emoji']} {r['title']}"]
            for it in found:
                lines += item_markdown(it)
    return lines


def tail_markdown(d: dict, cfg: dict) -> list[str]:
    lines = []
    if show_idea(d, cfg):
        lines += ["", "## 💡 Ідея дня", d["idea"]]
    if cfg["format"].get("tests") and d.get("tests"):
        lines += ["", "## 🧪 Що протестувати"] + [f"{n}. {t}" for n, t in enumerate(d["tests"], 1)]
    if d.get("rejected"):
        lines += ["", "## 🗂 Що перевірили й відкинули"] + [f"- **{r['topic']}** — {r['reason']}" for r in d["rejected"]]
    return lines


def daily_markdown(d: dict, cfg: dict, day: date) -> str:
    lines = [f"# {cfg['title']} · {human_date(day)}"]
    if d.get("page"):
        lines += ["", f"Повний випуск у Telegraph: {d['page']}"]
    return "\n".join(lines + items_markdown(d["items"], cfg) + tail_markdown(d, cfg)) + "\n"


# ── Тижневий ──────────────────────────────────────────────────

def weekly_blocks(w: dict) -> list[str]:
    blocks = []
    if w["trends"]:
        blocks.append("📈 <b>Тренди</b>\n" + "\n".join(f"• {e(t)}" for t in w["trends"]))
    if w["opportunities"]:
        blocks.append("💰 <b>Можливості для нас</b>\n" + "\n".join(f"• {e(o)}" for o in w["opportunities"]))
    return blocks


def weekly_telegram(w: dict, cfg: dict, start: date, end: date) -> list[str]:
    header = f"📅 <b>{e(cfg['title'])}: тиждень · {period(start, end)}</b>  #тиждень\n\n<i>{e(w['headline'])}</i>"
    if is_issue(cfg):
        return issue_message(header, w, cfg, extra=weekly_blocks(w))

    def build(items: list[dict]) -> str:
        return "\n\n".join([header] + sections(items, cfg["rubrics"]) + weekly_blocks(w))
    return [one_message(build, w["items"])]


def weekly_markdown(w: dict, cfg: dict, start: date, end: date) -> str:
    lines = [f"# {cfg['title']}: тиждень · {period(start, end)}", "", f"_{w['headline']}_"]
    lines += items_markdown(w["items"], cfg)
    lines += ["", "## 📈 Тренди"] + [f"- {t}" for t in w["trends"]]
    lines += ["", "## 💰 Можливості для нас"] + [f"- {o}" for o in w["opportunities"]]
    return "\n".join(lines) + "\n"
