# -*- coding: utf-8 -*-
import os
from openai import OpenAI, APIStatusError
from groq import Groq
import json

# --- 1. Настройка клиентов ---
try:
    from config import OPENAI_API_KEY, GROQ_API_KEY
except ImportError:
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# OpenAI клиент для GPT-4o
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    print(f"[Агенты] OpenAI клиент инициализирован. Ключ: {OPENAI_API_KEY[:20]}...")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось инициализировать OpenAI клиент: {e}")
    client = None

# Groq клиент для Llama и Gemma (через официальную библиотеку)
try:
    if GROQ_API_KEY:
        groq_client = Groq(api_key=GROQ_API_KEY)
        print(f"[Агенты] Groq клиент инициализирован.")
    else:
        groq_client = None
        print("[Агенты] Groq API ключ не найден, Llama/Gemma агенты отключены.")
except Exception as e:
    groq_client = None
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось инициализировать Groq клиент: {e}")

# --- 2. Функция-помощник для вызова ИИ ---
def call_ai(prompt, client_instance, model, retries=2):
    """Отправляет промпт в указанную модель и возвращает ответ в формате JSON."""
    if not client_instance:
        print(f"[ОШИБКА] Клиент для модели {model} не инициализирован!")
        return {"error": f"Клиент для {model} не инициализирован."}
    
    is_groq = isinstance(client_instance, Groq)
    
    for attempt in range(retries):
        try:
            print(f"[{model}] Отправляю запрос (попытка {attempt+1})...")
            
            # Для Groq и OpenAI вызовы немного отличаются в зависимости от библиотеки
            if is_groq:
                response = client_instance.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Ты — эксперт мирового класса по ставкам на футбол. Отвечай ТОЛЬКО валидным JSON объектом. Все текстовые поля пиши на русском языке. Будь конкретным и аналитичным."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                    timeout=30
                )
            else:
                response = client_instance.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Ты — эксперт мирового класса по ставкам на футбол. Отвечай ТОЛЬКО валидным JSON объектом. Все текстовые поля пиши на русском языке. Будь конкретным и аналитичным."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                    timeout=30
                )
            
            result = json.loads(response.choices[0].message.content)
            print(f"[{model}] Ответ получен: {str(result)[:100]}...")
            return result
            
        except Exception as e:
            print(f"[{model} ОШИБКА попытка {attempt+1}] {type(e).__name__}: {e}")
            if attempt < retries - 1:
                import time; time.sleep(2)
                
    # Если модель упала — возвращаем заглушку с пометкой
    print(f"[{model}] Все попытки исчерпаны, возвращаю заглушку")
    return {"error": f"{model} недоступен", "analysis_summary": f"⚠️ {model} временно недоступен",
            "recommended_outcome": "Нет данных", "final_confidence_percent": 0,
            "total_goals_prediction": "—", "both_teams_to_score_prediction": "—"}

# --- 3. Специализированные ИИ-агенты (основной анализ) ---

def run_statistician_agent(prophet_data, team_stats_text=None):
    """Агент-Статистик: анализирует только цифры."""
    stats_block = f"""
    Дополнительная статистика сезона:
    {team_stats_text}
    """ if team_stats_text else ""
    prompt = f"""
    Ты — лучший в мире футбольный статистик. Анализируй только числовые данные.

    Данные нейросети Пророк (обучена на 10 сезонах АПЛ):
    - Вероятность победы хозяев (П1): {prophet_data[1]:.2%}
    - Вероятность ничьей (Х): {prophet_data[0]:.2%}
    - Вероятность победы гостей (П2): {prophet_data[2]:.2%}
    {stats_block}
    Задача: дай статистическую оценку с учётом ВСЕХ данных. Какой исход наиболее вероятен? Насколько равный матч?
    Если есть данные по форме и голам — обязательно используй их в анализе.

    Формат ответа (только JSON):
    {{
      "analysis_summary": "Краткое резюме статистической картины (2-3 предложения).",
      "home_win_prob": <число от 0.0 до 1.0>,
      "draw_prob": <число от 0.0 до 1.0>,
      "away_win_prob": <число от 0.0 до 1.0>,
      "match_balance": "равный" или "лёгкое преимущество хозяев" или "явный фаворит хозяева" или "лёгкое преимущество гостей" или "явный фаворит гости"
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

def run_scout_agent(home_team, away_team, news_summary):
    """Агент-Разведчик: анализирует новости и настроения."""
    prompt = f"""
    Ты — лучший спортивный аналитик. Находишь скрытые факторы, невидимые в статистике.
    Матч: {home_team} vs {away_team}

    Новостной фон:
    {news_summary}

    Задача:
    1. Найди ключевые качественные факторы: травмы, моральный дух, мотивация, конфликты, усталость от плотного графика
    2. Оцени как новостной фон влияет на вероятность каждого исхода
    3. Дай оценку настроения каждой команды

    Формат ответа (только JSON):
    {{
      "analysis_summary": "Ключевые выводы из новостей (2-3 предложения).",
      "home_team_sentiment": <число от -1.0 до 1.0>,
      "away_team_sentiment": <число от -1.0 до 1.0>,
      "key_factor": "Самый важный фактор влияющий на матч (1 предложение)"
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

def run_arbitrator_agent(stats_result, scout_result, bookmaker_odds):
    """Агент-Арбитр: объединяет все данные и выносит вердикт."""
    prompt = f"""
    Ты — финальный Арбитр, мастер-аналитик ставок с 20-летним опытом. Синтезируй отчёты и вынеси окончательное решение.

    ОТЧЁТ СТАТИСТИКА:
    - Резюме: {stats_result.get('analysis_summary', 'Нет данных')}
    - П1: {stats_result.get('home_win_prob', 0.33):.2%} | Х: {stats_result.get('draw_prob', 0.33):.2%} | П2: {stats_result.get('away_win_prob', 0.33):.2%}
    - Баланс матча: {stats_result.get('match_balance', 'неизвестно')}

    ОТЧЁТ РАЗВЕДЧИК:
    - Резюме: {scout_result.get('analysis_summary', 'Нет данных')}
    - Ключевой фактор: {scout_result.get('key_factor', 'Нет данных')}
    - Настроение хозяев: {scout_result.get('home_team_sentiment', 0.0):.2f} | Гостей: {scout_result.get('away_team_sentiment', 0.0):.2f}

    КОЭФФИЦИЕНТЫ БУКМЕКЕРОВ:
    - П1: {bookmaker_odds.get('home_win', 0)} | Х: {bookmaker_odds.get('draw', 0)} | П2: {bookmaker_odds.get('away_win', 0)}

    ТВОИ ЗАДАЧИ:
    1. Взвесь данные: статистика 60%, новостной фон 40%
    2. Рассчитай итоговые вероятности для трёх исходов
    3. Найди Value Bet: сравни свою вероятность с подразумеваемой букмекером (1/коэф). Value есть если твоя вероятность > вероятности букмекера на 5%+
    4. Критерий Келли: Ставка% = ((Вероятность × Коэффициент) - 1) / (Коэффициент - 1). Если нет ценности — ставка 0.
    5. ВАЖНО: Рекомендуй ставку ТОЛЬКО если уверенность >= 60% И есть реальная ценность. Иначе — "Пропустить матч"

    Формат ответа (только JSON):
    {{
      "final_verdict_summary": "Резюме финального решения (2-3 предложения).",
      "recommended_outcome": "Победа хозяев" или "Ничья" или "Победа гостей",
      "final_confidence_percent": <целое число от 0 до 100>,
      "bookmaker_odds": <коэффициент на рекомендуемый исход>,
      "expected_value_percent": <преимущество над букмекером в %>,
      "recommended_stake_percent": <результат критерия Келли, 0 если нет ценности>,
      "bet_signal": "СТАВИТЬ" или "ПРОПУСТИТЬ",
      "signal_reason": "Почему ставить или пропустить (1 предложение)"
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

# --- 4. Llama Агент (независимое мнение) ---

def run_llama_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds, team_stats_text=None):
    """Агент на базе Llama 3.3 70B через Groq: даёт второе независимое мнение."""
    if not groq_client:
        print("[Llama] Агент Llama недоступен, использую GPT как запасной вариант.")
        return run_llama_via_gpt(home_team, away_team, prophet_data, news_summary, bookmaker_odds)

    stats_block = f"""
    4. Статистика сезона (API-Football):
    {team_stats_text}
    """ if team_stats_text else ""

    prompt = f"""
    Ты — независимый футбольный аналитик. Дай СВОЙ прогноз, не копируй чужие выводы.
    Матч: {home_team} (хозяева) vs {away_team} (гости)

    Данные:
    1. Нейросеть (10 сезонов АПЛ): П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}
    2. Новостной фон: {news_summary}
    3. Коэффициенты: П1={bookmaker_odds.get('home_win', 0)}, X={bookmaker_odds.get('draw', 0)}, П2={bookmaker_odds.get('away_win', 0)}
    {stats_block}
    Твои задачи:
    1. Дай НЕЗАВИСИМЫЙ прогноз на исход (П1/Х/П2) со своими вероятностями
    2. Прогноз тотала голов: Больше 2.5 или Меньше 2.5 — с обоснованием (используй среднее голов из статистики если есть)
    3. Прогноз "Обе забьют": Да или Нет — с обоснованием (учитывай сухие матчи из статистики если есть)
    4. Оцени уверенность в своём прогнозе от 0 до 100%
    5. Напиши краткое резюме своего анализа

    Формат ответа (только JSON):
    {{
      "analysis_summary": "Твой независимый анализ (2-3 предложения).",
      "recommended_outcome": "Победа хозяев" или "Ничья" или "Победа гостей",
      "home_win_prob": <число от 0.0 до 1.0>,
      "draw_prob": <число от 0.0 до 1.0>,
      "away_win_prob": <число от 0.0 до 1.0>,
      "final_confidence_percent": <целое число от 0 до 100>,
      "total_goals_prediction": "Больше 2.5" или "Меньше 2.5",
      "total_goals_reasoning": "Почему такой прогноз по голам (1 предложение)",
      "both_teams_to_score_prediction": "Да" или "Нет",
      "btts_reasoning": "Почему обе забьют или нет (1 предложение)"
    }}
    """
    return call_ai(prompt, groq_client, "llama-3.3-70b-versatile")

def run_llama_via_gpt(home_team, away_team, prophet_data, news_summary, bookmaker_odds):
    """Запасной вариант: используем GPT вместо Llama."""
    prompt = f"""
    Ты — независимый футбольный аналитик. Дай прогноз на матч {home_team} vs {away_team}.
    Статистика: П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}.
    Коэффициенты: П1={bookmaker_odds.get('home_win',0)}, X={bookmaker_odds.get('draw',0)}, П2={bookmaker_odds.get('away_win',0)}.
    Новости: {news_summary[:500]}
    Отвечай только JSON:
    {{
      "analysis_summary": "...", 
      "recommended_outcome": "...", 
      "home_win_prob": 0.0, 
      "draw_prob": 0.0, 
      "away_win_prob": 0.0,
      "final_confidence_percent": 0,
      "total_goals_prediction": "Больше 2.5",
      "both_teams_to_score_prediction": "Да"
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

# --- 5. Дополнительные рыночные агенты (Маркет-мейкеры) ---

def run_goals_market_agent(home_team, away_team, stats_text, bookmaker_odds):
    """Агент по рынку голов: анализирует ТБ/ТМ."""
    prompt = f"""
    Ты — эксперт по ставкам на тоталы голов. Матч: {home_team} vs {away_team}.
    Статистика голов и xG: {stats_text}
    Коэффициенты на ТБ 2.5: {bookmaker_odds.get('over_2_5', 'Нет данных')}, ТМ 2.5: {bookmaker_odds.get('under_2_5', 'Нет данных')}.
    Задача: Дай прогноз на ТБ 2.5 или ТМ 2.5. Оцени вероятность и ценность.
    Формат ответа (JSON):
    {{
      "analysis_summary": "...",
      "recommended_outcome": "Больше 2.5" или "Меньше 2.5",
      "confidence_percent": 0,
      "expected_value_percent": 0
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

def run_corners_market_agent(home_team, away_team, stats_text, bookmaker_odds):
    """Агент по угловым."""
    prompt = f"""
    Ты — эксперт по ставкам на угловые. Матч: {home_team} vs {away_team}.
    Статистика угловых: {stats_text}
    Задача: Прогнозируй количество угловых (Победа по угловым или Тотал).
    Формат ответа (JSON):
    {{
      "analysis_summary": "...",
      "recommended_outcome": "...",
      "confidence_percent": 0
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

def run_cards_market_agent(home_team, away_team, stats_text, bookmaker_odds):
    """Агент по желтым карточкам."""
    prompt = f"""
    Ты — эксперт по ставкам на карточки. Матч: {home_team} vs {away_team}.
    Статистика ЖК: {stats_text}
    Задача: Прогнозируй количество ЖК (Победа по ЖК или Тотал).
    Формат ответа (JSON):
    {{
      "analysis_summary": "...",
      "recommended_outcome": "...",
      "confidence_percent": 0
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

def run_handicap_market_agent(home_team, away_team, stats_text, bookmaker_odds):
    """Агент по форам."""
    prompt = f"""
    Ты — эксперт по ставкам на форы (гандикапы). Матч: {home_team} vs {away_team}.
    Статистика: {stats_text}
    Задача: Прогнозируй оптимальную фору (например, -1 или +1.5).
    Формат ответа (JSON):
    {{
      "analysis_summary": "...",
      "recommended_outcome": "...",
      "confidence_percent": 0
    }}
    """
    return call_ai(prompt, client, "gpt-4.1-mini")

def run_mixtral_agent(home_team, away_team, stats_text):
    """Агент на базе Mixtral (через Groq) для альтернативного взгляда."""
    if not groq_client:
        return {"error": "Groq недоступен"}
    prompt = f"Проанализируй матч {home_team} vs {away_team}. Статистика: {stats_text}. Дай краткий прогноз."
    return call_ai(prompt, groq_client, "mixtral-8x7b-32768")

def build_math_ensemble(math_probs, ai_probs):
    """Объединяет математические вероятности и ИИ-прогнозы в ансамбль."""
    # Веса: Математика 40%, ИИ 60%
    ensemble = {}
    for key in ['home', 'draw', 'away']:
        ensemble[key] = (math_probs.get(key, 0.33) * 0.4) + (ai_probs.get(key, 0.33) * 0.6)
    return ensemble

def calculate_value_bets(ensemble_probs, bookmaker_odds):
    """Ищет выгодные ставки (Value Bets) на основе ансамбля."""
    value_bets = []
    for outcome, prob in ensemble_probs.items():
        odds = bookmaker_odds.get(outcome)
        if odds and odds > 1:
            implied_prob = 1 / odds
            if prob > implied_prob + 0.05: # Преимущество 5%+
                value_bets.append({
                    "outcome": outcome,
                    "prob": prob,
                    "odds": odds,
                    "ev": (prob * odds) - 1
                })
    return value_bets
