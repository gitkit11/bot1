# -*- coding: utf-8 -*-
import requests
import datetime
from config import THE_ODDS_API_KEY

def get_real_cs2_matches():
    """
    Получает реальные матчи и коэффициенты CS2 через The Odds API.
    Лига: esports_csgo
    """
    if not THE_ODDS_API_KEY:
        print("[CS2 Parser] Ошибка: THE_ODDS_API_KEY не найден в .env")
        return []

    # The Odds API использует 'esports_csgo' для CS2, но иногда он может быть недоступен в Free Plan
    # Пробуем получить матчи, если не найдено - возвращаем пустой список
    url = f"https://api.the-odds-api.com/v4/sports/esports_csgo/odds/"
    params = {
        "apiKey": THE_ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            matches = []
            for item in data:
                # Фильтруем матчи на сегодня/завтра
                commence_time = datetime.datetime.fromisoformat(item['commence_time'].replace('Z', '+00:00'))
                now = datetime.datetime.now(datetime.timezone.utc)
                
                # Берем матчи в пределах 48 часов
                if now <= commence_time <= now + datetime.timedelta(hours=48):
                    home_team = item['home_team']
                    away_team = item['away_team']
                    
                    # Ищем коэффициенты (берем первый доступный букмекер)
                    odds = {"home_win": 0, "away_win": 0}
                    if item.get('bookmakers'):
                        for bm in item['bookmakers']:
                            for mkt in bm.get('markets', []):
                                if mkt['key'] == 'h2h':
                                    for outcome in mkt['outcomes']:
                                        if outcome['name'] == home_team:
                                            odds['home_win'] = outcome['price']
                                        elif outcome['name'] == away_team:
                                            odds['away_win'] = outcome['price']
                                    break
                            if odds['home_win'] > 0: break
                    
                    matches.append({
                        "id": item['id'],
                        "home": home_team,
                        "away": away_team,
                        "time": commence_time.strftime("%H:%M"),
                        "odds": odds
                    })
            return matches
        else:
            print(f"[CS2 Parser] Ошибка API: {response.status_code}")
            return []
    except Exception as e:
        print(f"[CS2 Parser] Исключение при парсинге: {e}")
        return []
