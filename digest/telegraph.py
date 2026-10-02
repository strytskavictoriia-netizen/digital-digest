"""Сторінки Telegraph (telegra.ph) з подробицями кожної новини.

Сторінки Telegraph відкриваються будь-ким, хто має посилання, тому:
- на них немає назв нашої компанії, каналів і планів (це контролює промпт);
- адреса сторінки випадкова: сторінка створюється з випадковим заголовком
  (з нього Telegraph робить адресу), а потім отримує справжній заголовок.
"""
import logging
import secrets
import time

import requests

from .render import human_date

log = logging.getLogger(__name__)
API = "https://api.telegra.ph"
AUTHOR = "Дайджест"  # перезаписується назвою з config.yaml


class TelegraphError(RuntimeError):
    pass


def _call(method: str, payload: dict) -> dict:
    for _ in range(4):
        data = requests.post(f"{API}/{method}", json=payload, timeout=30).json()
        if data.get("ok"):
            return data["result"]
        error = str(data.get("error", ""))
        if error.startswith("FLOOD_WAIT_"):
            time.sleep(int(error.removeprefix("FLOOD_WAIT_") or 5) + 1)
            continue
        raise TelegraphError(f"{method}: {error}")
    raise TelegraphError(f"{method}: забагато спроб")


def create_account() -> str:
    """Створює анонімний акаунт Telegraph і повертає його access_token."""
    return _call("createAccount", {"short_name": "ai_digest", "author_name": AUTHOR})["access_token"]


def _links(links: list[dict]) -> list:
    out = []
    for n, l in enumerate(links):
        out += ([" · "] if n else []) + [{"tag": "a", "attrs": {"href": l["url"]}, "children": [l["name"]]}]
    return out


def item_content(item: dict, label: str) -> list:
    """Сторінка новини: мітка, опис, рекомендації, джерела."""
    nodes = [{"tag": "p", "children": [{"tag": "em", "children": [label]}]}]
    for paragraph in item["details"].split("\n"):
        if paragraph.strip():
            nodes.append({"tag": "p", "children": [paragraph.strip()]})
    if item.get("recommendations"):
        nodes.append({"tag": "h4", "children": ["💡 Як використати в роботі"]})
        nodes.append({"tag": "ul", "children": [{"tag": "li", "children": [r]} for r in item["recommendations"]]})
    if item["links"]:
        nodes.append({"tag": "h4", "children": ["🔗 Джерела"]})
        nodes.append({"tag": "p", "children": _links(item["links"])})
    return nodes


def create_page(token: str, title: str, content: list) -> str:
    placeholder = secrets.token_hex(8)  # з нього Telegraph зробить адресу — її не вгадати
    path = _call("createPage", {"access_token": token, "title": placeholder, "author_name": AUTHOR,
                                "content": [{"tag": "p", "children": ["…"]}]})["path"]
    page = _call(f"editPage/{path}", {"access_token": token, "title": title[:256],
                                      "author_name": AUTHOR, "content": content})
    return page["url"]


def publish_issue(token: str, title: str, result: dict, cfg: dict) -> str | None:
    """Одна сторінка на весь випуск: секції за напрямами, кожна новина детально, тренди, футер «відкинуто»."""
    content = []
    if result.get("headline"):
        content.append({"tag": "p", "children": [{"tag": "em", "children": [result["headline"]]}]})
    for r in cfg["rubrics"]:
        found = sorted((i for i in result["items"] if i["rubric"] == r["id"]), key=lambda i: -i.get("importance", 2))
        if not found:
            continue
        content.append({"tag": "h3", "children": [f"{r['emoji']} {r['title']}"]})
        for it in found:
            content.append({"tag": "h4", "children": [("🔥 " if it.get("importance") == 3 else "") + it["title"]]})
            if it.get("summary"):
                content.append({"tag": "p", "children": [{"tag": "strong", "children": [it["summary"]]}]})
            content += item_content(it, "")[1:]  # без мітки рубрики — вона вже в заголовку секції
    if result.get("trends"):
        content.append({"tag": "h3", "children": ["📈 Тренди"]})
        content.append({"tag": "ul", "children": [{"tag": "li", "children": [t]} for t in result["trends"]]})
    if result.get("rejected"):
        content.append({"tag": "h3", "children": ["🗂 Що перевірили й відкинули"]})
        content.append({"tag": "ul", "children": [
            {"tag": "li", "children": [{"tag": "strong", "children": [r["topic"]]}, f" — {r['reason']}"]}
            for r in result["rejected"]
        ]})
    try:
        url = create_page(token, title, content or [{"tag": "p", "children": ["—"]}])
        log.info("Telegraph: %s", url)
        return url
    except (TelegraphError, requests.RequestException) as exc:
        log.warning("Telegraph: не вдалося створити сторінку випуску: %s", exc)
        return None


def publish_items(token: str, items: list[dict], rubrics: list[dict], day, prefix: str = "") -> None:
    """Додає кожній новині поле page. Помилка однієї сторінки не зупиняє решту."""
    titles = {r["id"]: f"{r['emoji']} {r['title']}" for r in rubrics}
    for it in items:
        label = f"{prefix}{titles.get(it['rubric'], '')} · {human_date(day)}"
        try:
            it["page"] = create_page(token, it["title"], item_content(it, label))
        except (TelegraphError, requests.RequestException) as exc:
            log.warning("Telegraph: не вдалося створити сторінку «%s»: %s", it["title"][:50], exc)
        time.sleep(0.3)
    log.info("Telegraph: створено %d з %d сторінок", sum(1 for i in items if i.get("page")), len(items))
