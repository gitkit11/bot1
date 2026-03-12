import json
import requests
from config import OPENAI_API_KEY, GROQ_API_KEY

def run_cs2_analyst_agent(home_team, away_team, map_stats, bookmaker_odds, agent_type="gpt-4o"):
    """
    Запускает AI-агента для анализа матча CS2.
    agent_type: 'gpt-4o' (Стратег) или 'llama-3.3' (Тактик)
    """
    
    prompt = f"""
    Ты — профессиональный аналитик CS2 с 10-летним опытом.
    Проанализируй матч: {home_team} vs {away_team}
    
    Данные по картам (Винрейты):
    {json.dumps(map_stats, indent=2)}
    
    Коэффициенты букмекеров:
    {json.dumps(bookmaker_odds, indent=2)}
    
    Твоя задача:
    1. Оцени мап-вето. Кто забанит лучшие карты соперника?
    2. Оцени текущую форму команд (LAN vs Online).
    3. Сделай прогноз на победителя и тотал карт (2.5).
    4. Найди Value Bet (если вероятность выше коэффициента).
    
    Формат ответа:
    🎯 Прогноз: [Победитель]
    📊 Уверенность: [X%]
    🗺 Ключевая карта: [Название]
    💡 Комментарий: [Краткий анализ тактики]
    """
    
    # Заглушка для реального вызова API (в будущем использовать OpenAI/Groq)
    if not OPENAI_API_KEY or "dummy" in OPENAI_API_KEY:
        return f"🤖 [CS2 AI {agent_type}] Анализ для {home_team} vs {away_team}: Ожидается победа {home_team} на основе сильного пула Ancient/Anubis. Вероятный счет 2:1."
    
    # В реальном коде здесь будет вызов API (аналогично agents.py)
    return f"🤖 [CS2 AI {agent_type}] Анализ в процессе (требуется рабочий API ключ)..."

def build_cs2_ensemble(math_prob, ai_probs, news_factor=1.0):
    """
    Собирает ансамбль из математики, AI и новостей.
    math_prob: (prob_home, prob_away)
    ai_probs: list of (prob_home, prob_away)
    """
    weights = {
        "math": 0.40,
        "ai": 0.50,
        "news": 0.10
    }
    
    final_home = math_prob[0] * weights["math"]
    avg_ai_home = sum([p[0] for p in ai_probs]) / len(ai_probs) if ai_probs else 0.5
    final_home += avg_ai_home * weights["ai"]
    
    # Учет новостного фактора (замены, болезни)
    final_home *= news_factor
    
    # Ограничение
    final_home = max(0.05, min(0.95, final_home))
    return round(final_home, 2), round(1 - final_home, 2)
