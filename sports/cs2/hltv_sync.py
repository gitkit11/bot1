"""
HLTV Sync — синхронный модуль для получения статистики HLTV без asyncio конфликтов.
Использует кэширование и fallback на статические данные.
"""

import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к кэшу
CACHE_FILE = Path(__file__).parent.parent.parent / "hltv_cache.json"

# Статический кэш (Fallback)
STATIC_MAP_STATS = {
    "Team Vitality": {"Inferno": 77.8, "Dust2": 90.9, "Mirage": 67.4, "Nuke": 70.7, "Train": 68.2, "Overpass": 77.8, "Anubis": 75.0, "Ancient": 50.0},
    "G2 Esports": {"Inferno": 55.6, "Dust2": 60.0, "Mirage": 66.7, "Nuke": 50.0, "Overpass": 57.1, "Anubis": 62.5, "Ancient": 45.0},
    "FaZe Clan": {"Inferno": 50.0, "Dust2": 55.6, "Mirage": 52.4, "Nuke": 47.1, "Overpass": 60.0, "Anubis": 53.3, "Ancient": 50.0},
    "Natus Vincere": {"Inferno": 58.3, "Dust2": 50.0, "Mirage": 61.5, "Nuke": 54.5, "Overpass": 55.6, "Anubis": 57.1, "Ancient": 60.0},
    "Team Spirit": {"Inferno": 65.0, "Dust2": 70.0, "Mirage": 60.0, "Nuke": 72.7, "Overpass": 62.5, "Anubis": 58.3, "Ancient": 55.0},
}

STATIC_PLAYER_STATS = {
    "Team Vitality": [{"name": "ZywOo", "rating": 1.35}, {"name": "apEX", "rating": 1.05}, {"name": "flameZ", "rating": 1.12}, {"name": "mezii", "rating": 1.08}, {"name": "Spinx", "rating": 1.15}],
    "G2 Esports": [{"name": "m0NESY", "rating": 1.28}, {"name": "NiKo", "rating": 1.22}, {"name": "huNter-", "rating": 1.10}, {"name": "MalbsMd", "rating": 1.15}, {"name": "Snax", "rating": 1.02}],
    "FaZe Clan": [{"name": "karrigan", "rating": 0.97}, {"name": "rain", "rating": 1.08}, {"name": "broky", "rating": 1.15}, {"name": "frozen", "rating": 1.12}, {"name": "ropz", "rating": 1.14}],
    "Natus Vincere": [{"name": "iM", "rating": 1.12}, {"name": "w0nderful", "rating": 1.18}, {"name": "jL", "rating": 1.15}, {"name": "b1t", "rating": 1.10}, {"name": "Aleksib", "rating": 1.02}],
    "Team Spirit": [{"name": "donk", "rating": 1.38}, {"name": "chopper", "rating": 1.02}, {"name": "zont1x", "rating": 1.15}, {"name": "shalfey", "rating": 1.10}, {"name": "magixx", "rating": 1.05}],
}

TEAM_ALIASES = {
    "Vitality": "Team Vitality",
    "G2": "G2 Esports",
    "FaZe": "FaZe Clan",
    "NaVi": "Natus Vincere",
    "Spirit": "Team Spirit",
    "mousesports": "MOUZ",
    "Liquid": "Team Liquid",
}

def load_cache():
    """Загружает кэш из файла."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки кэша: {e}")
    return {}

def save_cache(data):
    """Сохраняет кэш в файл."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша: {e}")

def get_team_map_stats(team_name: str) -> dict:
    """Получить винрейты команды по картам (с приоритетом: кэш -> статика)."""
    name = TEAM_ALIASES.get(team_name, team_name)
    cache = load_cache()
    
    # Приоритет: Динамический кэш -> Статический кэш
    return cache.get("maps", {}).get(name) or STATIC_MAP_STATS.get(name, {})

def get_player_stats(team_name: str) -> list:
    """Получить статистику игроков команды."""
    name = TEAM_ALIASES.get(team_name, team_name)
    cache = load_cache()
    return cache.get("players", {}).get(name) or STATIC_PLAYER_STATS.get(name, [])

def update_team_stats(team_name: str, maps: dict = None, players: list = None):
    """Обновляет динамический кэш для команды."""
    name = TEAM_ALIASES.get(team_name, team_name)
    cache = load_cache()
    
    if "maps" not in cache:
        cache["maps"] = {}
    if "players" not in cache:
        cache["players"] = {}
    
    if maps:
        cache["maps"][name] = maps
    if players:
        cache["players"][name] = players
    
    save_cache(cache)

def format_map_stats_for_ai(home_team: str, away_team: str) -> str:
    """Форматирует статистику карт для ИИ-анализа."""
    h_maps = get_team_map_stats(home_team)
    a_maps = get_team_map_stats(away_team)
    
    if not h_maps and not a_maps:
        return "Статистика карт HLTV недоступна."
    
    res = "🗺 Статистика карт (HLTV Winrate):\n"
    all_maps = set(list(h_maps.keys()) + list(a_maps.keys()))
    for m in sorted(all_maps):
        h_wr = h_maps.get(m, "—")
        a_wr = a_maps.get(m, "—")
        res += f"  • {m}: {home_team} {h_wr}% vs {a_wr}% {away_team}\n"
    return res

def format_players_for_ai(home_team: str, away_team: str) -> str:
    """Форматирует статистику игроков для ИИ-анализа."""
    h_players = get_player_stats(home_team)
    a_players = get_player_stats(away_team)
    
    if not h_players and not a_players:
        return "Статистика игроков HLTV недоступна."
    
    res = "👥 Ключевые игроки (HLTV Rating):\n"
    if h_players:
        h_str = ", ".join([f"{p['name']} ({p['rating']})" for p in h_players])
        res += f"  🔹 {home_team}: {h_str}\n"
    if a_players:
        a_str = ", ".join([f"{p['name']} ({p['rating']})" for p in a_players])
        res += f"  🔸 {away_team}: {a_str}\n"
    return res
