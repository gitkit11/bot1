import os
import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("THE_ODDS_API_KEY")

def find_cs2():
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
    r = requests.get(url)
    if r.status_code == 200:
        data = r.json()
        print("🔍 Поиск CS2 в списке доступных видов спорта...")
        found = False
        for sport in data:
            if "cs" in sport['key'].lower() or "counter" in sport['title'].lower():
                print(f"✅ Найдено: {sport['key']} ({sport['title']})")
                found = True
        if not found:
            print("❌ CS2 не найден в списке. Возможно, сейчас нет активных матчей в линии.")
    else:
        print(f"❌ Ошибка API: {r.status_code}")

if __name__ == "__main__":
    find_cs2()
