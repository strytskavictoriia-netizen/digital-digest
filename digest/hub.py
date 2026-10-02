"""Центр агентів: особисті сповіщення в окремий бот і відмітки для сторожа healthchecks.io.

Змінні оточення:
    HUB_BOT_TOKEN, HUB_CHAT_ID — бот «центр агентів» і особистий чат з ним
    HEALTHCHECK_URL            — адреса для відмітки «дайджест вийшов» на healthchecks.io
Якщо щось не задано, сповіщення просто пропускаються — дайджест від цього не ламається.
"""
import logging
import os
from html import escape

import requests

from .telegram import TelegramError, _call

log = logging.getLogger(__name__)
AGENT = "🗞 <b>Дайджест</b>"  # перезаписується назвою з config.yaml


def repo_url(path: str = "") -> str:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.getenv('GITHUB_REPOSITORY', '')}{path}"


def run_url(run_id: str | int | None = None) -> str | None:
    run_id = run_id or os.getenv("GITHUB_RUN_ID")
    return repo_url(f"/actions/runs/{run_id}") if run_id else None


def workflow_url(file: str) -> str:
    return repo_url(f"/actions/workflows/{file}")


def button(text: str, url: str | None) -> list[dict]:
    return [{"text": text, "url": url}] if url else []


def notify(text: str, *buttons: list[dict]) -> None:
    token, chat = os.getenv("HUB_BOT_TOKEN", "").strip(), os.getenv("HUB_CHAT_ID", "").strip()
    if not (token and chat):
        log.info("Центр агентів не налаштовано (HUB_BOT_TOKEN / HUB_CHAT_ID) — сповіщення пропущено")
        return
    payload = {"chat_id": chat, "text": f"{AGENT}\n{text}", "parse_mode": "HTML",
               "link_preview_options": {"is_disabled": True}}
    rows = [b for b in buttons if b]
    if rows:
        payload["reply_markup"] = {"inline_keyboard": rows}
    try:
        _call(token, "sendMessage", payload)
    except TelegramError as exc:  # сповіщення не повинно валити сам дайджест
        log.warning("Не вдалося надіслати сповіщення: %s", exc)


def notify_failure(what: str, exc: BaseException, workflow: str) -> None:
    reason = escape(str(exc).strip() or type(exc).__name__)[:500]
    notify(f"❌ {what} не вийшов.\n<code>{reason}</code>",
           button("▶️ Запустити вручну", workflow_url(workflow)),
           button("📄 Журнал запуску", run_url()))


def ping() -> None:
    """Відмітка для сторожа: дайджест вийшов."""
    url = os.getenv("HEALTHCHECK_URL", "").strip()
    if not url:
        return
    try:
        requests.get(url, timeout=15)
    except requests.RequestException as exc:
        log.warning("healthchecks.io недоступний: %s", exc)
