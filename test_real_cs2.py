import os
import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("THE_ODDS_API_KEY")

def get_cs2_matches():
    url = f"https://api.the-odds-api.com/v4/sports/esports_csgo/odds/?apiKey={key}&regions=eu&markets=h2h&oddsFormat=decimal"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        print(f"✅ Найдено матчей CS2: {len(data)}")
        for match in data[:3]:
            print(f"🎮 {match['home_team']} vs {match['away_team']} | Время: {match['commence_time']}")
    else:
        print(f"❌ Ошибка API: {r.status_code} - {r.text}")

if __name__ == "__main__":
    get_cs2_matches()
