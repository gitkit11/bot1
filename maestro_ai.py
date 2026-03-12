# -*- coding: utf-8 -*-
"""
maestro_ai.py — ИИ #3 "Маэстро"
Ансамблевая система и поиск выгодных ставок (Value Bets).

ВАЖНО: Все ключи берутся из config.py (который читает .env).
Никаких хардкодированных ключей в этом файле!
"""

import numpy as np
import json
import os
import requests
import warnings
warnings.filterwarnings("ignore")

# Ключи из конфига (не хардкодить!)
try:
    from config import THE_ODDS_API_KEY
except ImportError:
    THE_ODDS_API_KEY = os.environ.get('THE_ODDS_API_KEY', '')

THE_ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"


# ============================================================
# ПОЛУЧЕНИЕ КОЭФФИЦИЕНТОВ БУКМЕКЕРОВ
# ============================================================
def get_bookmaker_odds(home_team, away_team):
    """
    Получает актуальные коэффициенты букмекеров через The Odds API.
    Возвращает словарь с вероятностями для каждого исхода.
    """
    try:
        params = {
            'apiKey': THE_ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h',
            'oddsFormat': 'decimal'
        }
        response = requests.get(THE_ODDS_API_URL, params=params, timeout=10)
        data = response.json()

        for game in data:
            if (home_team.lower() in game.get('home_team', '').lower() or
                    away_team.lower() in game.get('away_team', '').lower()):
                for bookmaker in game.get('bookmakers', []):
                    for market in bookmaker.get('markets', []):
                        if market['key'] == 'h2h':
                            outcomes = {o['name']: o['price'] for o in market['outcomes']}
                            return outcomes

        return None
    except Exception as e:
        print(f"  [Маэстро] Ошибка получения коэффициентов: {e}")
        return None


def odds_to_probability(odds):
    """Конвертирует десятичный коэффициент в вероятность."""
    if odds and odds > 1:
        return round(1 / odds, 4)
    return 0.0


# ============================================================
# АНСАМБЛЬ — используем правильную функцию из agents.py
# (старая ensemble_predictions() удалена — она была сломана)
# ============================================================
def get_ensemble_probs(prophet_probs, poisson_probs=None, elo_probs=None,
                       gpt_result=None, llama_result=None, mixtral_result=None,
                       bookmaker_odds=None):
    """
    Делегирует расчёт ансамбля в build_math_ensemble() из agents.py.
    Это единственное место где считается ансамбль — нет дублирования.
    """
    try:
        from agents import build_math_ensemble
        return build_math_ensemble(
            prophet_probs, poisson_probs, elo_probs,
            gpt_result, llama_result, mixtral_result,
            bookmaker_odds
        )
    except Exception as e:
        print(f"[Маэстро] Ошибка ансамбля: {e}")
        # Fallback: только Пророк
        return {
            'home': float(prophet_probs[1]) if prophet_probs else 0.33,
            'draw': float(prophet_probs[0]) if prophet_probs else 0.33,
            'away': float(prophet_probs[2]) if prophet_probs else 0.34,
        }


# ============================================================
# ПОИСК VALUE BETS
# ============================================================
def find_value_bets(ai_probs, bookmaker_odds, home_team, away_team):
    """
    Ищет ставки с положительным ожидаемым значением (Value Bets).

    Пороги (профессиональные):
    - EV > 10% (не 5% — слишком много ложных сигналов)
    - Коэффициент >= 1.55 (не брать очевидных фаворитов)
    - Наша уверенность >= 52%
    """
    MIN_EV = 0.10       # минимум 10% EV
    MIN_ODDS = 1.55     # не брать очевидных фаворитов
    MIN_PROB = 0.52     # наша уверенность минимум 52%

    value_bets = []

    if not bookmaker_odds:
        return value_bets

    outcomes_map = {
        'home_win': home_team,
        'draw': 'Draw',
        'away_win': away_team
    }

    for outcome_key, team_name in outcomes_map.items():
        our_prob = ai_probs.get(outcome_key, 0)
        bookie_odds = bookmaker_odds.get(team_name, None)

        if bookie_odds and our_prob > 0:
            ev = (our_prob * bookie_odds) - 1
            implied_prob = odds_to_probability(bookie_odds)

            if ev > MIN_EV and bookie_odds >= MIN_ODDS and our_prob >= MIN_PROB:
                value_bets.append({
                    'outcome': outcome_key,
                    'team': team_name,
                    'our_probability': our_prob,
                    'implied_probability': implied_prob,
                    'bookmaker_odds': bookie_odds,
                    'expected_value': round(ev, 4),
                    'edge': round(our_prob - implied_prob, 4)
                })

    value_bets.sort(key=lambda x: x['expected_value'], reverse=True)
    return value_bets


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ МАЭСТРО
# ============================================================
def maestro_analyze(home_team, away_team, prophet_probs, oracle_results,
                    poisson_probs=None, elo_probs=None,
                    gpt_result=None, llama_result=None, mixtral_result=None):
    """
    Главная функция ИИ #3 "Маэстро".
    Использует правильный взвешенный ансамбль из agents.py.
    """
    print(f"\n[Маэстро] Финальный анализ: {home_team} vs {away_team}")

    # Получаем коэффициенты букмекеров
    bookmaker_odds = get_bookmaker_odds(home_team, away_team)

    # Ансамбль через правильную функцию
    final_probs = get_ensemble_probs(
        prophet_probs, poisson_probs, elo_probs,
        gpt_result, llama_result, mixtral_result,
        bookmaker_odds
    )

    # Ищем value bets
    value_bets = find_value_bets(final_probs, bookmaker_odds, home_team, away_team)

    # Определяем основной прогноз
    best_outcome = max(['home', 'draw', 'away'], key=lambda k: final_probs.get(k, 0))
    outcome_names = {
        'home': f'Победа {home_team}',
        'draw': 'Ничья',
        'away': f'Победа {away_team}'
    }
    main_prediction = outcome_names[best_outcome]
    confidence = final_probs.get(best_outcome, 0)

    result = {
        'home_team': home_team,
        'away_team': away_team,
        'final_probabilities': final_probs,
        'main_prediction': main_prediction,
        'confidence': confidence,
        'bookmaker_odds': bookmaker_odds,
        'value_bets': value_bets,
    }

    return result


# ============================================================
# ТЕСТОВЫЙ ЗАПУСК
# ============================================================
if __name__ == "__main__":
    test_prophet_probs = [0.177, 0.720, 0.103]
    test_oracle_results = {
        "Manchester City": {"sentiment_score": 0.5811},
        "Arsenal": {"sentiment_score": -0.0292}
    }

    analysis = maestro_analyze(
        "Manchester City", "Arsenal",
        test_prophet_probs, test_oracle_results
    )
    print(f"Прогноз: {analysis['main_prediction']} ({analysis['confidence']*100:.1f}%)")
    print(f"Value bets: {len(analysis['value_bets'])}")
