import requests
from config import THE_ODDS_API_KEY

def check_cs2_availability():
    url = "https://api.the-odds-api.com/v4/sports/"
    params = {"apiKey": THE_ODDS_API_KEY}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        sports = response.json()
        cs2_sports = [s for s in sports if 'csgo' in s['key'] or 'cs2' in s['key']]
        print(f"Доступные рынки CS2: {cs2_sports}")
        
        if cs2_sports:
            key = cs2_sports[0]['key']
            odds_url = f"https://api.the-odds-api.com/v4/sports/{key}/odds/"
            odds_params = {
                "apiKey": THE_ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal"
            }
            odds_resp = requests.get(odds_url, params=odds_params)
            odds_resp.raise_for_status()
            matches = odds_resp.json()
            print(f"Найдено {len(matches)} матчей для {key}")
            if matches:
                print(f"Пример матча: {matches[0]['home_team']} vs {matches[0]['away_team']}")
    except Exception as e:
        print(f"Ошибка при проверке API: {e}")

if __name__ == "__main__":
    check_cs2_availability()
