"""Агент-наглядач: перевіряє, чи вийшов сьогоднішній дайджест, і якщо ні — запускає його сам.

Працює через GitHub API (змінні GITHUB_TOKEN і GITHUB_REPOSITORY, їх дає GitHub Actions).
Логіка:
  - випуск за сьогодні вже в архіві          → нічого не робить (✅ надіслав сам дайджест);
  - дайджест саме генерується (< HUNG_MIN)   → чекає, нічого не робить;
  - запуск висить довше HUNG_MIN хвилин      → зупиняє його, запускає заново, пише ⚠️;
  - сьогодні вже MAX_ATTEMPTS невдалих спроб → не запускає, пише ❌ (потрібна людина);
  - інакше                                   → запускає дайджест, пише 🔄.
"""
import logging
import os
import time
from datetime import datetime, timezone

import requests

from . import hub

log = logging.getLogger(__name__)
API = "https://api.github.com"
WORKFLOW = "daily.yml"
HUNG_MIN = 25
MAX_ATTEMPTS = 3
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}


class GitHub:
    def __init__(self) -> None:
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                        "Accept": "application/vnd.github+json"}

    def get(self, path: str, **params) -> requests.Response:
        return requests.get(f"{API}/repos/{self.repo}{path}", headers=self.headers, params=params, timeout=30)

    def post(self, path: str, body: dict | None = None) -> requests.Response:
        resp = requests.post(f"{API}/repos/{self.repo}{path}", headers=self.headers, json=body or {}, timeout=30)
        resp.raise_for_status()
        return resp

    def published(self, day) -> bool:
        return self.get(f"/contents/archive/daily/{day.year}/{day.isoformat()}.json").status_code == 200

    def runs_today(self, day) -> list[dict]:
        resp = self.get(f"/actions/workflows/{WORKFLOW}/runs", per_page=30, created=f">={day.isoformat()}")
        resp.raise_for_status()
        return resp.json()["workflow_runs"]

    def start(self) -> None:
        self.post(f"/actions/workflows/{WORKFLOW}/dispatches", {"ref": "main"})


def age_minutes(run: dict) -> float:
    started = datetime.fromisoformat((run.get("run_started_at") or run["created_at"]).replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - started).total_seconds() / 60


def run(today) -> None:
    gh = GitHub()
    if gh.published(today):
        log.info("Дайджест за %s уже вийшов — усе гаразд.", today)
        return

    runs = gh.runs_today(today)
    active = [r for r in runs if r["status"] in ACTIVE]
    for r in active:
        if age_minutes(r) < HUNG_MIN:
            log.info("Дайджест саме генерується (%.0f хв) — чекаю, втручатися не треба.", age_minutes(r))
            return
    for r in active:  # усі активні запуски — завислі
        gh.post(f"/actions/runs/{r['id']}/cancel")
        log.warning("Запуск %s висить %.0f хв — зупинено.", r["id"], age_minutes(r))

    failed = [r for r in runs if r["conclusion"] in ("failure", "timed_out", "cancelled")]
    if len(failed) >= MAX_ATTEMPTS:
        hub.notify(f"❌ Дайджест не вийшов, невдалих спроб сьогодні: {len(failed)}. "
                   "Автоматично більше не перезапускаю — потрібно глянути журнал.",
                   hub.button("📄 Останній запуск", failed[0]["html_url"]),
                   hub.button("▶️ Запустити вручну", hub.workflow_url(WORKFLOW)))
        return

    before = datetime.now(timezone.utc)
    try:
        gh.start()
    except requests.RequestException as exc:
        hub.notify(f"❌ Дайджест не вийшов, і запустити його не вдалося: <code>{exc}</code>",
                   hub.button("▶️ Запустити вручну", hub.workflow_url(WORKFLOW)))
        raise

    new_run = None
    for _ in range(12):  # до ~2 хв чекаємо, поки GitHub створить запуск
        time.sleep(10)
        fresh = [r for r in gh.runs_today(today)
                 if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= before.replace(microsecond=0)]
        if fresh:
            new_run = fresh[0]
            break

    if active:
        text = f"⚠️ Запуск дайджесту завис (понад {HUNG_MIN} хв) — зупинив і запустив заново. Вийде за ~5 хв."
    else:
        text = "🔄 Дайджест не вийшов вчасно — запустив сам. Вийде за ~5 хв."
    if not new_run:
        text += "\nАле GitHub поки не підтвердив запуск — перевір за кнопкою нижче."
    hub.notify(text, hub.button("📄 Стежити за запуском", new_run and new_run["html_url"]),
               hub.button("▶️ Сторінка запуску", None if new_run else hub.workflow_url(WORKFLOW)))
