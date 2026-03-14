#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_groq_llama.py — Тестирование Groq API и Llama 3.3 70B
Проверяет, работает ли ключ и модель доступны.
"""

import os
import json
import sys

# Загружаем ключ из .env
try:
    from config import GROQ_API_KEY
except ImportError:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

print(f"[Test] Groq API ключ: {GROQ_API_KEY[:20]}...{GROQ_API_KEY[-10:]}")

if not GROQ_API_KEY:
    print("[❌ ОШИБКА] GROQ_API_KEY не найден!")
    sys.exit(1)

# Пытаемся инициализировать Groq клиент
try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)
    print("[✅] Groq клиент инициализирован успешно")
except Exception as e:
    print(f"[❌ ОШИБКА] Не удалось инициализировать Groq клиент: {e}")
    sys.exit(1)

# Пытаемся отправить простой запрос к Llama
print("\n[Test] Отправляю тестовый запрос к Llama 3.3 70B...")

test_prompt = """Ты — футбольный аналитик. Дай краткий прогноз на матч Everton vs Chelsea.
Ответь только JSON:
{
  "prediction": "П1" или "Х" или "П2",
  "confidence": 0-100,
  "reason": "Почему такой прогноз"
}"""

try:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Ты — эксперт по ставкам на футбол. Отвечай только JSON."},
            {"role": "user", "content": test_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        timeout=30
    )
    
    result = json.loads(response.choices[0].message.content)
    print("[✅] Llama ответила успешно!")
    print(f"[Response] {json.dumps(result, ensure_ascii=False, indent=2)}")
    print("\n[✅ SUCCESS] Groq API и Llama 3.3 70B работают корректно!")
    
except Exception as e:
    error_type = type(e).__name__
    error_msg = str(e)
    
    print(f"\n[❌ ОШИБКА] {error_type}: {error_msg}")
    
    # Специальная диагностика для разных типов ошибок
    if "403" in error_msg or "Forbidden" in error_msg or "Access Denied" in error_msg:
        print("\n[🔍 Диагностика 403 Forbidden]")
        print("Возможные причины:")
        print("  1. API ключ неправильный или заблокирован")
        print("  2. Региональные ограничения (Groq может блокировать некоторые регионы)")
        print("  3. Лимит запросов исчерпан (бесплатный план имеет ограничения)")
        print("  4. Аккаунт Groq не активирован")
        print("\nРешения:")
        print("  • Проверьте ключ на https://console.groq.com/keys")
        print("  • Попробуйте использовать VPN")
        print("  • Используйте альтернативный провайдер (OpenRouter, Together.ai)")
        
    elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
        print("\n[🔍 Диагностика Timeout]")
        print("Возможные причины:")
        print("  1. Медленное интернет-соединение")
        print("  2. Сервер Groq перегружен")
        print("  3. Сетевые проблемы")
        
    elif "model" in error_msg.lower() or "not found" in error_msg.lower():
        print("\n[🔍 Диагностика Model Not Found]")
        print("Возможные причины:")
        print("  1. Модель 'llama-3.3-70b-versatile' недоступна в вашем плане")
        print("  2. Название модели неправильное")
        print("\nДоступные модели Groq:")
        print("  • llama-3.3-70b-versatile")
        print("  • llama-3.1-70b-versatile")
        print("  • mixtral-8x7b-32768")
        print("  • gemma-7b-it")
    
    sys.exit(1)
