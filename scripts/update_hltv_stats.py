"""
scripts/update_hltv_stats.py — Ежедневное обновление статистики HLTV
=====================================================================
Использует Playwright для обхода Cloudflare.
Обновляет winrate по картам и статистику игроков.

Запуск:
    python3.11 scripts/update_hltv_stats.py
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

async def scrape_team_maps(page, team_id: int, slug: str) -> dict | None:
    url = f"https://www.hltv.org/stats/teams/maps/{team_id}/{slug}?startDate=last-3-months"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        map_data = await page.evaluate("""
            () => {
                const result = {};
                document.querySelectorAll('.stats-table tbody tr').forEach(row => {
                    const mapNameEl = row.querySelector('.stats-table-map-name');
                    const winRateEl = row.querySelector('.stats-table-win-rate');
                    if (mapNameEl && winRateEl) {
                        const name = mapNameEl.textContent.trim();
                        const wr = parseFloat(winRateEl.textContent.replace('%', ''));
                        if (!isNaN(wr)) result[name] = wr;
                    }
                });
                return result;
            }
        """)
        return map_data if map_data else None
    except Exception as e:
        logger.error(f"  ❌ Maps {slug}: {e}")
        return None

async def scrape_team_players(page, team_id: int, slug: str) -> list | None:
    url = f"https://www.hltv.org/stats/teams/players/{team_id}/{slug}?startDate=last-3-months"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        players = await page.evaluate("""
            () => {
                const result = [];
                document.querySelectorAll('table.stats-table tbody tr').forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 5) {
                        const nameEl = cells[0].querySelector('a');
                        result.push({
                            name: nameEl ? nameEl.textContent.trim() : cells[0].textContent.trim(),
                            rating: parseFloat(cells[4].textContent.trim()) || 0,
                        });
                    }
                });
                return result;
            }
        """)
        return players if players else None
    except Exception as e:
        logger.error(f"  ❌ Players {slug}: {e}")
        return None

def generate_hltv_stats_file(map_stats: dict, player_stats: dict, update_date: str) -> str:
    content = f'"""\nHLTV Stats — Автоматически обновляемые данные\nДата обновления: {update_date}\n"""\n\n'
    
    # MAP_STATS
    content += "MAP_STATS: dict[str, dict[str, float]] = {\n"
    for team, maps in map_stats.items():
        content += f'    "{team}": {json.dumps(maps)},\n'
    content += "}\n\n"
    
    # PLAYER_STATS
    content += "PLAYER_STATS: dict[str, list[dict]] = {\n"
    for team, players in player_stats.items():
        content += f'    "{team}": {json.dumps(players)},\n'
    content += "}\n"
    
    return content

async def run_update():
    from playwright.async_api import async_playwright
    update_date = datetime.now().strftime("%Y-%m-%d")
    
    map_results = {}
    player_results = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        for team_name, team_id, slug in TEAMS_TO_UPDATE:
            logger.info(f"Updating {team_name}...")
            
            maps = await scrape_team_maps(page, team_id, slug)
            if maps: map_results[team_name] = maps
            
            await asyncio.sleep(2)
            
            players = await scrape_team_players(page, team_id, slug)
            if players: player_results[team_name] = players
            
            await asyncio.sleep(2)
            
        await browser.close()
        
    if map_results or player_results:
        stats_file = PROJECT_ROOT / "sports" / "cs2" / "hltv_stats.py"
        new_content = generate_hltv_stats_file(map_results, player_results, update_date)
        stats_file.write_text(new_content, encoding="utf-8")
        logger.info(f"✅ hltv_stats.py updated")
        return True
    return False

if __name__ == "__main__":
    asyncio.run(run_update())
