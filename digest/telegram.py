"""Надсилання повідомлень у Telegram через Bot API."""
import logging
import re
import time

import requests

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, payload: dict | None = None) -> dict:
    # Помилки формуємо самі: URL містить токен, і його не можна показувати в логах
    for attempt in range(5):
        try:
            resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {}, timeout=30)
        except requests.RequestException as exc:
            if attempt == 4:
                raise TelegramError(f"{method}: мережева помилка {type(exc).__name__}") from None
            time.sleep(5)
            continue
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        retry = data.get("parameters", {}).get("retry_after")
        if resp.status_code == 429 and retry:
            time.sleep(retry + 1)
            continue
        raise TelegramError(f"{method}: {resp.status_code} {data.get('description')}")
    raise TelegramError(f"{method}: забагато спроб")


def send_messages(token: str, chat_id: str, messages: list[str]) -> None:
    for n, text in enumerate(messages, 1):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                   "link_preview_options": {"is_disabled": True}}
        try:
            _call(token, "sendMessage", payload)
        except TelegramError as exc:
            if "parse" not in str(exc).lower():
                raise
            log.warning("Помилка HTML-розмітки, надсилаю як простий текст: %s", exc)
            payload.pop("parse_mode")
            payload["text"] = re.sub(r"<[^>]+>", "", text)
            _call(token, "sendMessage", payload)
        log.info("Надіслано повідомлення %d/%d", n, len(messages))
        time.sleep(1.5)


def find_chats(token: str) -> list[tuple[str, str, str]]:
    """Чати, де бот бачив активність: (id, тип, назва)."""
    chats = {}
    for upd in _call(token, "getUpdates"):
        for key in ("channel_post", "message", "my_chat_member", "edited_channel_post"):
            chat = (upd.get(key) or {}).get("chat")
            if chat:
                chats[str(chat["id"])] = (chat["type"], chat.get("title") or chat.get("username") or "")
    return [(cid, t, name) for cid, (t, name) in chats.items()]
