# -*- coding: utf-8 -*-
import os
from openai import OpenAI
import json

# --- 1. Настройка клиента OpenAI ---
try:
    from config import OPENAI_API_KEY
except ImportError:
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    print(f"[Агенты] OpenAI клиент инициализирован. Ключ: {OPENAI_API_KEY[:20]}...")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось инициализировать OpenAI клиент: {e}")
    client = None

# --- 2. Функция-помощник для вызова GPT ---
def call_gpt(prompt, model="gpt-4o-mini"):
    """Отправляет промпт в модель GPT и возвращает ответ в формате JSON."""
    if not client:
        print("[GPT] ОШИБКА: клиент не инициализирован!")
        return {"error": "OpenAI client не инициализирован."}
    try:
        print(f"[GPT] Отправляю запрос к модели {model}...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a world-class expert. Respond ONLY with a valid JSON object."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        result = json.loads(response.choices[0].message.content)
        print(f"[GPT] Ответ получен: {str(result)[:100]}...")
        return result
    except Exception as e:
        print(f"[GPT ОШИБКА] {type(e).__name__}: {e}")
        return {"error": str(e)}

# --- 3. Специализированные ИИ-агенты ---

def run_statistician_agent(prophet_data):
    """Агент-Статистик: анализирует только цифры."""
    prompt = f"""
    You are a world-class football statistician. Your sole focus is quantitative data.
    Analyze the provided statistical data for an upcoming match.

    **Input Data:**
    - Prophet AI (LSTM model) prediction based on 30 years of history:
      - Home Win Probability: {prophet_data[1]:.2%}
      - Draw Probability: {prophet_data[0]:.2%}
      - Away Win Probability: {prophet_data[2]:.2%}
    
    **Your Task:**
    Based *only* on this statistical input, provide your final probability assessment.
    Do not invent or assume any other information. Your output must be a pure reflection of the provided stats.

    **Output Format (JSON only):**
    {{
      "analysis_summary": "A brief summary of the statistical outlook.",
      "home_win_prob": <float between 0.0 and 1.0>,
      "draw_prob": <float between 0.0 and 1.0>,
      "away_win_prob": <float between 0.0 and 1.0>
    }}
    """
    return call_gpt(prompt)

def run_scout_agent(home_team, away_team, news_summary):
    """Агент-Разведчик: анализирует новости и настроения."""
    prompt = f"""
    You are an investigative sports journalist. You find the hidden narratives that stats don't show.
    Analyze the provided news summary for the match: **{home_team} vs {away_team}**.

    **Input Data (News Summary):**
    {news_summary}

    **Your Task:**
    1. Identify key qualitative factors: confirmed injuries, team morale, manager pressure, player conflicts, etc.
    2. Synthesize this into a brief, impactful summary highlighting the most critical points for each team.
    3. Provide a sentiment score from -1.0 (very negative) to +1.0 (very positive) for each team based on the news.

    **Output Format (JSON only):**
    {{
      "analysis_summary": "A summary of the key findings from the news.",
      "home_team_sentiment": <float between -1.0 and 1.0>,
      "away_team_sentiment": <float between -1.0 and 1.0>
    }}
    """
    return call_gpt(prompt)

def run_arbitrator_agent(stats_result, scout_result, bookmaker_odds):
    """Агент-Арбитр: объединяет все данные и выносит вердикт."""
    prompt = f"""
    You are the final Arbitrator, a master betting analyst. You synthesize reports from your two specialist agents to make the final, decisive call.

    **Agent 1: The Statistician's Report**
    - Summary: {stats_result.get('analysis_summary', 'N/A')}
    - Probabilities: Home Win: {stats_result.get('home_win_prob', 0.33):.2%}, Draw: {stats_result.get('draw_prob', 0.33):.2%}, Away Win: {stats_result.get('away_win_prob', 0.33):.2%}

    **Agent 2: The Scout's Report**
    - Summary: {scout_result.get('analysis_summary', 'N/A')}
    - Sentiments: Home Team: {scout_result.get('home_team_sentiment', 0.0)}, Away Team: {scout_result.get('away_team_sentiment', 0.0)}

    **Market Data: Bookmaker Odds**
    - Home Win: {bookmaker_odds.get('home_win', 0)}
    - Draw: {bookmaker_odds.get('draw', 0)}
    - Away Win: {bookmaker_odds.get('away_win', 0)}

    **Your Task:**
    1.  **Synthesize:** Weigh the statistical probabilities against the qualitative news factors. The statistician is more objective (weight ~60%), the scout provides crucial context (weight ~40%).
    2.  **Final Probabilities:** Produce your final, blended probabilities for the three outcomes.
    3.  **Find Value:** Compare your final probabilities to the bookmaker's implied probabilities (1 / odds). Identify any "Value Bet" where your assessed probability is significantly higher than the market's.
    4.  **Kelly Criterion:** Based on the best value bet, calculate the recommended stake as a percentage of the bankroll. Formula: Stake % = ((Probability * Odds) - 1) / (Odds - 1). If no value, stake is 0.
    5.  **Verdict:** State your final verdict clearly.

    **Output Format (JSON only):**
    {{
      "final_verdict_summary": "A 2-3 sentence summary explaining your final decision.",
      "recommended_outcome": "Home Win", "Draw", or "Away Win",
      "final_confidence_percent": <int between 0 and 100>,
      "bookmaker_odds": <float, odds for the recommended outcome>,
      "expected_value_percent": <float, the edge over the bookmaker>,
      "recommended_stake_percent": <float, kelly criterion result>
    }}
    """
    return call_gpt(prompt)
