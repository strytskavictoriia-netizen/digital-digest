"""Дайджест у Telegram.

    python -m digest daily   [--dry-run] [--force]   щоденний випуск
    python -m digest weekly  [--dry-run] [--force]   тижневий підсумок
    python -m digest publish-preview                 опублікувати останній dry-run і записати в архів

    python -m digest sources                         перевірити всі джерела (без Claude і Telegram)
    python -m digest check-source <посилання>        визначити тип джерела і показати, що воно дає
    python -m digest add-source <посилання> [--name "Назва"]   перевірити й додати джерело в config.yaml

    python -m digest find-chat                       знайти ID каналу / чату (за токеном з .env)
    python -m digest test-telegram                   тестове повідомлення в канал
    python -m digest telegraph-setup                 створити акаунт Telegraph для сторінок новин
    python -m digest watchdog                        наглядач: чи вийшов сьогоднішній випуск (на GitHub)
"""
import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from . import hub, llm, render, telegram, telegraph, watchdog
from .sources import collect, detect, normalize_url, preview_source

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
ARCHIVE = ROOT / "archive"
SEEN_FILE = ROOT / "state" / "seen.json"
OUT = ROOT / "out"
KYIV = ZoneInfo("Europe/Kyiv")
SEEN_KEEP_DAYS = 21

log = logging.getLogger("digest")


# ── Допоміжне ─────────────────────────────────────────────────

def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cfg["format"] = cfg.get("format") or {}
    cfg["sources"] = cfg.get("sources") or []
    cfg.setdefault("title", "Дайджест")
    cfg.setdefault("emoji", "🗞")
    # назва дайджесту — у сповіщеннях центру агентів і підписі на сторінках Telegraph
    hub.AGENT = f"{cfg['emoji']} <b>{cfg['title']}</b>"
    telegraph.AUTHOR = cfg["title"]
    return cfg


def fmt(cfg: dict, key: str, default):
    return cfg["format"].get(key, default)


def env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"Не задано змінну {name} (локально — у файлі .env, на GitHub — у Secrets)")
    return value


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def daily_path(day: date) -> Path:
    return ARCHIVE / "daily" / str(day.year) / f"{day.isoformat()}.json"


def right_time(now: datetime) -> bool:
    """За розкладом GitHub запускає нас кілька разів поспіль (запуски запізнюються, а іноді губляться).
    Публікує перший запуск після MIN_KYIV_HOUR за Києвом, наступні побачать готовий випуск в архіві й пропустять."""
    min_hour = os.getenv("MIN_KYIV_HOUR")
    if min_hour and now.hour < int(min_hour):
        log.info("Зараз у Києві %s, публікуємо не раніше %s:00 — пропускаю.", now.strftime("%H:%M"), min_hour)
        return False
    return True


def extras(cfg: dict) -> str:
    """Додаткові правила промпту залежно від увімкнених можливостей."""
    rules = []
    if any(s.get("tier") for s in cfg["sources"]):
        rules.append(
            "**Рівні довіри джерел.** Перед назвою джерела в матеріалах стоїть рівень: T1 — офіційні (блоги платформ, "
            "документація, звітність), T2 — топ-журналістика й галузева преса, T3 — дослідницькі й data-компанії, "
            "T4 — інсайдери й аналітики, UA — українські джерела. Новина йде у випуск, лише якщо її підтримує хоча б одне "
            "джерело T1–T3 (або UA). Матеріал лише з T4 — тільки з підтвердженням іншим джерелом. Vendor-матеріал "
            "і SEO-блог — це не два незалежні джерела. Якщо ключову цифру не вдалося підтвердити другим незалежним "
            "джерелом, додай у `details` окремий абзац, що починається з «⚠️ Не підтверджено:», і поясни чому.")
    if cfg.get("reference"):
        rules.append(
            "**Довідник.** Нижче в матеріалах є довідник сталих фактів (ставки, умови, політики). Те, що вже є в "
            "довіднику, — НЕ новина, не подавай його як свіже. Новина — це ЗМІНА чогось із довідника або новий факт; "
            "у такому разі прямо скажи, що змінилося порівняно з довідником.")
    if fmt(cfg, "tests", False):
        rules.append(
            "**`tests` — «Що протестувати».** 2–4 конкретні гіпотези, що випливають із матеріалу ЦЬОГО випуску: що "
            "саме перевірити, на чому, яку метрику дивитись. По одному-два речення. Тут можна згадувати компанію читачів.")
    else:
        rules.append("`tests` — поверни порожній список.")
    if fmt(cfg, "rejected_footer", False):
        rules.append(
            "**`rejected` — що перевірили й відкинули.** 3–8 помітних тем із матеріалів, які ти свідомо НЕ включив: "
            "`topic` — коротко, що це було; `reason` — чому відкинуто (чорний список, не свіже, без наслідку для нас, "
            "не підтверджено, повтор сюжету). Без назви компанії читачів — це піде на публічну сторінку.")
    else:
        rules.append("`rejected` — поверни порожній список.")
    return "\n\n".join(rules)


def prompt(name: str, cfg: dict) -> str:
    rubrics = "\n".join(f"- `{r['id']}` — {r['emoji']} {r['title']}: {r.get('hint', '')}" for r in cfg["rubrics"])
    return (
        (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        .replace("{{title}}", cfg["title"])
        .replace("{{language}}", cfg.get("language", "українська"))
        .replace("{{topic}}", cfg.get("topic", "").strip())
        .replace("{{audience}}", cfg["audience"].strip())
        .replace("{{rubrics}}", rubrics)
        .replace("{{max_items}}", str(fmt(cfg, "max_items", 12)))
        .replace("{{extras}}", extras(cfg))
    )


def reference_text(cfg: dict) -> str:
    path = cfg.get("reference")
    if not path or not (ROOT / path).exists():
        return ""
    return f"## Довідник сталих фактів (не новина; зміна — новина)\n\n{(ROOT / path).read_text(encoding='utf-8').strip()}\n\n"


def resolve_links(ids: list[str], by_id: dict[str, list[dict]]) -> list[dict]:
    links, urls = [], set()
    for i in ids:
        for link in by_id.get(i, []):
            if link["url"] not in urls:
                urls.add(link["url"])
                links.append(link)
    return links[:3]


def str_array() -> dict:
    return {"type": "array", "items": {"type": "string"}}


def obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def item_schema(cfg: dict) -> dict:
    text = {"type": "string"}
    return obj({
        "rubric": {"type": "string", "enum": [r["id"] for r in cfg["rubrics"]]},
        "title": text, "summary": text, "teaser": text,
        "importance": {"type": "integer", "enum": [2, 3]},
        "details": text, "recommendations": str_array(), "source_ids": str_array(),
    })


def preview(messages: list[str], markdown: str, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.md").write_text(markdown, encoding="utf-8")
    (OUT / f"{name}-telegram.txt").write_text("\n\n════════ наступне повідомлення ════════\n\n".join(messages), encoding="utf-8")
    log.info("Dry-run: %d повідомлень. Перегляд: out/%s.md", len(messages), name)


@contextmanager
def reporting(what: str, workflow: str, enabled: bool):
    """Якщо робота впала — сповіщення ❌ у центр агентів (і позначка, щоб workflow не дублював його)."""
    try:
        yield
    except BaseException as exc:
        if enabled and not isinstance(exc, KeyboardInterrupt):
            hub.notify_failure(what, exc, workflow)
            OUT.mkdir(exist_ok=True)
            (OUT / "notified").touch()
        raise


# ── Щоденний дайджест ─────────────────────────────────────────

def telegraph_pages(result: dict, cfg: dict, day: date, title: str, prefix: str = "") -> None:
    """layout: items — сторінка на кожну новину (якщо item_pages); issue — одна сторінка на весь випуск."""
    issue = fmt(cfg, "layout", "items") == "issue"
    if not (issue or fmt(cfg, "item_pages", True)):
        return
    token = os.getenv("TELEGRAPH_TOKEN", "").strip()
    if not token:
        log.warning("TELEGRAPH_TOKEN не задано — випуск буде без сторінок Telegraph")
        return
    if issue:
        result["page"] = telegraph.publish_issue(token, title, result, cfg)
    else:
        telegraph.publish_items(token, result["items"], cfg["rubrics"], day, prefix)


def publish_daily(result: dict, cfg: dict, day: date) -> None:
    """Сторінки Telegraph, потім одне повідомлення в канал."""
    telegraph_pages(result, cfg, day, f"{cfg['title']} · {render.human_date(day)}")
    telegram.send_messages(env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID"), render.daily_telegram(result, cfg, day))


def run_daily(dry_run: bool, force: bool) -> None:
    cfg = load_config()
    now = datetime.now(KYIV)
    if not (force or dry_run) and not right_time(now):
        return
    today = now.date()
    if daily_path(today).exists() and not (force or dry_run):
        log.info("Випуск за %s уже опубліковано — пропускаю (використайте --force для повтору).", today)
        return

    with reporting("Випуск", "daily.yml", enabled=not dry_run):
        count = make_daily(cfg, today, dry_run)
    if not dry_run:
        hub.notify(f"✅ Випуск вийшов о {datetime.now(KYIV):%H:%M} · новин: {count}")
        hub.ping()


def make_daily(cfg: dict, today: date, dry_run: bool) -> int:
    """Збирає, генерує і публікує випуск. Повертає кількість новин."""
    seen: dict[str, str] = read_json(SEEN_FILE, {})
    since = datetime.now(timezone.utc) - timedelta(hours=cfg.get("lookback_hours", 30))
    items, errors = collect(cfg["sources"], since, set(seen))
    log.info("Зібрано %d нових матеріалів, недоступних джерел: %d", len(items), len(errors))
    if not items:
        raise SystemExit("Не зібрано жодного матеріалу — перевірте джерела")

    recent = []
    for back in range(1, cfg.get("avoid_repeats_days", 3) + 1):
        old = read_json(daily_path(today - timedelta(days=back)), None)
        if old:
            recent += [f"- {it['title']}" for it in old["items"]]

    materials = "\n\n".join(
        f"[{i.id}] {f'[{i.tier}] ' if i.tier else ''}{i.source} | {i.published:%Y-%m-%d %H:%M} UTC\n{i.title}\n{i.summary}".rstrip()
        for i in items
    )
    user = (
        f"Сьогодні {render.human_date(today)}.\n\n"
        f"{reference_text(cfg)}"
        f"## Теми попередніх випусків (не повторювати той самий сюжет)\n{chr(10).join(recent) or '— немає —'}\n\n"
        f"## Матеріали за добу ({len(items)})\n\n{materials}"
    )
    text = {"type": "string"}
    schema = obj({
        "items": {"type": "array", "items": item_schema(cfg)},
        "idea": text,
        "tests": str_array(),
        "rejected": {"type": "array", "items": obj({"topic": text, "reason": text})},
    })
    result = llm.generate_json(cfg, prompt("daily", cfg), user, schema)

    by_id = {i.id: [{"name": i.source.split(" / ")[-1], "url": i.url}] for i in items}
    for it in result["items"]:
        it["links"] = resolve_links(it.pop("source_ids"), by_id)
    result["date"] = today.isoformat()

    if dry_run:
        # адреси зібраних матеріалів — щоб publish-preview міг позначити їх як використані
        write_json(OUT / "daily-preview.json", result | {"_urls": [normalize_url(i.url) for i in items]})
        preview(render.daily_telegram(result, cfg, today), render.daily_markdown(result, cfg, today), "daily-preview")
        return len(result["items"])

    publish_daily(result, cfg, today)
    save_daily(result, cfg, today, [normalize_url(i.url) for i in items])
    log.info("Готово: %d новин опубліковано.", len(result["items"]))
    return len(result["items"])


def save_daily(result: dict, cfg: dict, day: date, urls: list[str]) -> None:
    """Архів випуску + адреси використаних матеріалів: наступні випуски не повторять ці теми."""
    write_json(daily_path(day), result)
    daily_path(day).with_suffix(".md").write_text(render.daily_markdown(result, cfg, day), encoding="utf-8")
    urls += [normalize_url(l["url"]) for it in result["items"] for l in it["links"]]
    stamp, cutoff = day.isoformat(), (day - timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    seen = {u: d for u, d in read_json(SEEN_FILE, {}).items() if d >= cutoff}
    seen.update({u: stamp for u in urls if u not in seen})
    write_json(SEEN_FILE, seen)


# ── Тижневий підсумок ─────────────────────────────────────────

def run_weekly(dry_run: bool, force: bool) -> None:
    cfg = load_config()
    if not fmt(cfg, "weekly", True):
        log.info("Тижневий підсумок вимкнено в config.yaml (format.weekly) — пропускаю.")
        return
    now = datetime.now(KYIV)
    if not (force or dry_run) and not right_time(now):
        return
    end = now.date()
    start = end - timedelta(days=6)
    year, week, _ = end.isocalendar()
    out_path = ARCHIVE / "weekly" / f"{year}-W{week:02d}.json"
    if out_path.exists() and not (force or dry_run):
        log.info("Тижневий підсумок %s уже опубліковано — пропускаю.", out_path.stem)
        return
    with reporting("Тижневий підсумок", "weekly.yml", enabled=not dry_run):
        make_weekly(cfg, start, end, out_path, dry_run)
    if not dry_run:
        hub.notify(f"✅ Тижневий підсумок вийшов о {datetime.now(KYIV):%H:%M}")


def make_weekly(cfg: dict, start: date, end: date, out_path: Path, dry_run: bool) -> None:
    lines, by_id, n = [], {}, 0
    for k in range(7):
        day = start + timedelta(days=k)
        digest = read_json(daily_path(day), None)
        if not digest:
            continue
        for it in digest["items"]:
            n += 1
            by_id[f"w{n}"] = it["links"]
            lines.append(f"[w{n}] {day.isoformat()} · {it['rubric']}\n{it['title']}\n{it.get('summary', '')}\n{it.get('details', '')}")
    if not lines:
        raise SystemExit("За тиждень немає жодного щоденного випуску в архіві")

    schema = obj({
        "headline": {"type": "string"},
        "items": {"type": "array", "items": item_schema(cfg)},
        "trends": str_array(),
        "opportunities": str_array(),
    })
    user = f"Період: {render.human_date(start)} – {render.human_date(end)}.\n\n## Новини тижня ({n})\n\n" + "\n\n".join(lines)
    result = llm.generate_json(cfg, prompt("weekly", cfg), user, schema)
    for it in result["items"]:
        it["links"] = resolve_links(it.pop("source_ids"), by_id)
    result["period"] = [start.isoformat(), end.isoformat()]

    if dry_run:
        write_json(OUT / "weekly-preview.json", result)
        preview(render.weekly_telegram(result, cfg, start, end), render.weekly_markdown(result, cfg, start, end),
                "weekly-preview")
        return

    telegraph_pages(result, cfg, end, f"{cfg['title']}: тиждень · {render.period(start, end)}", prefix="Підсумок тижня · ")
    telegram.send_messages(env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID"), render.weekly_telegram(result, cfg, start, end))
    write_json(out_path, result)
    out_path.with_suffix(".md").write_text(render.weekly_markdown(result, cfg, start, end), encoding="utf-8")
    log.info("Готово: тижневий підсумок опубліковано.")


# ── Джерела ───────────────────────────────────────────────────

def run_sources() -> None:
    cfg = load_config()
    since = datetime.now(timezone.utc) - timedelta(hours=cfg.get("lookback_hours", 30))
    items, errors = collect(cfg["sources"], since, set())
    print(f"\nУсього унікальних матеріалів за {cfg.get('lookback_hours', 30)} год: {len(items)}. "
          f"Недоступні джерела: {len(errors)}")
    for err in errors:
        print("  ✗", err)


def check_source(url: str, name: str | None) -> dict:
    src = detect(url, name)
    items = preview_source(src, days=7)
    print(f"Тип: {src['type']} · Назва: {src['name']}")
    print(f"Матеріалів за 7 днів: {len(items)}")
    for it in items[:5]:
        print(f"  • {it.published:%d.%m} {it.title[:100]}")
    if not items:
        print("⚠️ За тиждень джерело нічого не дало — можливо, воно неактивне або стрічка порожня.")
    return src


def yaml_line(src: dict) -> str:
    """Один рядок для config.yaml — дописуємо в кінець файлу, щоб зберегти коментарі."""
    parts = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in src.items()]
    return "  - {" + ", ".join(parts) + "}\n"


def run_add_source(url: str, name: str | None) -> None:
    cfg = load_config()
    src = check_source(url, name)
    key = src.get("url") or src.get("channel")
    if any(key in (s.get("url"), s.get("channel")) for s in cfg["sources"]):
        print("Це джерело вже є в config.yaml — нічого не змінено.")
        return
    text = CONFIG.read_text(encoding="utf-8")
    CONFIG.write_text(text.rstrip("\n") + "\n" + yaml_line(src), encoding="utf-8")
    load_config()  # перевірка, що файл досі коректний
    print("✅ Додано в config.yaml (sources). Не забудьте відправити зміни на GitHub (git push).")


# ── Сервісні команди ──────────────────────────────────────────

def run_find_chat() -> None:
    chats = telegram.find_chats(env("TELEGRAM_BOT_TOKEN"))
    if not chats:
        print("Бот ще не бачив жодного чату. Додайте бота адміністратором у канал, "
              "опублікуйте в каналі будь-яке повідомлення і запустіть команду ще раз.")
    for cid, kind, name in chats:
        print(f"{kind:10} {cid:>16}  {name}")


def run_publish_preview() -> None:
    """Публікує в канал останній dry-run (out/daily-preview.json) і записує його в архів —
    усе, що побачили читачі, має бути в архіві, інакше наступний випуск це повторить.
    Після цього архів треба відправити на GitHub (git push), щоб його бачив робочий запуск."""
    result = read_json(OUT / "daily-preview.json", None)
    if not result:
        sys.exit("Немає out/daily-preview.json — спершу запустіть: python -m digest daily --dry-run")
    cfg, day = load_config(), date.fromisoformat(result["date"])
    urls = result.pop("_urls", [])
    publish_daily(result, cfg, day)
    if daily_path(day).exists():  # за цей день уже є випуск — дописуємо тестові новини до нього
        old = read_json(daily_path(day), {})
        result = old | {"items": old.get("items", []) + result["items"]}
    save_daily(result, cfg, day, urls)
    print("Випуск опубліковано й записано в архів. Не забудьте відправити архів на GitHub (git push).")


def run_telegraph_setup() -> None:
    """Створює акаунт Telegraph для сторінок новин і записує токен у .env."""
    token = telegraph.create_account()
    env_file = ROOT / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [l for l in lines if not l.startswith("TELEGRAPH_TOKEN=")] + [f"TELEGRAPH_TOKEN={token}"]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Акаунт Telegraph створено, токен записано у .env.\n"
          "Додайте його на GitHub як секрет TELEGRAPH_TOKEN:\n\n" + token)


def run_watchdog() -> None:
    """Агент-наглядач (запускається на GitHub): чи вийшов сьогоднішній випуск, і якщо ні — запускає."""
    load_config()
    now = datetime.now(KYIV)
    if right_time(now):
        watchdog.run(now.date())


def run_test_telegram() -> None:
    cfg = load_config()
    telegram.send_messages(env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID"),
                           [f"✅ <b>Бот підключено.</b> Тут з'являтиметься {cfg['title']}."])
    print("Тестове повідомлення надіслано.")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(prog="digest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["daily", "weekly", "sources", "check-source", "add-source", "find-chat",
                                            "test-telegram", "publish-preview", "telegraph-setup", "watchdog"])
    parser.add_argument("url", nargs="?", help="посилання на джерело (для check-source / add-source)")
    parser.add_argument("--name", help="назва джерела (для add-source)")
    parser.add_argument("--dry-run", action="store_true", help="згенерувати, але не публікувати (результат у out/)")
    parser.add_argument("--force", action="store_true", help="ігнорувати перевірки часу і повторів")
    args = parser.parse_args()
    if args.command in ("check-source", "add-source") and not args.url:
        parser.error("потрібне посилання на джерело")

    commands = {
        "daily": lambda: run_daily(args.dry_run, args.force),
        "weekly": lambda: run_weekly(args.dry_run, args.force),
        "sources": run_sources,
        "check-source": lambda: check_source(args.url, args.name),
        "add-source": lambda: run_add_source(args.url, args.name),
        "find-chat": run_find_chat,
        "test-telegram": run_test_telegram,
        "publish-preview": run_publish_preview,
        "telegraph-setup": run_telegraph_setup,
        "watchdog": run_watchdog,
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
