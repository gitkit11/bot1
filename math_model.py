"""
Математическая модель для прогнозирования футбольных матчей.

Включает:
1. Распределение Пуассона + xG → вероятности точного счёта и тотала
2. ELO рейтинг → динамическая сила команды
3. Регрессия к среднему → корректировка на удачу
4. Взвешенный ансамбль всех компонентов
"""

import math
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── ELO РЕЙТИНГ ────────────────────────────────────────────────────────────

ELO_FILE = "elo_ratings.json"
FORM_FILE = "team_form.json"
DEFAULT_ELO = 1500
K_FACTOR = 32  # Чувствительность к результатам

# Начальные ELO для команд АПЛ (на основе исторических данных)
INITIAL_ELO = {
    "Manchester City": 1820,
    "Arsenal": 1760,
    "Liverpool": 1780,
    "Chelsea": 1700,
    "Tottenham Hotspur": 1680,
    "Manchester United": 1660,
    "Newcastle United": 1640,
    "Aston Villa": 1630,
    "West Ham United": 1590,
    "Brighton": 1600,
    "Brighton & Hove Albion": 1600,
    "Wolves": 1560,
    "Wolverhampton Wanderers": 1560,
    "Fulham": 1550,
    "Brentford": 1545,
    "Crystal Palace": 1540,
    "Everton": 1530,
    "Nottingham Forest": 1535,
    "Bournemouth": 1520,
    "Leicester City": 1510,
    "Leeds United": 1490,
    "Southampton": 1480,
    "Ipswich Town": 1470,
    "Burnley": 1460,
    "Luton Town": 1450,
    "Sheffield United": 1445,
}


def load_elo_ratings() -> dict:
    """Загружает ELO рейтинги из файла или возвращает начальные."""
    if os.path.exists(ELO_FILE):
        try:
            with open(ELO_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return dict(INITIAL_ELO)


def load_team_form() -> dict:
    """Загружает форму команд из файла. Возвращает dict {team: ['W','D','L',...]}"""
    if os.path.exists(FORM_FILE):
        try:
            with open(FORM_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_form_bonus(team: str, form_data: dict) -> float:
    """
    Считает бонус/штраф к ELO на основе формы последних 5 матчей.
    W=+8, D=0, L=-8 (максимум ±40 очков).
    Последние матчи важнее (веса 0.6 → 1.4).
    """
    results = form_data.get(team, [])
    if not results:
        return 0.0
    last5 = results[-5:]
    weights = [0.6, 0.8, 1.0, 1.2, 1.4]
    bonus = 0.0
    for i, res in enumerate(last5):
        w = weights[i] if i < len(weights) else 1.0
        if res == 'W':
            bonus += 8 * w
        elif res == 'L':
            bonus -= 8 * w
    return round(bonus, 1)


def get_form_string(team: str, form_data: dict) -> str:
    """Возвращает строку формы последних 5 матчей, например 'WWDLW'."""
    results = form_data.get(team, [])
    return ''.join(results[-5:]) if results else '?????'


def save_elo_ratings(ratings: dict):
    """Сохраняет ELO рейтинги в файл."""
    try:
        with open(ELO_FILE, 'w', encoding='utf-8') as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[ELO] Не удалось сохранить рейтинги: {e}")


def get_elo(team: str, ratings: dict) -> float:
    """Получить ELO рейтинг команды."""
    return ratings.get(team, DEFAULT_ELO)


def expected_score(elo_a: float, elo_b: float) -> float:
    """Ожидаемый результат для команды A против B по формуле ELO."""
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def update_elo(home_team: str, away_team: str, home_goals: int, away_goals: int,
               ratings: dict) -> dict:
    """
    Обновить ELO рейтинги после матча.
    home_goals, away_goals — реальный счёт матча.
    """
    elo_home = get_elo(home_team, ratings)
    elo_away = get_elo(away_team, ratings)

    # Домашнее преимущество +100 ELO
    elo_home_adj = elo_home + 100

    exp_home = expected_score(elo_home_adj, elo_away)
    exp_away = 1 - exp_home

    # Реальный результат
    if home_goals > away_goals:
        actual_home, actual_away = 1.0, 0.0
    elif home_goals == away_goals:
        actual_home, actual_away = 0.5, 0.5
    else:
        actual_home, actual_away = 0.0, 1.0

    # Обновляем рейтинги
    new_ratings = dict(ratings)
    new_ratings[home_team] = round(elo_home + K_FACTOR * (actual_home - exp_home), 1)
    new_ratings[away_team] = round(elo_away + K_FACTOR * (actual_away - exp_away), 1)

    return new_ratings


def elo_win_probabilities(home_team: str, away_team: str, ratings: dict,
                          form_data: dict = None) -> dict:
    """
    Рассчитать вероятности победы на основе ELO + форма последних 5 матчей.
    Возвращает {'home': float, 'draw': float, 'away': float, ...}
    """
    base_home_elo = get_elo(home_team, ratings)
    base_away_elo = get_elo(away_team, ratings)

    # Форма-бонус (если есть данные)
    home_form_bonus = get_form_bonus(home_team, form_data) if form_data else 0.0
    away_form_bonus = get_form_bonus(away_team, form_data) if form_data else 0.0
    home_form_str = get_form_string(home_team, form_data) if form_data else '?????'
    away_form_str = get_form_string(away_team, form_data) if form_data else '?????'

    # ELO + домашнее преимущество + форма
    elo_home = base_home_elo + 100 + home_form_bonus
    elo_away = base_away_elo + away_form_bonus

    exp_home = expected_score(elo_home, elo_away)

    # Конвертируем ELO вероятность в трёхисходную
    draw_prob = 0.25 - abs(exp_home - 0.5) * 0.1
    draw_prob = max(0.15, min(0.35, draw_prob))

    home_prob = exp_home * (1 - draw_prob)
    away_prob = (1 - exp_home) * (1 - draw_prob)

    total = home_prob + draw_prob + away_prob
    return {
        'home': round(home_prob / total, 4),
        'draw': round(draw_prob / total, 4),
        'away': round(away_prob / total, 4),
        'home_elo': base_home_elo,
        'away_elo': base_away_elo,
        'home_form': home_form_str,
        'away_form': away_form_str,
        'home_form_bonus': home_form_bonus,
        'away_form_bonus': away_form_bonus,
    }


# ─── РАСПРЕДЕЛЕНИЕ ПУАССОНА ──────────────────────────────────────────────────

def poisson_prob(lam: float, k: int) -> float:
    """P(X=k) для распределения Пуассона с параметром lambda."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def dc_correction(h: int, a: int, lam_h: float, lam_a: float, rho: float = -0.1) -> float:
    """
    Поправка Dixon-Coles для малых счётов (0:0, 1:0, 0:1, 1:1).
    Стандартный Пуассон недооценивает вероятность этих счётов.
    rho=-0.1 — оптимальное значение для футбола (по Dixon & Coles, 1997).
    """
    if h == 0 and a == 0:
        return 1 - lam_h * lam_a * rho
    elif h == 1 and a == 0:
        return 1 + lam_a * rho
    elif h == 0 and a == 1:
        return 1 + lam_h * rho
    elif h == 1 and a == 1:
        return 1 - rho
    return 1.0


def poisson_match_probabilities(home_xg: float, away_xg: float,
                                 max_goals: int = 7) -> dict:
    """
    Рассчитать вероятности исходов матча через распределение Пуассона + поправка Dixon-Coles.

    home_xg: ожидаемые голы хозяев (их xG атаки vs xGA гостей)
    away_xg: ожидаемые голы гостей

    Возвращает вероятности П1, Х, П2, тоталов и обе забьют.
    """
    # Матрица вероятностей счётов с поправкой Dixon-Coles
    score_matrix = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
            p *= dc_correction(h, a, home_xg, away_xg)  # Dixon-Coles поправка
            score_matrix[(h, a)] = p

    # Нормализуем (на случай обрезки)
    total = sum(score_matrix.values())
    if total > 0:
        score_matrix = {k: v / total for k, v in score_matrix.items()}

    # Исходы
    home_win = sum(p for (h, a), p in score_matrix.items() if h > a)
    draw = sum(p for (h, a), p in score_matrix.items() if h == a)
    away_win = sum(p for (h, a), p in score_matrix.items() if h < a)

    # Тоталы
    over_15 = sum(p for (h, a), p in score_matrix.items() if h + a > 1)
    over_25 = sum(p for (h, a), p in score_matrix.items() if h + a > 2)
    over_35 = sum(p for (h, a), p in score_matrix.items() if h + a > 3)
    under_25 = 1 - over_25

    # Обе забьют
    btts = sum(p for (h, a), p in score_matrix.items() if h > 0 and a > 0)

    # Наиболее вероятный счёт
    most_likely = max(score_matrix, key=score_matrix.get)

    return {
        'home_win': round(home_win, 4),
        'draw': round(draw, 4),
        'away_win': round(away_win, 4),
        'over_15': round(over_15, 4),
        'over_25': round(over_25, 4),
        'over_35': round(over_35, 4),
        'under_25': round(under_25, 4),
        'btts': round(btts, 4),
        'most_likely_score': f"{most_likely[0]}:{most_likely[1]}",
        'most_likely_score_prob': round(score_matrix[most_likely], 4),
        'home_xg': round(home_xg, 2),
        'away_xg': round(away_xg, 2),
    }


def calculate_expected_goals(home_team_stats: dict, away_team_stats: dict) -> tuple:
    """
    Рассчитать ожидаемые голы для матча на основе xG статистики.

    Формула:
    home_expected = (home_xg_attack + away_xga_defense) / 2 * home_advantage
    away_expected = (away_xg_attack + home_xga_defense) / 2

    Возвращает (home_xg, away_xg)
    """
    # Берём xG за последние 5 матчей (более актуально)
    home_xg_att = home_team_stats.get('avg_xg_last5', home_team_stats.get('avg_xg_season', 1.3))
    home_xga_def = home_team_stats.get('avg_xga_last5', home_team_stats.get('avg_xga_season', 1.3))
    away_xg_att = away_team_stats.get('avg_xg_last5', away_team_stats.get('avg_xg_season', 1.3))
    away_xga_def = away_team_stats.get('avg_xga_last5', away_team_stats.get('avg_xga_season', 1.3))

    # Домашнее преимущество +8%
    home_advantage = 1.08

    home_expected = ((home_xg_att + away_xga_def) / 2) * home_advantage
    away_expected = (away_xg_att + home_xga_def) / 2

    # Регрессия к среднему (лига ~1.35 голов за матч на команду)
    league_avg = 1.35
    regression = 0.3
    home_expected = home_expected * (1 - regression) + league_avg * regression
    away_expected = away_expected * (1 - regression) + league_avg * regression

    return round(home_expected, 3), round(away_expected, 3)


# ─── ВЗВЕШЕННЫЙ АНСАМБЛЬ ────────────────────────────────────────────────────

def ensemble_probabilities(
    prophet_probs: dict,      # {'home': 0.43, 'draw': 0.22, 'away': 0.35}
    elo_probs: dict,          # {'home': 0.48, 'draw': 0.25, 'away': 0.27}
    poisson_probs: dict,      # {'home_win': 0.45, 'draw': 0.26, 'away_win': 0.29}
    bookmaker_odds: dict,     # {'home': 1.72, 'draw': 3.5, 'away': 4.5}
) -> dict:
    """
    Взвешенный ансамбль всех математических моделей.

    Веса:
    - Пуассон (xG): 40% — самая точная модель для голов
    - ELO: 30% — лучшая модель для текущей формы
    - Пророк (нейросеть): 20% — исторические паттерны
    - Неявные вероятности букмекеров: 10% — умные деньги
    """
    # Конвертируем букмекерские КФ в вероятности (с маржой)
    book_probs = {}
    if bookmaker_odds:
        raw_home = 1 / bookmaker_odds.get('home', 2.0) if bookmaker_odds.get('home', 0) > 0 else 0.33
        raw_draw = 1 / bookmaker_odds.get('draw', 3.5) if bookmaker_odds.get('draw', 0) > 0 else 0.28
        raw_away = 1 / bookmaker_odds.get('away', 4.0) if bookmaker_odds.get('away', 0) > 0 else 0.25
        total = raw_home + raw_draw + raw_away
        if total > 0:
            book_probs = {
                'home': raw_home / total,
                'draw': raw_draw / total,
                'away': raw_away / total,
            }

    # Нормализуем Пуассон
    poisson_norm = {
        'home': poisson_probs.get('home_win', 0.33),
        'draw': poisson_probs.get('draw', 0.28),
        'away': poisson_probs.get('away_win', 0.33),
    }

    # Нормализуем Пророка
    prophet_norm = {
        'home': prophet_probs.get('home', 0.33),
        'draw': prophet_probs.get('draw', 0.33),
        'away': prophet_probs.get('away', 0.33),
    }

    # Нормализуем ELO
    elo_norm = {
        'home': elo_probs.get('home', 0.33),
        'draw': elo_probs.get('draw', 0.28),
        'away': elo_probs.get('away', 0.33),
    }

    # Веса
    w_poisson = 0.40
    w_elo = 0.30
    w_prophet = 0.20
    w_book = 0.10

    if not book_probs:
        # Перераспределяем вес букмекеров
        w_poisson, w_elo, w_prophet, w_book = 0.45, 0.35, 0.20, 0.0

    results = {}
    for outcome in ['home', 'draw', 'away']:
        results[outcome] = round(
            poisson_norm[outcome] * w_poisson +
            elo_norm[outcome] * w_elo +
            prophet_norm[outcome] * w_prophet +
            book_probs.get(outcome, 0.33) * w_book,
            4
        )

    # Нормализуем итог
    total = sum(results.values())
    if total > 0:
        results = {k: round(v / total, 4) for k, v in results.items()}

    return results


def calculate_value_bet(our_prob: float, bookmaker_odds: float) -> dict:
    """
    Рассчитать ценность ставки (Expected Value).

    EV = our_prob * odds - 1
    Ставка имеет ценность если EV > 0.05 (5%)
    """
    if bookmaker_odds <= 0 or our_prob <= 0:
        return {'ev': 0, 'kelly': 0, 'has_value': False}

    ev = our_prob * bookmaker_odds - 1
    # Критерий Келли: f = (p*b - q) / b, где b = odds-1
    b = bookmaker_odds - 1
    q = 1 - our_prob
    kelly = (our_prob * b - q) / b if b > 0 else 0
    kelly = max(0, min(kelly, 0.25))  # Ограничиваем 25% банка

    return {
        'ev': round(ev, 4),
        'ev_percent': round(ev * 100, 1),
        'kelly': round(kelly, 4),
        'kelly_percent': round(kelly * 100, 1),
        'has_value': ev > 0.05,  # Порог 5% EV
    }


def format_math_report(
    home_team: str,
    away_team: str,
    elo_probs: dict,
    poisson_probs: dict,
    ensemble_probs: dict,
    home_xg_stats: dict = None,
    away_xg_stats: dict = None,
) -> str:
    """Форматирует математический анализ для отображения в боте."""

    lines = ["📐 *МАТЕМАТИЧЕСКИЙ АНАЛИЗ:*"]

    # ELO
    home_elo = elo_probs.get('home_elo', 1500)
    away_elo = elo_probs.get('away_elo', 1500)
    lines.append(f"⚡ ELO: {home_team}={home_elo} | {away_team}={away_elo}")

    # xG если есть
    if home_xg_stats and away_xg_stats:
        lines.append(
            f"📊 xG (посл.5): {home_team}={home_xg_stats.get('avg_xg_last5','?')} | "
            f"{away_team}={away_xg_stats.get('avg_xg_last5','?')}"
        )

    # Пуассон
    lines.append(
        f"🎯 Пуассон: П1={round(poisson_probs['home_win']*100)}% | "
        f"Х={round(poisson_probs['draw']*100)}% | "
        f"П2={round(poisson_probs['away_win']*100)}%"
    )
    lines.append(
        f"   Тотал >2.5: {round(poisson_probs['over_25']*100)}% | "
        f"Обе забьют: {round(poisson_probs['btts']*100)}%"
    )
    lines.append(f"   Вероятный счёт: {poisson_probs['most_likely_score']} "
                 f"({round(poisson_probs['most_likely_score_prob']*100)}%)")

    # Ансамбль
    lines.append(
        f"🔢 Ансамбль: П1={round(ensemble_probs['home']*100)}% | "
        f"Х={round(ensemble_probs['draw']*100)}% | "
        f"П2={round(ensemble_probs['away']*100)}%"
    )

    return "\n".join(lines)
