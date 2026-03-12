# -*- coding: utf-8 -*-
import os
from openai import OpenAI
import json

# --- 1. Настройка клиентов ---
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

# Gemini клиент через Google OpenAI-совместимый API
try:
    import google.generativeai as genai
    try:
        from config import GEMINI_API_KEY
    except ImportError:
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-2.0-flash')
        print(f"[Агенты] Gemini клиент инициализирован.")
    else:
        gemini_model = None
        print("[Агенты] Gemini API ключ не найден, агент Gemini отключён.")
except ImportError:
    gemini_model = None
    print("[Агенты] Библиотека google-generativeai не установлена, агент Gemini отключён.")

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
                {"role": "system", "content": "Ты — эксперт мирового класса. Отвечай ТОЛЬКО валидным JSON объектом. Все текстовые поля пиши на русском языке."},
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
    Ты — лучший в мире футбольный статистик. Твоя задача — анализировать только числовые данные.
    Проанализируй предоставленные статистические данные для предстоящего матча.

    Входные данные (нейросеть Пророк, обученная на 30 годах истории):
    - Вероятность победы хозяев: {prophet_data[1]:.2%}
    - Вероятность ничьей: {prophet_data[0]:.2%}
    - Вероятность победы гостей: {prophet_data[2]:.2%}

    Твоя задача: на основе ТОЛЬКО этих данных дай итоговую оценку вероятностей.
    Не придумывай и не предполагай ничего лишнего. Твой вывод должен отражать предоставленную статистику.

    Формат ответа (только JSON):
    {{
      "analysis_summary": "Краткое резюме статистической картины на русском языке (2-3 предложения).",
      "home_win_prob": <число от 0.0 до 1.0>,
      "draw_prob": <число от 0.0 до 1.0>,
      "away_win_prob": <число от 0.0 до 1.0>
    }}
    """
    return call_gpt(prompt)

def run_scout_agent(home_team, away_team, news_summary):
    """Агент-Разведчик: анализирует новости и настроения."""
    prompt = f"""
    Ты — лучший спортивный журналист-аналитик. Ты находишь скрытые факторы, которые не видны в статистике.
    Проанализируй новостной фон для матча: {home_team} vs {away_team}.

    Входные данные (новостной фон):
    {news_summary}

    Твоя задача:
    1. Определи ключевые качественные факторы: травмы, моральный дух, давление на тренера, конфликты, мотивация и т.д.
    2. Составь краткое, но ёмкое резюме, выделяя самые важные моменты для каждой команды.
    3. Дай оценку настроения от -1.0 (очень негативное) до +1.0 (очень позитивное) для каждой команды.

    Формат ответа (только JSON):
    {{
      "analysis_summary": "Резюме ключевых выводов из новостей на русском языке (2-3 предложения).",
      "home_team_sentiment": <число от -1.0 до 1.0>,
      "away_team_sentiment": <число от -1.0 до 1.0>
    }}
    """
    return call_gpt(prompt)

def run_arbitrator_agent(stats_result, scout_result, bookmaker_odds):
    """Агент-Арбитр: объединяет все данные и выносит вердикт."""
    prompt = f"""
    Ты — финальный Арбитр, мастер-аналитик ставок. Ты синтезируешь отчёты двух агентов и выносишь окончательное решение.

    Отчёт Агента 1 (Статистик):
    - Резюме: {stats_result.get('analysis_summary', 'Нет данных')}
    - Вероятности: Победа хозяев: {stats_result.get('home_win_prob', 0.33):.2%}, Ничья: {stats_result.get('draw_prob', 0.33):.2%}, Победа гостей: {stats_result.get('away_win_prob', 0.33):.2%}

    Отчёт Агента 2 (Разведчик):
    - Резюме: {scout_result.get('analysis_summary', 'Нет данных')}
    - Настроения: Хозяева: {scout_result.get('home_team_sentiment', 0.0)}, Гости: {scout_result.get('away_team_sentiment', 0.0)}

    Данные букмекеров:
    - Победа хозяев (П1): {bookmaker_odds.get('home_win', 0)}
    - Ничья (X): {bookmaker_odds.get('draw', 0)}
    - Победа гостей (П2): {bookmaker_odds.get('away_win', 0)}

    Твои задачи:
    1. Синтез: взвесь статистические вероятности и качественные факторы. Статистик весит ~60%, Разведчик ~40%.
    2. Итоговые вероятности: выдай финальные смешанные вероятности для трёх исходов.
    3. Поиск ценности: сравни свои вероятности с подразумеваемыми вероятностями букмекера (1 / коэффициент). Найди Value Bet там, где твоя вероятность значительно выше рыночной.
    4. Критерий Келли: рассчитай рекомендуемый размер ставки в % от банка. Формула: Ставка% = ((Вероятность * Коэффициент) - 1) / (Коэффициент - 1). Если нет ценности — ставка 0.
    5. Вердикт: чётко сформулируй финальное решение.

    Формат ответа (только JSON):
    {{
      "final_verdict_summary": "Резюме финального решения на русском языке (2-3 предложения).",
      "recommended_outcome": "Победа хозяев" или "Ничья" или "Победа гостей",
      "final_confidence_percent": <целое число от 0 до 100>,
      "bookmaker_odds": <число, коэффициент на рекомендуемый исход>,
      "expected_value_percent": <число, преимущество над букмекером в процентах>,
      "recommended_stake_percent": <число, результат критерия Келли>
    }}
    """
    return call_gpt(prompt)

# --- 4. Gemini Агент ---

def run_gemini_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds):
    """Агент на базе Gemini: даёт второе независимое мнение."""
    if not gemini_model:
        print("[Gemini] Агент Gemini недоступен, использую GPT как запасной вариант.")
        return run_gemini_via_gpt(home_team, away_team, prophet_data, news_summary, bookmaker_odds)

    prompt = f"""
Ты — лучший в мире футбольный аналитик Google Gemini. Дай независимый прогноз на матч.

Матч: {home_team} vs {away_team}

Входные данные:
1. Статистика (нейросеть Пророк):
   - Победа хозяев: {prophet_data[1]:.2%}
   - Ничья: {prophet_data[0]:.2%}
   - Победа гостей: {prophet_data[2]:.2%}
2. Новости:
   {news_summary}
3. Коэффициенты букмекеров:
   - П1: {bookmaker_odds.get('home_win', 0)}, X: {bookmaker_odds.get('draw', 0)}, П2: {bookmaker_odds.get('away_win', 0)}

Твои задачи:
1. Проанализируй все данные и дай свой прогноз на исход матча.
2. Оцени вероятность каждого из трёх исходов.
3. Предложи ставку на тотал голов (Больше 2.5 или Меньше 2.5) и на "Обе забьют" (Да/Нет).
4. Напиши краткое резюме (2-3 предложения) почему ты так считаешь.

Отвечай ТОЛЬКО валидным JSON без пояснений, все тексты на русском:
{{
  "analysis_summary": "Краткое резюме твоего анализа.",
  "recommended_outcome": "Победа хозяев" или "Ничья" или "Победа гостей",
  "home_win_prob": 0.0,
  "draw_prob": 0.0,
  "away_win_prob": 0.0,
  "total_goals_prediction": "Больше 2.5" или "Меньше 2.5",
  "both_teams_to_score_prediction": "Да" или "Нет"
}}
    """
    try:
        print("[Gemini] Отправляю запрос к Gemini...")
        response = gemini_model.generate_content(prompt)
        text = response.text.strip()
        # Извлекаем JSON из ответа
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        result = json.loads(text)
        print(f"[Gemini] Ответ получен: {str(result)[:100]}...")
        return result
    except Exception as e:
        print(f"[Gemini ОШИБКА] {type(e).__name__}: {e}")
        return run_gemini_via_gpt(home_team, away_team, prophet_data, news_summary, bookmaker_odds)


def run_gemini_via_gpt(home_team, away_team, prophet_data, news_summary, bookmaker_odds):
    """Запасной вариант: используем GPT вместо Gemini."""
    prompt = f"""
    Ты — футбольный аналитик. Дай независимый прогноз на матч {home_team} vs {away_team}.
    Статистика: П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}.
    Коэффициенты: П1={bookmaker_odds.get('home_win',0)}, X={bookmaker_odds.get('draw',0)}, П2={bookmaker_odds.get('away_win',0)}.
    Новости: {news_summary[:500]}
    Отвечай только JSON на русском:
    {{"analysis_summary": "...", "recommended_outcome": "...", "home_win_prob": 0.0, "draw_prob": 0.0, "away_win_prob": 0.0, "total_goals_prediction": "...", "both_teams_to_score_prediction": "..."}}
    """
    return call_gpt(prompt)
