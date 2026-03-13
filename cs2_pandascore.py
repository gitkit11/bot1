# -*- coding: utf-8 -*-
import requests
import datetime
from config import PANDASCORE_API_KEY, THE_ODDS_API_KEY

def get_cs2_matches_pandascore():
    """
    Получает матчи CS2 (включая Tier-2/3) через PandaScore API.
    """
    if not PANDASCORE_API_KEY:
        print("[PandaScore] Ошибка: PANDASCORE_API_KEY не найден")
        return []

    url = "https://api.pandascore.co/csgo/matches/running"
    headers = {"Authorization": f"Bearer {PANDASCORE_API_KEY}"}
    params = {"per_page": 50}

    matches = []
    try:
        # Сначала берем текущие (running) матчи
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            for item in response.json():
                if item.get('opponents') and len(item['opponents']) >= 2:
                    matches.append(parse_pandascore_item(item, status="LIVE 🔴"))

        # Затем берем предстоящие (upcoming) матчи
        url_upcoming = "https://api.pandascore.co/csgo/matches/upcoming"
        response = requests.get(url_upcoming, headers=headers, params=params)
        if response.status_code == 200:
            for item in response.json():
                if item.get('opponents') and len(item['opponents']) >= 2:
                    matches.append(parse_pandascore_item(item, status="UPCOMING"))
        
        return matches
    except Exception as e:
        print(f"[PandaScore] Ошибка: {e}")
        return []

def parse_pandascore_item(item, status):
    """Парсит один матч из формата PandaScore."""
    opponents = item['opponents']
    home = opponents[0]['opponent']['name']
    away = opponents[1]['opponent']['name']
    
    # Время матча
    start_time = item.get('begin_at')
    time_str = "—"
    if start_time:
        dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        time_str = dt.strftime("%H:%M")

    # Пытаемся найти коэффициенты (PandaScore в Free Plan их не дает детально, 
    # поэтому мы будем позже подтягивать их из The Odds API или ставить 1.9/1.9)
    return {
        "id": item['id'],
        "home": home,
        "away": away,
        "time": f"{time_str} [{status}]",
        "odds": {"home_win": 1.90, "away_win": 1.90}, # Заглушка, если нет реальных кэфов
        "league": item.get('league', {}).get('name', 'Tier-2/3')
    }

def get_combined_cs2_matches():
    """
    Объединяет данные из The Odds API (кэфы) и PandaScore (список матчей).
    """
    # 1. Берем матчи из PandaScore (они видят Tier-2/3)
    ps_matches = get_cs2_matches_pandascore()
    
    # 2. Пытаемся найти кэфы в The Odds API (если есть ключ)
    # (В этой версии мы просто возвращаем PandaScore, так как это дает максимум матчей)
    return ps_matches
