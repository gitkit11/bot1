# -*- coding: utf-8 -*-
import os
from openai import OpenAI
import json

# --- 1. Настройка клиентов ---
try:
    from config import OPENAI_API_KEY, GROQ_API_KEY
except ImportError:
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    print(f"[Агенты] OpenAI клиент инициализирован. Ключ: {OPENAI_API_KEY[:20]}...")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось инициализировать OpenAI клиент: {e}")
    client = None

# Groq клиент для Llama 3.3 70B
try:
    if GROQ_API_KEY:
        groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        print(f"[Агенты] Groq клиент инициализирован.")
    else:
        groq_client = None
        print("[Агенты] Groq API ключ не найден, Llama агент отключён.")
except Exception as e:
    groq_client = None
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось инициализировать Groq клиент: {e}")

# --- 2. Функция-помощник для вызова ИИ ---
def call_ai(prompt, client_instance, model):
    """Отправляет промпт в указанную модель и возвращает ответ в формате JSON."""
    if not client_instance:
        print(f"[ОШИБКА] Клиент для модели {model} не инициализирован!")
        return {"error": f"Клиент для {model} не инициализирован."}
    try:
        print(f"[{model}] Отправляю запрос...")
        response = client_instance.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты — эксперт мирового класса по ставкам на футбол. Отвечай ТОЛЬКО валидным JSON объектом. Все текстовые поля пиши на русском языке. Будь конкретным и аналитичным."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        result = json.loads(response.choices[0].message.content)
        print(f"[{model}] Ответ получен: {str(result)[:100]}...")
        return result
    except Exception as e:
        print(f"[{model} ОШИБКА] {type(e).__name__}: {e}")
        return {"error": str(e)}

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
    return call_ai(prompt, client, "gpt-4o-mini")

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
    return call_ai(prompt, client, "gpt-4o-mini")

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
    return call_ai(prompt, client, "gpt-4o")

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
    {{"analysis_summary": "...", "recommended_outcome": "...", "home_win_prob": 0.0, "draw_prob": 0.0, "away_win_prob": 0.0,
      "final_confidence_percent": 50, "total_goals_prediction": "...", "total_goals_reasoning": "...",
      "both_teams_to_score_prediction": "...", "btts_reasoning": "..."}}
    """
    return call_ai(prompt, client, "gpt-4o-mini")

# --- 5. Агенты для конкретных рынков ---

def run_goals_market_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds, gpt_result, llama_result):
    """Глубокий анализ рынка голов: тотал, обе забьют, первый гол."""
    gpt_total = gpt_result.get("total_goals_prediction", "Нет данных") if gpt_result else "Нет данных"
    llama_total = llama_result.get("total_goals_prediction", "Нет данных") if llama_result else "Нет данных"
    llama_btts = llama_result.get("both_teams_to_score_prediction", "Нет данных") if llama_result else "Нет данных"

    prompt = f"""
    Ты — специалист по ставкам на голы в футболе. Проведи глубокий анализ голевых рынков.
    Матч: {home_team} (хозяева) vs {away_team} (гости)

    Данные:
    - Статистика нейросети: П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}
    - Новостной фон: {news_summary}
    - Коэффициенты П1/Х/П2: {bookmaker_odds.get('home_win',0)} / {bookmaker_odds.get('draw',0)} / {bookmaker_odds.get('away_win',0)}
    - Мнение GPT по тоталу: {gpt_total}
    - Мнение Llama по тоталу: {llama_total}
    - Мнение Llama "Обе забьют": {llama_btts}

    Проанализируй:
    1. Тотал голов: Больше 2.5 или Меньше 2.5? Уверенность?
    2. Тотал 1.5: Больше 1.5 или Меньше 1.5? (почти всегда больше, но укажи если матч может быть 0:0 или 1:0)
    3. Обе команды забьют: Да или Нет? Уверенность?
    4. Кто забьёт первым: хозяева или гости? (на основе атакующей силы)
    5. Итоговый рекомендуемый рынок голов с наибольшей ценностью

    Формат ответа (только JSON):
    {{
      "summary": "Общий вывод по голевым рынкам (2-3 предложения).",
      "total_over_2_5": "Больше 2.5" или "Меньше 2.5",
      "total_over_2_5_confidence": <число от 0 до 100>,
      "total_over_2_5_reason": "Обоснование (1 предложение)",
      "total_over_1_5": "Больше 1.5" или "Меньше 1.5",
      "total_over_1_5_confidence": <число от 0 до 100>,
      "btts": "Да" или "Нет",
      "btts_confidence": <число от 0 до 100>,
      "btts_reason": "Обоснование (1 предложение)",
      "first_goal": "Хозяева" или "Гости" или "Неопределённо",
      "best_goals_bet": "Лучшая ставка на голы с обоснованием (1 предложение)"
    }}
    """
    return call_ai(prompt, client, "gpt-4o")

def run_corners_market_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds):
    """Анализ рынка угловых ударов."""
    prompt = f"""
    Ты — специалист по ставкам на угловые удары в футболе.
    Матч: {home_team} (хозяева) vs {away_team} (гости)

    Данные:
    - Статистика нейросети: П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}
    - Новостной фон: {news_summary}
    - Коэффициенты П1/Х/П2: {bookmaker_odds.get('home_win',0)} / {bookmaker_odds.get('draw',0)} / {bookmaker_odds.get('away_win',0)}

    Проанализируй рынок угловых:
    1. Общий тотал угловых: Больше 9.5 или Меньше 9.5?
    2. Угловые хозяев: Больше 4.5 или Меньше 4.5?
    3. Угловые гостей: Больше 4.5 или Меньше 4.5?
    4. Кто выиграет по угловым?
    5. Учитывай: атакующие команды бьют больше угловых, команды под давлением получают больше угловых

    Формат ответа (только JSON):
    {{
      "summary": "Анализ угловых (2 предложения).",
      "total_corners_over_9_5": "Больше 9.5" или "Меньше 9.5",
      "total_corners_confidence": <число от 0 до 100>,
      "total_corners_reason": "Обоснование (1 предложение)",
      "home_corners_over_4_5": "Больше 4.5" или "Меньше 4.5",
      "away_corners_over_4_5": "Больше 4.5" или "Меньше 4.5",
      "corners_winner": "{home_team}" или "{away_team}" или "Равно",
      "best_corners_bet": "Лучшая ставка на угловые (1 предложение)"
    }}
    """
    return call_ai(prompt, groq_client if groq_client else client, "llama-3.3-70b-versatile" if groq_client else "gpt-4o-mini")

def run_cards_market_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds):
    """Анализ рынка карточек."""
    prompt = f"""
    Ты — специалист по ставкам на карточки в футболе.
    Матч: {home_team} (хозяева) vs {away_team} (гости)

    Данные:
    - Статистика нейросети: П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}
    - Новостной фон: {news_summary}
    - Коэффициенты П1/Х/П2: {bookmaker_odds.get('home_win',0)} / {bookmaker_odds.get('draw',0)} / {bookmaker_odds.get('away_win',0)}

    Проанализируй рынок карточек:
    1. Тотал карточек: Больше 3.5 или Меньше 3.5?
    2. Будет ли красная карточка: Да или Нет?
    3. Кто получит больше карточек?
    4. Учитывай: дерби и принципиальные матчи дают больше карточек, равные матчи тоже

    Формат ответа (только JSON):
    {{
      "summary": "Анализ карточек (2 предложения).",
      "total_cards_over_3_5": "Больше 3.5" или "Меньше 3.5",
      "total_cards_confidence": <число от 0 до 100>,
      "total_cards_reason": "Обоснование (1 предложение)",
      "red_card": "Да" или "Нет",
      "red_card_confidence": <число от 0 до 100>,
      "more_cards_team": "{home_team}" или "{away_team}" или "Равно",
      "best_cards_bet": "Лучшая ставка на карточки (1 предложение)"
    }}
    """
    return call_ai(prompt, groq_client if groq_client else client, "llama-3.3-70b-versatile" if groq_client else "gpt-4o-mini")

def run_handicap_market_agent(home_team, away_team, prophet_data, bookmaker_odds, gpt_result, llama_result):
    """Анализ рынка гандикапов."""
    gpt_outcome = gpt_result.get("recommended_outcome", "Нет данных") if gpt_result else "Нет данных"
    gpt_conf = gpt_result.get("final_confidence_percent", 0) if gpt_result else 0
    llama_outcome = llama_result.get("recommended_outcome", "Нет данных") if llama_result else "Нет данных"

    prompt = f"""
    Ты — специалист по ставкам на гандикапы в футболе.
    Матч: {home_team} (хозяева) vs {away_team} (гости)

    Данные:
    - Нейросеть: П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}
    - Коэффициенты: П1={bookmaker_odds.get('home_win',0)}, Х={bookmaker_odds.get('draw',0)}, П2={bookmaker_odds.get('away_win',0)}
    - GPT прогноз: {gpt_outcome} (уверенность {gpt_conf}%)
    - Llama прогноз: {llama_outcome}

    Проанализируй гандикапы:
    1. Азиатский гандикап -0.5 на хозяев (хозяева должны выиграть)
    2. Азиатский гандикап +0.5 на гостей (гости не должны проиграть)
    3. Европейский гандикап -1 на фаворита (если есть явный фаворит)
    4. Двойной шанс: 1X, X2, 12 — какой наиболее ценный?

    Формат ответа (только JSON):
    {{
      "summary": "Анализ гандикапов (2 предложения).",
      "asian_handicap_home": "Брать -0.5 на хозяев" или "Не брать",
      "asian_handicap_home_confidence": <число от 0 до 100>,
      "asian_handicap_away": "Брать +0.5 на гостей" или "Не брать",
      "asian_handicap_away_confidence": <число от 0 до 100>,
      "double_chance": "1X" или "X2" или "12" или "Нет ценности",
      "double_chance_reason": "Обоснование (1 предложение)",
      "best_handicap_bet": "Лучшая ставка на гандикап (1 предложение)"
    }}
    """
    return call_ai(prompt, client, "gpt-4o-mini")


# ─── MIXTRAL АГЕНТ (3-й независимый агент) ──────────────────────────────────

def run_mixtral_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds,
                      team_stats_text=None, poisson_data=None, elo_data=None):
    """
    Gemma2-9b-it через Groq — тактический анализ и паттерны.
    Третий независимый агент для более надёжного консенсуса.
    (mixtral-8x7b-32768 удалён из Groq, заменён на gemma2-9b-it)
    """
    if not groq_client:
        print("[Gemma2] Groq недоступен, пропускаю третий агент.")  
        return {"error": "Groq недоступен"}

    poisson_block = ""
    if poisson_data:
        poisson_block = f"""
4. Модель Пуассона (xG-based):
   П1={round(poisson_data.get('home_win', 0)*100)}%, Х={round(poisson_data.get('draw', 0)*100)}%, П2={round(poisson_data.get('away_win', 0)*100)}%
   Тотал >2.5: {round(poisson_data.get('over_25', 0)*100)}%, Обе забьют: {round(poisson_data.get('btts', 0)*100)}%
   Вероятный счёт: {poisson_data.get('most_likely_score', 'N/A')}
"""

    elo_block = ""
    if elo_data:
        elo_block = f"""
5. ELO рейтинги:
   {home_team}: {elo_data.get('home_elo', 1500)} | {away_team}: {elo_data.get('away_elo', 1500)}
   ELO П1={round(elo_data.get('home', 0)*100)}%, ELO П2={round(elo_data.get('away', 0)*100)}%
"""

    stats_block = f"\n3. Статистика сезона:\n{team_stats_text}" if team_stats_text else ""

    prompt = f"""
Ты — тактический аналитик ставок на футбол. Специализируешься на анализе тактических схем,
стиля игры, прессинга и паттернов результатов в схожих матчах.

Матч: {home_team} (хозяева) vs {away_team} (гости)

Данные:
1. Нейросеть (10 сезонов): П1={prophet_data[1]:.2%}, Х={prophet_data[0]:.2%}, П2={prophet_data[2]:.2%}
2. Новостной фон: {news_summary}
{stats_block}{poisson_block}{elo_block}
Коэффициенты: П1={bookmaker_odds.get('home_win', 0)}, Х={bookmaker_odds.get('draw', 0)}, П2={bookmaker_odds.get('away_win', 0)}

Твои задачи:
1. Дай ТАКТИЧЕСКИЙ прогноз на исход — с акцентом на стиль игры команд
2. Прогноз тотала голов: Больше 2.5 или Меньше 2.5 (с учётом xG если есть)
3. Прогноз "Обе забьют": Да или Нет
4. Оцени уверенность в прогнозе от 0 до 100%
5. Укажи 2-3 ключевых тактических фактора

Формат ответа (только JSON):
{{
  "analysis_summary": "Тактический анализ (2-3 предложения с конкретными цифрами).",
  "recommended_outcome": "Победа хозяев" или "Ничья" или "Победа гостей",
  "home_win_prob": <число от 0.0 до 1.0>,
  "draw_prob": <число от 0.0 до 1.0>,
  "away_win_prob": <число от 0.0 до 1.0>,
  "final_confidence_percent": <целое число от 0 до 100>,
  "total_goals_prediction": "Больше 2.5" или "Меньше 2.5",
  "total_goals_reasoning": "Тактическое обоснование (1 предложение)",
  "both_teams_to_score_prediction": "Да" или "Нет",
  "btts_reasoning": "Обоснование (1 предложение)",
  "key_tactical_factors": ["фактор 1", "фактор 2", "фактор 3"]
}}
"""
    result = call_ai(prompt, groq_client, "gemma2-9b-it")
    print(f"[Gemma2] Результат: {str(result)[:100]}...")
    return result


# ─── МАТЕМАТИЧЕСКИЙ АНСАМБЛЬ ─────────────────────────────────────────────────

def build_math_ensemble(prophet_data, poisson_probs, elo_probs,
                        gpt_result, llama_result, mixtral_result=None,
                        bookmaker_odds=None):
    """
    Взвешенный ансамбль всех моделей.

    Веса (v4.2):
    - Пуассон (xG): 40%  — самая точная модель для голов
    - ELO: 30%           — сила команд и форма
    - AI агенты: 15%   — контекстный анализ
    - Букмекеры: 10%    — умные деньги
    - Пророк (нейросеть): 5% — исторические паттерны

    Пророк снижен до 5% т.к. нейросеть обучена на старых данных АПЛ
    и не учитывает текущую форму команд.
    """
    # Пуассон
    p_home = poisson_probs.get('home_win', 0.33) if poisson_probs else 0.33
    p_draw = poisson_probs.get('draw', 0.28) if poisson_probs else 0.28
    p_away = poisson_probs.get('away_win', 0.33) if poisson_probs else 0.33

    # ELO
    e_home = elo_probs.get('home', 0.33) if elo_probs else 0.33
    e_draw = elo_probs.get('draw', 0.28) if elo_probs else 0.28
    e_away = elo_probs.get('away', 0.33) if elo_probs else 0.33

    # Пророк
    pr_home = float(prophet_data[1]) if prophet_data else 0.33
    pr_draw = float(prophet_data[0]) if prophet_data else 0.28
    pr_away = float(prophet_data[2]) if prophet_data else 0.33

    # AI агенты — усредняем
    ai_home, ai_draw, ai_away = 0.0, 0.0, 0.0
    ai_count = 0
    for agent_result in [gpt_result, llama_result, mixtral_result]:
        if agent_result and not agent_result.get('error'):
            ai_home += float(agent_result.get('home_win_prob', 0.33))
            ai_draw += float(agent_result.get('draw_prob', 0.28))
            ai_away += float(agent_result.get('away_win_prob', 0.33))
            ai_count += 1
    if ai_count > 0:
        ai_home /= ai_count
        ai_draw /= ai_count
        ai_away /= ai_count
    else:
        ai_home, ai_draw, ai_away = 0.33, 0.28, 0.33

    # Букмекерские вероятности
    bk_home, bk_draw, bk_away = 0.33, 0.28, 0.33
    if bookmaker_odds:
        raw_h = 1 / bookmaker_odds.get('home_win', 3.0) if bookmaker_odds.get('home_win', 0) > 0 else 0.33
        raw_d = 1 / bookmaker_odds.get('draw', 3.5) if bookmaker_odds.get('draw', 0) > 0 else 0.28
        raw_a = 1 / bookmaker_odds.get('away_win', 4.0) if bookmaker_odds.get('away_win', 0) > 0 else 0.33
        total_bk = raw_h + raw_d + raw_a
        if total_bk > 0:
            bk_home, bk_draw, bk_away = raw_h/total_bk, raw_d/total_bk, raw_a/total_bk

    # Взвешенный ансамбль (v4.2 — исправленные веса)
    w_poisson = 0.40   # Хорошо знает текущую форму через xG
    w_elo = 0.30       # Хорошо знает силу команд
    w_ai = 0.15        # Контекстный анализ (GPT+Llama+Mixtral)
    w_book = 0.10      # Умные деньги букмекеров
    w_prophet = 0.05   # Нейросеть на старых данных — минимальный вес

    # Если нет Пуассона (Understat недоступен) — перераспределяем
    if not poisson_probs:
        w_elo += 0.25
        w_ai += 0.10
        w_book += 0.05
        w_poisson = 0.0

    # Если нет ELO — перераспределяем
    if not elo_probs:
        w_poisson += 0.20
        w_ai += 0.10
        w_elo = 0.0

    final_home = (p_home*w_poisson + e_home*w_elo + pr_home*w_prophet +
                  ai_home*w_ai + bk_home*w_book)
    final_draw = (p_draw*w_poisson + e_draw*w_elo + pr_draw*w_prophet +
                  ai_draw*w_ai + bk_draw*w_book)
    final_away = (p_away*w_poisson + e_away*w_elo + pr_away*w_prophet +
                  ai_away*w_ai + bk_away*w_book)

    total = final_home + final_draw + final_away
    if total > 0:
        final_home /= total
        final_draw /= total
        final_away /= total

    return {
        'home': round(final_home, 4),
        'draw': round(final_draw, 4),
        'away': round(final_away, 4),
        'weights': {
            'poisson': w_poisson,
            'elo': w_elo,
            'prophet': w_prophet,
            'ai': w_ai,
            'bookmaker': w_book,
        }
    }


def calculate_value_bets(ensemble_probs, bookmaker_odds):
    """
    Находит ставки с положительным ожидаемым значением.
    Пороги (профессиональные):
    - EV > 10% (не 5% — слишком много ложных сигналов)
    - Коэффициент >= 1.55 (не брать очевидных фаворитов)
    - Наша уверенность >= 52%
    """
    MIN_EV = 0.10       # минимум 10% EV
    MIN_ODDS = 1.55     # не брать очевидных фаворитов
    MIN_PROB = 0.52     # наша уверенность минимум 52%

    recommendations = []

    outcome_map = {
        'home': ('П1', bookmaker_odds.get('home_win', 0)),
        'draw': ('Х', bookmaker_odds.get('draw', 0)),
        'away': ('П2', bookmaker_odds.get('away_win', 0)),
    }

    for key, (label, odds) in outcome_map.items():
        if odds <= 1.0:
            continue
        our_prob = ensemble_probs.get(key, 0)
        ev = our_prob * odds - 1
        if ev > MIN_EV and odds >= MIN_ODDS and our_prob >= MIN_PROB:
            b = odds - 1
            q = 1 - our_prob
            kelly = max(0, min((our_prob * b - q) / b, 0.20))  # Макс 20% банка
            recommendations.append({
                'outcome': label,
                'odds': odds,
                'our_prob': round(our_prob * 100, 1),
                'book_prob': round(100 / odds, 1),
                'ev': round(ev * 100, 1),
                'kelly': round(kelly * 100, 1),
            })

    # Сортируем по EV
    recommendations.sort(key=lambda x: x['ev'], reverse=True)
    return recommendations
