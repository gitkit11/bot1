import os
import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("PANDASCORE_API_KEY")

def test_ps():
    url = "https://api.pandascore.co/csgo/matches/upcoming"
    headers = {"Authorization": f"Bearer {key}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        print(f"✅ PandaScore работает! Найдено предстоящих матчей: {len(data)}")
        for m in data[:5]:
            home = m['opponents'][0]['opponent']['name'] if len(m['opponents']) > 0 else "TBD"
            away = m['opponents'][1]['opponent']['name'] if len(m['opponents']) > 1 else "TBD"
            print(f"🎮 {home} vs {away} | Турнир: {m['league']['name']}")
    else:
        print(f"❌ Ошибка PandaScore: {r.status_code} - {r.text}")

if __name__ == "__main__":
    test_ps()
