"""
api_football.py — Модуль для получения статистики команд через API-Football (v3.football.api-sports.io)
Бесплатный план: 100 запросов/день
"""
import requests
import json
import os
from datetime import datetime, timedelta

try:
    from config import API_FOOTBALL_KEY
except ImportError:
    API_FOOTBALL_KEY = None

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}

# Кэш для экономии запросов (TTL 6 часов)
_stats_cache = {}
CACHE_TTL = 6 * 3600  # секунды

# ID лиг
LEAGUE_IDS = {
    "soccer_epl": 39,
    "soccer_spain_la_liga": 140,
    "soccer_germany_bundesliga": 78,
    "soccer_italy_serie_a": 135,
    "soccer_france_ligue_one": 61,
    "soccer_uefa_champs_league": 2,
    "soccer_uefa_europa_league": 3,
}

# Соответствие названий команд → ID в API-Football (EPL 2024/25)
TEAM_IDS = {
    "Arsenal": 42,
    "Aston Villa": 66,
    "Bournemouth": 35,
    "Brentford": 55,
    "Brighton": 51,
    "Chelsea": 49,
    "Crystal Palace": 52,
    "Everton": 45,
    "Fulham": 36,
    "Ipswich": 57,
    "Leicester": 46,
    "Liverpool": 40,
    "Man City": 50,
    "Man United": 33,
    "Newcastle": 34,
    "Newcastle United": 34,
    "Nott'm Forest": 65,
    "Nottingham Forest": 65,
    "Southampton": 41,
    "Tottenham": 47,
    "Tottenham Hotspur": 47,
    "West Ham": 48,
    "Wolves": 39,
    "Wolverhampton Wanderers": 39,
    "Burnley": 44,
    "Leeds": 63,
    "Leeds United": 63,
    "Sheffield United": 62,
    "Luton": 1359,
    "Watford": 38,
    "Cardiff": 715,
    "Swansea": 381,
    "Stoke": 70,
    "Middlesbrough": 25,
    "Sunderland": 71,
    "QPR": 69,
    "Hull": 322,
    "Huddersfield": 394,
    "Norwich": 71,
    "West Brom": 60,
}


def _get_current_season():
    """Возвращает текущий сезон (год начала)."""
    now = datetime.now()
    return now.year if now.month >= 7 else now.year - 1


def _cache_get(key):
    """Получить из кэша если не устарело."""
    if key in _stats_cache:
        data, ts = _stats_cache[key]
        if (datetime.now().timestamp() - ts) < CACHE_TTL:
            return data
    return None


def _cache_set(key, data):
    """Сохранить в кэш."""
    _stats_cache[key] = (data, datetime.now().timestamp())


def get_team_stats(team_name, league_key="soccer_epl", season=None):
    """
    Получает статистику команды за сезон.
    Возвращает словарь с ключевыми показателями или None при ошибке.
    """
    if not API_FOOTBALL_KEY:
        return None

    if season is None:
        season = _get_current_season()

    league_id = LEAGUE_IDS.get(league_key, 39)
    team_id = TEAM_IDS.get(team_name)

    if not team_id:
        print(f"[API-Football] Команда не найдена в словаре: '{team_name}'")
        return None

    cache_key = f"stats_{team_id}_{league_id}_{season}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        r = requests.get(
            f"{BASE_URL}/teams/statistics",
            headers=HEADERS,
            params={"team": team_id, "league": league_id, "season": season},
            timeout=10
        )
        data = r.json()

        if not data.get("response"):
            print(f"[API-Football] Нет данных для {team_name}: {data.get('errors')}")
            return None

        s = data["response"]
        form_raw = s.get("form", "")
        # Берём последние 5 матчей из формы
        last5 = form_raw[-5:] if len(form_raw) >= 5 else form_raw

        result = {
            "team": s["team"]["name"],
            "form_full": form_raw,
            "form_last5": last5,
            "wins_home": s["fixtures"]["wins"]["home"],
            "wins_away": s["fixtures"]["wins"]["away"],
            "draws_home": s["fixtures"]["draws"]["home"],
            "draws_away": s["fixtures"]["draws"]["away"],
            "losses_home": s["fixtures"]["loses"]["home"],
            "losses_away": s["fixtures"]["loses"]["away"],
            "goals_for_home_avg": s["goals"]["for"]["average"]["home"],
            "goals_for_away_avg": s["goals"]["for"]["average"]["away"],
            "goals_against_home_avg": s["goals"]["against"]["average"]["home"],
            "goals_against_away_avg": s["goals"]["against"]["average"]["away"],
            "goals_for_total": s["goals"]["for"]["total"]["total"],
            "goals_against_total": s["goals"]["against"]["total"]["total"],
            "clean_sheets_home": s.get("clean_sheet", {}).get("home", 0),
            "clean_sheets_away": s.get("clean_sheet", {}).get("away", 0),
            "failed_to_score_home": s.get("failed_to_score", {}).get("home", 0),
            "failed_to_score_away": s.get("failed_to_score", {}).get("away", 0),
        }

        _cache_set(cache_key, result)
        print(f"[API-Football] Статистика {team_name}: форма={last5}, голов дома={result['goals_for_home_avg']}")
        return result

    except Exception as e:
        print(f"[API-Football] Ошибка при запросе статистики {team_name}: {e}")
        return None


def get_match_stats(home_team, away_team, league_key="soccer_epl"):
    """
    Получает статистику обеих команд для анализа матча.
    Возвращает форматированную строку для вставки в промпт ИИ.
    """
    home_stats = get_team_stats(home_team, league_key)
    away_stats = get_team_stats(away_team, league_key)

    if not home_stats and not away_stats:
        return None

    lines = ["📊 СТАТИСТИКА СЕЗОНА (API-Football):"]

    if home_stats:
        lines.append(
            f"\n🏠 {home_team} (хозяева):\n"
            f"  • Форма (посл. 5): {home_stats['form_last5']} (W=победа, D=ничья, L=поражение)\n"
            f"  • Дома: {home_stats['wins_home']}П / {home_stats['draws_home']}Н / {home_stats['losses_home']}П\n"
            f"  • Голов дома: {home_stats['goals_for_home_avg']} забито / {home_stats['goals_against_home_avg']} пропущено (в среднем)\n"
            f"  • Сухих матчей дома: {home_stats['clean_sheets_home']}"
        )
    else:
        lines.append(f"\n🏠 {home_team}: статистика недоступна")

    if away_stats:
        lines.append(
            f"\n✈️ {away_team} (гости):\n"
            f"  • Форма (посл. 5): {away_stats['form_last5']}\n"
            f"  • В гостях: {away_stats['wins_away']}П / {away_stats['draws_away']}Н / {away_stats['losses_away']}П\n"
            f"  • Голов в гостях: {away_stats['goals_for_away_avg']} забито / {away_stats['goals_against_away_avg']} пропущено (в среднем)\n"
            f"  • Сухих матчей в гостях: {away_stats['clean_sheets_away']}"
        )
    else:
        lines.append(f"\n✈️ {away_team}: статистика недоступна")

    return "\n".join(lines)
