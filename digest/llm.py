"""Виклик Claude зі структурованою (JSON) відповіддю.

Два способи (config.yaml → backend):
  subscription — через Claude Code і токен підписки Pro/Max (CLAUDE_CODE_OAUTH_TOKEN)
  api          — через Claude API і ключ з балансом (ANTHROPIC_API_KEY)
"""
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile

log = logging.getLogger(__name__)

# $ за 1M токенів (input, output) — лише для оцінки вартості в логах
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Для цих моделей вмикаємо серверний fallback: якщо модель відмовить через
# фільтри безпеки, запит автоматично перезапуститься на іншій моделі.
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}


class LLMError(RuntimeError):
    pass


def generate_json(cfg: dict, system: str, user: str, schema: dict,
                  web: bool = False, model: str | None = None, effort: str | None = None) -> dict:
    """web=True — модель може шукати й відкривати сторінки в інтернеті (WebSearch, WebFetch) для перевірки."""
    cfg = {**cfg, "model": model or cfg.get("model"), "effort": effort or cfg.get("effort")}
    if cfg.get("backend", "subscription") == "api":
        if web:
            log.warning("Веб-перевірка доступна лише з backend: subscription — працюю без неї")
        return _via_api(cfg, system, user, schema)
    return _via_subscription(cfg, system, user, schema, web)


# ── Підписка: Claude Code CLI ─────────────────────────────────

def _via_subscription(cfg: dict, system: str, user: str, schema: dict, web: bool = False) -> dict:
    lines = (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or "").split()
    if not lines:
        raise LLMError("Не задано CLAUDE_CODE_OAUTH_TOKEN (токен з команди `claude setup-token`)")
    # Секрет часто вставляють із зайвим: перенос рядка, пробіл або наступний рядок із .env.
    # Токен — це лише перше «слово», решту відкидаємо.
    token = lines[0]
    if len(lines) > 1:
        log.warning("CLAUDE_CODE_OAUTH_TOKEN містить зайве після токена (%d додаткових фрагментів) — відкидаю. "
                    "Збережіть секрет заново: лише сам токен, без інших рядків.", len(lines) - 1)
    # Скопійований разом із назвою змінної (CLAUDE_CODE_OAUTH_TOKEN=sk-ant-…) або в лапках
    cleaned = re.sub(r"^[A-Za-z_]+=", "", token).strip("\"'`")
    if cleaned != token:
        log.warning("У значенні CLAUDE_CODE_OAUTH_TOKEN була назва змінної або лапки — прибрано. "
                    "Збережіть секрет заново: лише сам токен.")
        token = cleaned
    # Діагностика без розкриття значення: довжина й публічний початок (справжній токен — ~108 символів, sk-ant-oat01-)
    log.info("Токен підписки: %d символів, початок «%s»", len(token), token[:13])
    if not token.startswith("sk-ant-oat01-") or not 90 <= len(token) <= 130:
        log.warning("Токен має незвичний вигляд (очікується ~108 символів, початок «sk-ant-oat01-»): "
                    "схоже, його скопійовано не повністю або не той.")
    # Ключ API, якщо він є в оточенні, перебив би токен підписки
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    with tempfile.TemporaryDirectory() as empty_dir:  # порожня папка: без чужих CLAUDE.md і налаштувань
        # Інструкції — через файл, а в аргументах лише ASCII без переносів:
        # на Windows cmd.exe обрізає багаторядкові аргументи і псує кирилицю
        system_file = os.path.join(empty_dir, "system.md")
        with open(system_file, "w", encoding="utf-8") as f:
            f.write(system + "\n\nВідповідай лише JSON-об'єктом за заданою схемою.")
        cmd = shlex.split(os.getenv("CLAUDE_CLI", "claude"))
        cmd[0] = shutil.which(cmd[0]) or cmd[0]
        cmd += [
            "-p",
            "--model", cfg.get("model", "claude-sonnet-5"),
            "--effort", cfg.get("effort", "high"),
            "--system-prompt-file", system_file,
            "--json-schema", json.dumps(schema, ensure_ascii=True, separators=(",", ":")),
            "--output-format", "json",
            # без інструментів економимо ~20k токенів ліміту; для перевірки — лише пошук і читання сторінок
            "--tools", "WebSearch,WebFetch" if web else "",
            *(["--allowedTools", "WebSearch,WebFetch"] if web else []),
            "--permission-mode", "dontAsk",  # усе, що не дозволено явно, автоматично заборонено
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                              env=env, cwd=empty_dir, timeout=2400 if web else 1200)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise LLMError(f"Claude Code завершився з помилкою (код {proc.returncode}):\n"
                       f"{(proc.stderr or proc.stdout)[-1500:]}") from None
    if data.get("is_error") or proc.returncode != 0:
        raise LLMError(f"Claude Code: {data.get('subtype')} — {str(data.get('result'))[:1000]}\n"
                       "Якщо це ліміт підписки — запустіть пізніше кнопкою Run workflow.")

    usage = data.get("usage") or {}
    log.info("Claude (підписка) %s: вхід %s токенів, вихід %s токенів, кроків %s, %.0f с",
             cfg.get("model"), _input_tokens(usage), usage.get("output_tokens", "?"),
             data.get("num_turns", "?"), (data.get("duration_ms") or 0) / 1000)

    if isinstance(data.get("structured_output"), dict):
        return data["structured_output"]
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(data.get("result", "")).strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Не вдалося розібрати JSON відповіді: {exc}\n{text[:500]}") from exc


def _input_tokens(usage: dict) -> int:
    return sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


# ── API: ключ з окремим балансом ──────────────────────────────

def _via_api(cfg: dict, system: str, user: str, schema: dict) -> dict:
    import anthropic

    model = cfg.get("model", "claude-opus-5")
    client = anthropic.Anthropic(max_retries=4, timeout=900)
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    kwargs = dict(
        model=model,
        max_tokens=64000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if "haiku" not in model:  # Haiku 4.5 не підтримує adaptive thinking та effort
        kwargs["thinking"] = {"type": "adaptive"}
        output_config["effort"] = cfg.get("effort", "high")
    kwargs["output_config"] = output_config
    if model in FALLBACK_MODELS:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["extra_body"] = {"fallbacks": "default"}

    with client.beta.messages.stream(**kwargs) as stream:
        msg = stream.get_final_message()

    _log_api_usage(msg)
    if msg.stop_reason == "refusal":
        raise LLMError(f"Модель відмовилась відповідати: {getattr(msg, 'stop_details', None)}")
    if msg.stop_reason == "max_tokens":
        raise LLMError("Відповідь обрізана (max_tokens) — зменшіть max_items у config.yaml")

    blocks = list(msg.content)
    last_fallback = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
    text = "".join(b.text for b in blocks[last_fallback + 1 :] if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Не вдалося розібрати JSON відповіді: {exc}\n{text[:500]}") from exc


def _log_api_usage(msg) -> None:
    u = msg.usage
    price_in, price_out = PRICES.get(msg.model, PRICES.get("claude-opus-5"))
    cost = u.input_tokens / 1e6 * price_in + u.output_tokens / 1e6 * price_out
    log.info("Claude %s: вхід %d токенів, вихід %d токенів ≈ $%.2f", msg.model, u.input_tokens, u.output_tokens, cost)
