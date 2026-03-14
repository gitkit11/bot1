"""
sports/cs2/agents.py — AI агенты для анализа CS2 матчей
Использует GPT-4.1-mini и Llama 3.3 70B через те же клиенты что и футбол

Источники данных:
  - PandaScore (free): история матчей, WR, форма, H2H
  - HLTV stats (hltv_stats.py): winrate по картам, рейтинг игроков
"""
import json
import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from config import OPENAI_API_KEY, GROQ_API_KEY
except ImportError:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Инициализация клиентов
try:
    from openai import OpenAI
    from groq import Groq
    _gpt_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    _groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except Exception as e:
    print(f"[CS2-Agents] Ошибка инициализации клиентов: {e}")
    _gpt_client = None
    _groq_client = None

# Подключаем HLTV статистику (карты + игроки)
try:
    from .hltv_stats import (
        format_map_stats_for_ai,
        format_players_for_ai,
        get_team_map_stats as get_map_stats,
        get_player_stats,
    )
    _HLTV_AVAILABLE = True
except ImportError:
    _HLTV_AVAILABLE = False


def _call_ai(prompt, client, model, system_msg=None, retries=2):
    """Вызов AI модели с retry при пустом ответе."""
    if not client:
        return f"❌ Клиент {model} не инициализирован"
    if system_msg is None:
        system_msg = "Ты — профессиональный аналитик CS2 с 10-летним опытом. Отвечай на русском языке, кратко и по делу."
    
    # Проверка типа клиента для Groq
    from groq import Groq
    is_groq = isinstance(client, Groq)
    
    for attempt in range(retries):
        try:
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4,
                "max_tokens": 600
            }
            
            # Groq не поддерживает response_format в некоторых моделях или требует иного синтаксиса,
            # но здесь мы ожидаем текст, так что просто вызываем.
            response = client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content.strip()
            if text:
                try:
                    # Попытка распарсить JSON, если ожидается JSON
                    if 'json_object' in kwargs.get('response_format', {}).values():
                        return json.loads(text)
                    return text
                except json.JSONDecodeError:
                    print(f"[AI] Ошибка JSONDecodeError для модели {model}. Raw response: {text[:200]}...")
                    return f"❌ Ошибка парсинга JSON от {model}"
            if attempt < retries - 1:
                time.sleep(1)
            if attempt < retries - 1:
                time.sleep(1)
        except Exception as e:
            err = str(e)[:120]
            # Если ошибка 403 (Access Denied) или другие критические ошибки Groq
            if "403" in err or "access denied" in err.lower():
                print(f"[AI] Критическая ошибка {model}: {err}. Требуется fallback.")
                raise e # Пробрасываем выше для обработки в run_cs2_analyst_agent
            
            if attempt < retries - 1 and ("rate" in err.lower() or "timeout" in err.lower()):
                time.sleep(3)
            else:
                return f"❌ Ошибка {model}: {err}"
    return "❌ Агент не дал ответа"


def run_cs2_analyst_agent(home_team, away_team, map_stats, bookmaker_odds,
                           agent_type="gpt-4o", home_stats=None, away_stats=None, h2h=None):
    """
    Запускает AI-агента для анализа матча CS2.

    agent_type: 'gpt-4o' (Стратег) или 'llama-3.3' (Тактик)
    home_stats/away_stats: реальная статистика из PandaScore
    h2h: личные встречи
    """
    home_odds = bookmaker_odds.get("home_win", 1.90)
    away_odds = bookmaker_odds.get("away_win", 1.90)

    # ── Блок 1: Статистика матчей (PandaScore) ──────────────────────────────
    stats_block = ""
    if home_stats and home_stats.get("matches", 0) > 0:
        stats_block += f"\n📊 Статистика матчей (PandaScore, последние 20):"
        stats_block += f"\n  {home_team}: {home_stats['wins']}В/{home_stats['losses']}П, WR={int(home_stats['winrate']*100)}%, форма: {home_stats['form']}"
    if away_stats and away_stats.get("matches", 0) > 0:
        if not stats_block:
            stats_block += f"\n📊 Статистика матчей (PandaScore, последние 20):"
        stats_block += f"\n  {away_team}: {away_stats['wins']}В/{away_stats['losses']}П, WR={int(away_stats['winrate']*100)}%, форма: {away_stats['form']}"
    if h2h and h2h.get("total", 0) >= 2:
        stats_block += f"\n  Личные встречи: {home_team} {h2h['team1_wins']}:{h2h['team2_wins']} {away_team} (из {h2h['total']} матчей)"

    # ── Блок 2: Статистика карт и игроков (HLTV) ────────────────────────────
    hltv_block = ""
    if _HLTV_AVAILABLE:
        hltv_maps = format_map_stats_for_ai(home_team, away_team)
        hltv_players = format_players_for_ai(home_team, away_team)
        if "недоступна" not in hltv_maps:
            hltv_block = f"\n{hltv_maps}"
        if "недоступна" not in hltv_players:
            hltv_block += f"\n\n{hltv_players}"

    # Fallback: MIS карты если HLTV недоступен
    if not hltv_block and map_stats:
        hltv_block = f"\nСтатистика карт (MIS):\n{json.dumps(map_stats, indent=2, ensure_ascii=False)}"

    # ── Промпты для агентов ──────────────────────────────────────────────────
    if agent_type == "gpt-4o":
        prompt = f"""Матч CS2: {home_team} vs {away_team}
Коэффициенты: {home_team}={home_odds} | {away_team}={away_odds}
{stats_block}
{hltv_block}

Как стратег — оцени:
1. Кто фаворит и почему (форма, WR, сильные карты, ключевые игроки)
2. Прогноз счёта серии (2:0, 2:1)
3. Есть ли value bet? Если да — на что конкретно?
4. Уверенность в прогнозе (%)

Ответ краткий, 4-5 предложений."""
        client = _gpt_client
        model = "gpt-4.1-mini"

    else:
        # llama-3.3 — тактический анализ
        prompt = f"""Матч CS2: {home_team} vs {away_team}
Коэффициенты: {home_team}={home_odds} | {away_team}={away_odds}
{stats_block}
{hltv_block}

Как тактик — оцени:
1. Мап-вето: какие карты выберут/забанят команды (опираясь на winrate по картам)
2. Ключевые игроки которые решат исход (AWPer, IGL, рейтинг)
3. Твой прогноз на победителя
4. Тотал карт: больше или меньше 2.5

Ответ краткий, 4-5 предложений."""
        client = _groq_client
        model = "llama-3.3-70b-versatile"

    try:
        result = _call_ai(prompt, client, model)
    except Exception as e:
        # Если Llama через Groq не сработала, пробуем еще раз с увеличенным таймаутом
        if agent_type == "llama-3.3":
            print(f"[CS2-Agents] Llama-3.3 агент упал с ошибкой: {e}. Пробую GPT-4.1-mini как запасной вариант.")
            # Fallback на GPT-4.1-mini, если Llama-3.3 не сработала
            result = _call_ai(prompt, _gpt_client, "gpt-4.1-mini", system_msg="Ты — профессиональный аналитик CS2 с 10-летним опытом. Отвечай на русском языке, кратко и по делу.")
            if isinstance(result, dict) and result.get("error"):
                result = f"❌ Ошибка Llama 3.3 и GPT-4.1-mini: {str(e)[:100]}"
        else:
            result = f"❌ Ошибка {model}: {str(e)[:100]}"
            
    return result


def build_cs2_ensemble(math_prob, ai_probs, news_factor=1.0):
    """
    Собирает ансамбль из математики и AI.
    math_prob: (prob_home, prob_away)
    ai_probs: list of (prob_home, prob_away)
    """
    weights = {"math": 0.50, "ai": 0.50}

    final_home = math_prob[0] * weights["math"]
    avg_ai_home = sum([p[0] for p in ai_probs]) / len(ai_probs) if ai_probs else math_prob[0]
    final_home += avg_ai_home * weights["ai"]
    final_home *= news_factor

    final_home = max(0.05, min(0.95, final_home))
    final_away = 1.0 - final_home
    return (round(final_home, 3), round(final_away, 3))
