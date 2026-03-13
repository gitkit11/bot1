import os
import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("THE_ODDS_API_KEY")

def list_sports():
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        print(f"--- Всего доступно видов спорта: {len(data)} ---")
        for sport in data:
            print(f"🏆 {sport['key']} | {sport['title']} | {sport['group']}")
    else:
        print(f"❌ Ошибка API: {r.status_code}")

if __name__ == "__main__":
    list_sports()
