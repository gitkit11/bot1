# -*- coding: utf-8 -*-
import os
import requests
import datetime
import time
from dotenv import load_dotenv

load_dotenv()

PANDASCORE_BASE = "https://api.pandascore.co/csgo"

# Предзаполненный кэш ID топ-команд CS2 (PandaScore IDs)
# Ключи — все варианты написания имени команды
_team_cache = {
    # Team Vitality
    "Team Vitality": 3455, "Vitality": 3455,
    # FaZe Clan
    "FaZe Clan": 3212, "FaZe": 3212,
    # G2 Esports
    "G2 Esports": 3210, "G2": 3210,
    # Natus Vincere
    "Natus Vincere": 3216, "NaVi": 3216, "Na'Vi": 3216,
    # Team Spirit
    "Team Spirit": 124523, "Spirit": 124523,
    # MOUZ
    "MOUZ": 3240,
    # Heroic
    "Heroic": 3246,
    # Astralis
    "Astralis": 3209,
    # ENCE
    "ENCE": 3251,
    # Cloud9
    "Cloud9": 3223,
    # Team Liquid
    "Team Liquid": 3213, "Liquid": 3213,
    # FURIA
    "FURIA": 124530,
    # BIG
    "BIG": 3248,
}

def _get_headers():
    key = os.getenv("PANDASCORE_API_KEY")
    if not key:
        raise ValueError("PANDASCORE_API_KEY не найден в .env")
    return {"Authorization": f"Bearer {key}"}

def _request_with_retry(url, params=None, retries=3, delay=1.5):
    """Делает GET запрос с retry при SSL/сетевых ошибках."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_get_headers(), params=params, timeout=15)
            return r
        except Exception as e:
            if attempt < retries - 1:
                print(f"[PandaScore] Попытка {attempt+1}/{retries} не удалась: {type(e).__name__}. Повтор через {delay}с...")
                time.sleep(delay)
            else:
                print(f"[PandaScore] Все попытки исчерпаны: {e}")
    return None

def get_team_id(team_name):
    """Ищет ID команды по имени. Кэширует результат."""
    if team_name in _team_cache:
        return _team_cache[team_name]
    r = _request_with_retry(f"{PANDASCORE_BASE}/teams",
                             params={"search[name]": team_name, "per_page": 5})
    if r and r.ok:
        teams = r.json()
        if teams:
            # Ищем точное или близкое совпадение
            for t in teams:
                if team_name.lower() in t["name"].lower() or t["name"].lower() in team_name.lower():
                    _team_cache[team_name] = t["id"]
                    return t["id"]
            # Берём первый результат если нет точного совпадения
            _team_cache[team_name] = teams[0]["id"]
            return teams[0]["id"]
    return None

def get_team_stats(team_name, last_n=20):
    """
    Получает реальную статистику команды из истории матчей.
    Возвращает: winrate, wins, losses, last_5_form
    Бесплатный тариф: только победы/поражения в матчах (без статистики карт).
    """
    team_id = get_team_id(team_name)
    if not team_id:
        return {"winrate": 0.5, "wins": 0, "losses": 0, "form": "?????", "matches": 0}

    r = _request_with_retry(f"{PANDASCORE_BASE}/matches/past",
                             params={"filter[opponent_id]": team_id,
                                     "per_page": last_n,
                                     "sort": "-end_at"})
    if not r or not r.ok:
        return {"winrate": 0.5, "wins": 0, "losses": 0, "form": "?????", "matches": 0}

    matches = r.json()
    wins = 0
    losses = 0
    form_chars = []

    for m in matches:
        if m.get("status") != "finished":
            continue
        winner_id = m.get("winner_id")
        if winner_id == team_id:
            wins += 1
            form_chars.append("W")
        elif winner_id is not None:
            losses += 1
            form_chars.append("L")

    total = wins + losses
    winrate = wins / total if total > 0 else 0.5
    form = "".join(form_chars[-5:]) if form_chars else "?????"

    return {
        "winrate": round(winrate, 3),
        "wins": wins,
        "losses": losses,
        "form": form,
        "matches": total
    }

def get_head_to_head(team1_name, team2_name, last_n=10):
    """
    Получает статистику личных встреч двух команд.
    Возвращает: team1_wins, team2_wins, total
    """
    team1_id = get_team_id(team1_name)
    team2_id = get_team_id(team2_name)
    if not team1_id or not team2_id:
        return {"team1_wins": 0, "team2_wins": 0, "total": 0}

    r = _request_with_retry(f"{PANDASCORE_BASE}/matches/past",
                             params={"filter[opponent_id]": team1_id,
                                     "per_page": last_n * 3,
                                     "sort": "-end_at"})
    if not r or not r.ok:
        return {"team1_wins": 0, "team2_wins": 0, "total": 0}

    t1_wins = 0
    t2_wins = 0
    matches = r.json()
    for m in matches:
        if m.get("status") != "finished":
            continue
        # Проверяем что оба соперника в матче
        opponent_ids = [o["opponent"]["id"] for o in m.get("opponents", [])]
        if team1_id not in opponent_ids or team2_id not in opponent_ids:
            continue
        winner_id = m.get("winner_id")
        if winner_id == team1_id:
            t1_wins += 1
        elif winner_id == team2_id:
            t2_wins += 1

    return {"team1_wins": t1_wins, "team2_wins": t2_wins, "total": t1_wins + t2_wins}

def get_cs2_matches_pandascore():
    """
    Получает матчи CS2 (включая Tier-2/3) через PandaScore API.
    Автономный модуль: не зависит от config.py.
    """
    key = os.getenv("PANDASCORE_API_KEY")
    if not key:
        print("[PandaScore] Ошибка: PANDASCORE_API_KEY не найден в .env")
        return []

    params = {"per_page": 50}
    matches = []

    r_upcoming = _request_with_retry(f"{PANDASCORE_BASE}/matches/upcoming", params=params)
    if r_upcoming and r_upcoming.status_code == 200:
        for item in r_upcoming.json():
            if item.get('opponents') and len(item['opponents']) >= 2:
                matches.append(parse_pandascore_item(item, status_label="UPCOMING"))

    r_running = _request_with_retry(f"{PANDASCORE_BASE}/matches/running", params=params)
    if r_running and r_running.status_code == 200:
        for item in r_running.json():
            if item.get('opponents') and len(item['opponents']) >= 2:
                matches.append(parse_pandascore_item(item, status_label="LIVE"))

    return matches

def parse_pandascore_item(item, status_label):
    """Парсит один матч из формата PandaScore."""
    opponents = item['opponents']
    home = opponents[0]['opponent']['name']
    away = opponents[1]['opponent']['name']
    home_id = opponents[0]['opponent']['id']
    away_id = opponents[1]['opponent']['id']

    # Кэшируем ID команд
    _team_cache[home] = home_id
    _team_cache[away] = away_id

    start_time = item.get('begin_at')
    time_str = "—"
    if start_time:
        try:
            dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            # Конвертируем в МСК (UTC+3)
            dt_msk = dt + datetime.timedelta(hours=3)
            time_str = dt_msk.strftime("%d.%m %H:%M")
        except:
            pass

    # Формируем статус: если LIVE, то зеленый кружок
    is_live = item.get("status") == "running"
    display_status = "🟢 LIVE" if is_live else time_str

    # Извлекаем коэффициенты (если есть в API)
    # PandaScore в бесплатном тарифе редко дает коэффициенты, 
    # но мы проверим поле market_odds или подобные если они появятся
    home_odds = 1.90
    away_odds = 1.90
    
    # Попытка найти реальные коэффициенты в объекте матча
    if item.get("market_odds"):
        for market in item["market_odds"]:
            if market.get("name") == "match-winner":
                for selection in market.get("selections", []):
                    if selection.get("name") == home:
                        home_odds = selection.get("odds", 1.90)
                    elif selection.get("name") == away:
                        away_odds = selection.get("odds", 1.90)

    return {
        "id": item['id'],
        "home": home,
        "away": away,
        "home_id": home_id,
        "away_id": away_id,
        "time": display_status,
        "odds": {"home_win": home_odds, "away_win": away_odds},
        "league": item.get('league', {}).get('name', 'Tier-2/3'),
        "match_type": item.get('match_type', 'best_of_3'),
        "tournament": item.get('tournament', {}).get('name', '')
    }

def get_combined_cs2_matches():
    """Интерфейс для main.py."""
    return get_cs2_matches_pandascore()
