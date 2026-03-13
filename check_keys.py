import os
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

def check_odds_api():
    key = os.getenv("THE_ODDS_API_KEY")
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
    try:
        r = requests.get(url)
        if r.status_code == 200:
            print("✅ The Odds API: OK")
        else:
            print(f"❌ The Odds API: Error {r.status_code} - {r.text}")
    except Exception as e:
        print(f"❌ The Odds API: Exception {e}")

def check_openai():
    key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=key)
    try:
        # Простой запрос списка моделей
        client.models.list()
        print("✅ OpenAI API: OK")
    except Exception as e:
        print(f"❌ OpenAI API: Exception {e}")

def check_groq():
    key = os.getenv("GROQ_API_KEY")
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            print("✅ Groq API: OK")
        else:
            print(f"❌ Groq API: Error {r.status_code}")
    except Exception as e:
        print(f"❌ Groq API: Exception {e}")

if __name__ == "__main__":
    print("--- Проверка API ключей ---")
    check_odds_api()
    check_openai()
    check_groq()
