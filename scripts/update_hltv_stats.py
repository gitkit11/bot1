"""
scripts/update_hltv_stats.py — Ежедневное обновление статистики HLTV
=====================================================================
Использует уже открытый браузер (CDP) чтобы обойти Cloudflare.
Открывает страницы HLTV, считывает данные и обновляет hltv_stats.py.

Запуск:
    python3.11 scripts/update_hltv_stats.py

Автоматически запускается каждый день в 06:00 через планировщик.
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "logs" / "hltv_update.log"),
    ]
)
logger = logging.getLogger(__name__)

# ─── Команды для обновления ──────────────────────────────────────────────────
TEAMS_TO_UPDATE = [
    ("Team Vitality",   9565,  "vitality"),
    ("G2 Esports",      5995,  "g2"),
    ("FaZe Clan",       6667,  "faze"),
    ("Natus Vincere",   4608,  "natus-vincere"),
    ("Team Spirit",     7020,  "spirit"),
    ("MOUZ",            4494,  "mouz"),
    ("Heroic",          7175,  "heroic"),
    ("Astralis",        4411,  "astralis"),
    ("Team Liquid",     5973,  "liquid"),
    ("FURIA",           8297,  "furia"),
    ("The MongolZ",     11595, "the-mongolz"),
    ("Cloud9",          5005,  "cloud9"),
    ("BIG",             8068,  "big"),
    ("Falcons",         12279, "falcons"),
]

# ─── Скрапер через CDP ───────────────────────────────────────────────────────
async def scrape_team_maps(page, team_id: int, slug: str) -> dict | None:
    """Получить winrate по картам для команды через уже открытый браузер."""
    url = f"https://www.hltv.org/stats/teams/maps/{team_id}/{slug}?startDate=last-3-months"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2500)

        title = await page.title()
        if "Just a moment" in title or "Attention Required" in title:
            logger.warning(f"Cloudflare block for {slug}")
            return None

        # Извлекаем winrate по картам
        map_data = await page.evaluate("""
            () => {
                const result = {};
                document.querySelectorAll('a').forEach(a => {
                    const m = a.textContent.trim().match(/^(\\w+)\\s*-\\s*([\\d.]+)%$/);
                    if (m) result[m[1]] = parseFloat(m[2]);
                });
                return result;
            }
        """)

        if map_data and len(map_data) >= 3:
            logger.info(f"  ✅ {slug}: {map_data}")
            return map_data
        else:
            logger.warning(f"  ⚠️ {slug}: недостаточно данных ({map_data})")
            return None

    except Exception as e:
        logger.error(f"  ❌ {slug}: {e}")
        return None


async def scrape_team_players(page, team_id: int, slug: str) -> list | None:
    """Получить статистику игроков команды."""
    url = f"https://www.hltv.org/stats/teams/players/{team_id}/{slug}?startDate=last-3-months"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        title = await page.title()
        if "Just a moment" in title:
            return None

        players = await page.evaluate("""
            () => {
                const result = [];
                const rows = document.querySelectorAll('table.stats-table tbody tr');
                rows.forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 5) {
                        const nameEl = cells[0].querySelector('a');
                        result.push({
                            name: nameEl ? nameEl.textContent.trim() : cells[0].textContent.trim(),
                            maps: parseInt(cells[1].textContent.trim()) || 0,
                            kd: parseFloat(cells[2].textContent.trim()) || 0,
                            adr: parseFloat(cells[3].textContent.trim()) || 0,
                            rating: parseFloat(cells[4].textContent.trim()) || 0,
                        });
                    }
                });
                return result;
            }
        """)

        if players and len(players) >= 3:
            logger.info(f"  ✅ Players {slug}: {[p['name'] for p in players]}")
            return players
        return None

    except Exception as e:
        logger.error(f"  ❌ Players {slug}: {e}")
        return None


# ─── Генератор кода hltv_stats.py ────────────────────────────────────────────
def generate_hltv_stats_file(map_stats: dict, player_stats: dict, update_date: str) -> str:
    """Генерирует содержимое hltv_stats.py с актуальными данными."""

    # Читаем текущий файл чтобы сохранить структуру
    stats_file = PROJECT_ROOT / "sports" / "cs2" / "hltv_stats.py"
    current_content = stats_file.read_text(encoding="utf-8")

    # ── Обновляем MAP_STATS ──────────────────────────────────────────────────
    map_stats_lines = ["MAP_STATS: dict[str, dict[str, float]] = {\n"]
    for team_name, maps in map_stats.items():
        map_stats_lines.append(f'    "{team_name}": {{\n')
        for map_name, wr in sorted(maps.items(), key=lambda x: -x[1]):
            map_stats_lines.append(f'        "{map_name}": {wr},\n')
        map_stats_lines.append("    },\n")
    map_stats_lines.append("}\n")
    new_map_block = "".join(map_stats_lines)

    # Заменяем блок MAP_STATS в файле
    pattern = r"MAP_STATS: dict\[str, dict\[str, float\]\] = \{.*?\n\}"
    new_content = re.sub(pattern, new_map_block.rstrip(), current_content, flags=re.DOTALL)

    # ── Обновляем дату ───────────────────────────────────────────────────────
    new_content = re.sub(
        r"Дата обновления: \d{4}-\d{2}-\d{2}",
        f"Дата обновления: {update_date}",
        new_content
    )

    return new_content


# ─── Основная функция ────────────────────────────────────────────────────────
async def run_update():
    """Запускает обновление всех команд."""
    from playwright.async_api import async_playwright

    update_date = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=== HLTV Update started: {update_date} ===")

    # Создаём папку для логов
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)

    # Загружаем текущие данные как базу (чтобы не потерять если HLTV заблокирует)
    try:
        from sports.cs2.hltv_stats import MAP_STATS as current_map_stats
        map_stats = dict(current_map_stats)
        logger.info(f"Loaded {len(map_stats)} teams from current hltv_stats.py")
    except Exception:
        map_stats = {}
        logger.warning("Could not load current hltv_stats.py, starting fresh")

    updated_count = 0
    blocked_count = 0

    async with async_playwright() as p:
        # Пробуем подключиться к уже открытому браузеру
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = await context.new_page()
            logger.info("Connected to existing browser via CDP")
        except Exception as e:
            logger.warning(f"CDP connection failed ({e}), launching new browser")
            # Запускаем новый браузер (может быть заблокирован Cloudflare)
            browser = await p.chromium.launch(
                headless=False,  # Видимый браузер лучше обходит Cloudflare
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

        # Обновляем каждую команду
        for team_name, team_id, slug in TEAMS_TO_UPDATE:
            logger.info(f"\nUpdating: {team_name} (id={team_id})")

            maps = await scrape_team_maps(page, team_id, slug)
            if maps:
                map_stats[team_name] = maps
                updated_count += 1
            else:
                blocked_count += 1

            # Пауза между запросами (не перегружаем HLTV)
            await asyncio.sleep(3)

        await page.close()

    logger.info(f"\n=== Update complete: {updated_count} updated, {blocked_count} blocked ===")

    # Сохраняем обновлённые данные
    if updated_count > 0:
        stats_file = PROJECT_ROOT / "sports" / "cs2" / "hltv_stats.py"
        new_content = generate_hltv_stats_file(map_stats, {}, update_date)
        stats_file.write_text(new_content, encoding="utf-8")
        logger.info(f"✅ hltv_stats.py updated with {updated_count} teams")
    else:
        logger.warning("⚠️ No teams updated (all blocked by Cloudflare)")

    return updated_count, blocked_count


def main():
    updated, blocked = asyncio.run(run_update())
    print(f"\n✅ Обновлено: {updated} команд | ⚠️ Заблокировано: {blocked}")
    return 0 if updated > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
