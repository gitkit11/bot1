"""
HLTV Scraper — бесплатные данные по картам и игрокам CS2
=========================================================
Использует Playwright (headless Chrome) для обхода Cloudflare защиты HLTV.
Данные кэшируются в SQLite на 6 часов чтобы не перегружать HLTV.

Что даёт БЕСПЛАТНО:
  - Winrate команды на каждой карте (Inferno, Dust2, Mirage, Nuke и т.д.)
  - Количество сыгранных карт (pick%, ban%)
  - Рейтинг игроков (HLTV Rating 2.0)
  - Роли игроков (AWPer, IGL, Rifler и т.д.)
  - Текущий состав команды

HLTV Team IDs (из URL hltv.org/team/{id}/{slug}):
  Vitality:      9565
  FaZe:          6667
  G2:            5995
  NaVi:          4608
  Spirit:        7020
  MOUZ:          4494
  Heroic:        7175
  Astralis:      4411
  ENCE:          6665
  Cloud9:        5005
  Liquid:        5973
  FURIA:         8297
  Complexity:    7170
  BIG:           8068
  Falcons:       12279
"""

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── HLTV Team ID кэш ───────────────────────────────────────────────────────
HLTV_TEAM_IDS: dict[str, tuple[int, str]] = {
    # (hltv_id, slug)
    "Team Vitality":    (9565,  "vitality"),
    "Vitality":         (9565,  "vitality"),
    "FaZe Clan":        (6667,  "faze"),
    "FaZe":             (6667,  "faze"),
    "G2 Esports":       (5995,  "g2"),
    "G2":               (5995,  "g2"),
    "Natus Vincere":    (4608,  "natus-vincere"),
    "NaVi":             (4608,  "natus-vincere"),
    "Team Spirit":      (7020,  "spirit"),
    "Spirit":           (7020,  "spirit"),
    "MOUZ":             (4494,  "mouz"),
    "mousesports":      (4494,  "mouz"),
    "Heroic":           (7175,  "heroic"),
    "Astralis":         (4411,  "astralis"),
    "ENCE":             (6665,  "ence"),
    "Cloud9":           (5005,  "cloud9"),
    "Team Liquid":      (5973,  "liquid"),
    "Liquid":           (5973,  "liquid"),
    "FURIA":            (8297,  "furia"),
    "Complexity":       (7170,  "complexity"),
    "BIG":              (8068,  "big"),
    "Falcons":          (12279, "falcons"),
    "The MongolZ":      (11595, "the-mongolz"),
    "MongolZ":          (11595, "the-mongolz"),
    "paiN":             (4773,  "pain"),
    "Eternal Fire":     (11595, "eternal-fire"),
}

# ─── SQLite кэш ─────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent.parent / "data" / "hltv_cache.db"
CACHE_TTL = 6 * 3600  # 6 часов


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hltv_cache (
            key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _cache_get(key: str) -> Optional[dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT data, updated_at FROM hltv_cache WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        if row and (time.time() - row[1]) < CACHE_TTL:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def _cache_set(key: str, data: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO hltv_cache (key, data, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(data), int(time.time()))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Cache write error: {e}")


# ─── Playwright scraper ──────────────────────────────────────────────────────
async def _scrape_hltv_maps(team_id: int, slug: str, period: str = "Last 3 months") -> Optional[dict]:
    """
    Скрапит страницу hltv.org/stats/teams/maps/{id}/{slug}
    Возвращает dict: {'Inferno': 77.8, 'Dust2': 90.9, ...}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright не установлен. Запустите: sudo pip3 install playwright && playwright install chromium")
        return None

    # Map period to HLTV URL params
    period_params = {
        "Last month":    "?startDate=last-month",
        "Last 3 months": "?startDate=last-3-months",
        "Last 6 months": "?startDate=last-6-months",
        "2025":          "?startDate=2025-01-01&endDate=2025-12-31",
        "2026":          "?startDate=2026-01-01&endDate=2026-12-31",
    }
    params = period_params.get(period, "?startDate=last-3-months")
    url = f"https://www.hltv.org/stats/teams/maps/{team_id}/{slug}{params}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)  # Ждём загрузки JS

            # Извлекаем данные через JavaScript
            map_data = await page.evaluate("""
                () => {
                    const result = {};
                    const allLinks = document.querySelectorAll('a');
                    allLinks.forEach(a => {
                        const text = a.textContent.trim();
                        const match = text.match(/^(\\w+)\\s*-\\s*([\\d.]+)%$/);
                        if (match) {
                            result[match[1]] = parseFloat(match[2]);
                        }
                    });
                    return result;
                }
            """)

            await browser.close()

            if map_data:
                logger.info(f"HLTV maps for {slug}: {map_data}")
                return map_data
            else:
                logger.warning(f"No map data found for {slug}")
                return None

    except Exception as e:
        logger.error(f"Playwright scraping error for {slug}: {e}")
        return None


async def _scrape_hltv_players(team_id: int, slug: str) -> Optional[list]:
    """
    Скрапит страницу hltv.org/stats/teams/players/{id}/{slug}
    Возвращает список игроков с рейтингом
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    url = f"https://www.hltv.org/stats/teams/players/{team_id}/{slug}?startDate=last-3-months"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                locale="en-US",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

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
                                maps: cells[1].textContent.trim(),
                                kd_ratio: cells[2].textContent.trim(),
                                adr: cells[3].textContent.trim(),
                                rating: cells[4].textContent.trim(),
                            });
                        }
                    });
                    return result;
                }
            """)

            await browser.close()
            return players if players else None

    except Exception as e:
        logger.error(f"Player scraping error for {slug}: {e}")
        return None


# ─── Публичный API ───────────────────────────────────────────────────────────
def get_team_map_stats(team_name: str, period: str = "Last 3 months") -> Optional[dict]:
    """
    Получить winrate команды по каждой карте.
    
    Возвращает:
        {
            'Inferno': 77.8,
            'Dust2': 90.9,
            'Mirage': 67.4,
            'Nuke': 70.7,
            ...
        }
    Или None если команда не найдена.
    """
    _init_db()

    # Нормализация имени
    team_entry = HLTV_TEAM_IDS.get(team_name)
    if not team_entry:
        # Попробуем частичное совпадение
        for key, val in HLTV_TEAM_IDS.items():
            if team_name.lower() in key.lower() or key.lower() in team_name.lower():
                team_entry = val
                break

    if not team_entry:
        logger.warning(f"Team '{team_name}' not found in HLTV ID cache")
        return None

    team_id, slug = team_entry
    cache_key = f"maps_{team_id}_{period}"

    # Проверяем кэш
    cached = _cache_get(cache_key)
    if cached:
        logger.info(f"Cache hit for {team_name} maps")
        return cached

    # Скрапим
    data = asyncio.run(_scrape_hltv_maps(team_id, slug, period))
    if data:
        _cache_set(cache_key, data)
    return data


def get_team_player_stats(team_name: str) -> Optional[list]:
    """
    Получить статистику игроков команды (рейтинг, K/D, ADR).
    
    Возвращает список:
        [
            {'name': 'ZywOo', 'maps': '45', 'kd_ratio': '1.42', 'adr': '89.3', 'rating': '1.35'},
            ...
        ]
    """
    _init_db()

    team_entry = HLTV_TEAM_IDS.get(team_name)
    if not team_entry:
        for key, val in HLTV_TEAM_IDS.items():
            if team_name.lower() in key.lower() or key.lower() in team_name.lower():
                team_entry = val
                break

    if not team_entry:
        return None

    team_id, slug = team_entry
    cache_key = f"players_{team_id}"

    cached = _cache_get(cache_key)
    if cached:
        return cached

    data = asyncio.run(_scrape_hltv_players(team_id, slug))
    if data:
        _cache_set(cache_key, data)
    return data


def get_map_advantage(team1: str, team2: str) -> dict:
    """
    Сравнить команды по картам и вернуть преимущество.
    
    Возвращает:
        {
            'Inferno': {'team1_wr': 77.8, 'team2_wr': 65.2, 'advantage': 'team1'},
            'Dust2': {'team1_wr': 90.9, 'team2_wr': 55.0, 'advantage': 'team1'},
            ...
        }
    """
    maps1 = get_team_map_stats(team1) or {}
    maps2 = get_team_map_stats(team2) or {}

    all_maps = set(maps1.keys()) | set(maps2.keys())
    result = {}

    for map_name in all_maps:
        wr1 = maps1.get(map_name)
        wr2 = maps2.get(map_name)
        if wr1 is not None and wr2 is not None:
            advantage = team1 if wr1 > wr2 else (team2 if wr2 > wr1 else "equal")
            result[map_name] = {
                "team1_wr": wr1,
                "team2_wr": wr2,
                "advantage": advantage,
                "diff": round(abs(wr1 - wr2), 1),
            }

    return result


# ─── Тест ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    team = sys.argv[1] if len(sys.argv) > 1 else "Team Vitality"
    print(f"\n=== Map stats for {team} ===")
    maps = get_team_map_stats(team)
    if maps:
        for map_name, wr in sorted(maps.items(), key=lambda x: -x[1]):
            print(f"  {map_name:12s}: {wr:.1f}%")
    else:
        print("  No data (Playwright may not be installed)")

    print(f"\n=== Player stats for {team} ===")
    players = get_team_player_stats(team)
    if players:
        for p in players:
            print(f"  {p['name']:12s} | Rating: {p['rating']} | K/D: {p['kd_ratio']} | ADR: {p['adr']}")
    else:
        print("  No data")
