"""
scripts/update_hltv_stats.py — Ежедневное обновление статистики HLTV
=====================================================================
Использует cloudscraper для обхода базовых проверок Cloudflare без браузера.
Обновляет winrate по картам и статистику игроков.

Запуск:
    python3.11 scripts/update_hltv_stats.py
"""

import json
import logging
import os
import sys
import time
import re
from datetime import datetime
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import cloudscraper
except ImportError:
    print("Ошибка: Библиотека cloudscraper не установлена. Выполните: pip install cloudscraper")
    sys.exit(1)

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

MAPS = ["Mirage", "Nuke", "Inferno", "Ancient", "Anubis", "Vertigo", "Dust2"]

def get_team_data(team_id: int, slug: str):
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    
    # Пытаемся получить данные через API-зеркало или напрямую с HLTV (через cloudscraper)
    # 1. Получаем карты (за последние 3 месяца)
    map_url = f"https://www.hltv.org/stats/teams/maps/{team_id}/{slug}?startDate=last-3-months"
    # 2. Получаем игроков (за последние 3 месяца)
    player_url = f"https://www.hltv.org/stats/teams/players/{team_id}/{slug}?startDate=last-3-months"
    
    map_stats = {}
    player_stats = []
    
    try:
        # Парсинг карт
        response = scraper.get(map_url, timeout=15)
        if response.status_code == 200:
            html = response.text
            for m in MAPS:
                # Ищем винрейт в HTML (упрощенный поиск регулярками)
                pattern = rf'<div class="stats-table-map-name">{m}</div>.*?<div class="stats-table-win-rate">(.*?)%</div>'
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        map_stats[m] = float(match.group(1).strip())
                    except:
                        pass
        
        time.sleep(2) # Пауза между запросами
        
        # Парсинг игроков
        response = scraper.get(player_url, timeout=15)
        if response.status_code == 200:
            html = response.text
            # Ищем имена и рейтинги игроков
            # Паттерн: <a href="/stats/players/ID/NAME">NAME</a></td>...<td class="ratingColumn">RATING</td>
            player_pattern = r'<td><a href="/stats/players/\d+/.*?">(.*?)</a></td>.*?<td class=".*?ratingColumn.*?">(.*?)</td>'
            matches = re.findall(player_pattern, html, re.DOTALL)
            for name, rating in matches:
                try:
                    player_stats.append({"name": name, "rating": float(rating)})
                except:
                    pass
                    
        return map_stats, player_stats
    except Exception as e:
        logger.error(f"Ошибка при получении данных для {slug}: {e}")
        return None, None

def generate_hltv_stats_file(map_results: dict, player_results: dict, update_date: str) -> str:
    content = f'"""\nHLTV Stats — Автоматически обновляемые данные\nДата обновления: {update_date}\n"""\n\n'
    
    content += "MAP_STATS: dict[str, dict[str, float]] = {\n"
    for team, maps in map_results.items():
        content += f'    "{team}": {json.dumps(maps)},\n'
    content += "}\n\n"
    
    content += "PLAYER_STATS: dict[str, list[dict]] = {\n"
    for team, players in player_results.items():
        content += f'    "{team}": {json.dumps(players)},\n'
    content += "}\n\n"
    
    content += "TEAM_ALIASES: dict[str, str] = {\n"
    content += '    "Vitality": "Team Vitality",\n'
    content += '    "G2": "G2 Esports",\n'
    content += '    "FaZe": "FaZe Clan",\n'
    content += '    "NaVi": "Natus Vincere",\n'
    content += '    "Spirit": "Team Spirit",\n'
    content += '    "mousesports": "MOUZ",\n'
    content += '    "Liquid": "Team Liquid",\n'
    content += "}\n"
    
    return content

def run_update():
    update_date = datetime.now().strftime("%Y-%m-%d")
    map_results = {}
    player_results = {}
    
    # Загружаем текущие данные (на случай, если API не отдаст часть данных)
    stats_file = PROJECT_ROOT / "sports" / "cs2" / "hltv_stats.py"
    
    for team_name, team_id, slug in TEAMS_TO_UPDATE:
        logger.info(f"Обновление {team_name} (ID: {team_id})...")
        maps, players = get_team_data(team_id, slug)
        
        if maps:
            map_results[team_name] = maps
            logger.info(f"  ✅ Карты: {len(maps)} шт.")
        if players:
            player_results[team_name] = players
            logger.info(f"  ✅ Игроки: {len(players)} чел.")
            
        time.sleep(3) # Безопасная пауза
        
    if map_results or player_results:
        new_content = generate_hltv_stats_file(map_results, player_results, update_date)
        stats_file.write_text(new_content, encoding="utf-8")
        logger.info(f"✅ Файл hltv_stats.py успешно обновлен!")
        return True
    else:
        logger.error("❌ Не удалось получить данные. Проверьте соединение или VPN.")
        return False

if __name__ == "__main__":
    run_update()
