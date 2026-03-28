# -*- coding: utf-8 -*-
"""
Автоматическая проверка результатов хоккейных матчей.
Вызывается каждый час из main.py.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

try:
    from config import THE_ODDS_API_KEY
except ImportError:
    THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")

ELO_K = 20  # Константа Elo для обновления рейтингов

HOCKEY_RESULT_LEAGUES = [
    "icehockey_nhl",
    "icehockey_sweden_hockey_league",
    "icehockey_ahl",
    "icehockey_liiga",
    "icehockey_sweden_allsvenskan",
]


def _fetch_scores(league_key: str) -> list:
    if not THE_ODDS_API_KEY:
        return []
    try:
        from odds_cache import get_scores as _get_scores
        return _get_scores(league_key, days_from=3)
    except ImportError:
        pass
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{league_key}/scores/",
            params={"apiKey": THE_ODDS_API_KEY, "daysFrom": 3},
            timeout=10,
        )
        return r.json() if r.ok else []
    except Exception as e:
        logger.warning(f"[Hockey results] scores fetch {league_key}: {e}")
    return []


def _update_elo(home: str, away: str, h_score: int, a_score: int):
    """Обновляет elo_hockey.json после матча."""
    import json
    path = "elo_hockey.json"
    try:
        from sports.hockey.core import NHL_ELO, SHL_ELO, DEFAULT_ELO
        try:
            with open(path, "r", encoding="utf-8") as f:
                elo = json.load(f)
        except FileNotFoundError:
            elo = {}

        def _get(team):
            return elo.get(team) or NHL_ELO.get(team) or SHL_ELO.get(team) or DEFAULT_ELO

        r_h = _get(home)
        r_a = _get(away)
        exp_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        exp_a = 1 - exp_h
        act_h = 1 if h_score > a_score else (0.5 if h_score == a_score else 0)
        act_a = 1 - act_h
        elo[home] = round(r_h + ELO_K * (act_h - exp_h))
        elo[away] = round(r_a + ELO_K * (act_a - exp_a))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(elo, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Hockey ELO] update error: {e}")


def check_and_update_hockey_results() -> int:
    """
    Проверяет завершённые матчи и обновляет БД.
    Возвращает количество обновлённых записей.
    """
    try:
        from database import get_pending_predictions, update_result
    except ImportError:
        logger.warning("[Hockey results] database not available")
        return 0

    pending = get_pending_predictions("hockey")
    if not pending:
        return 0

    # Собираем результаты по всем лигам
    all_scores: list = []
    for league_key in HOCKEY_RESULT_LEAGUES:
        all_scores.extend(_fetch_scores(league_key))

    if not all_scores:
        return 0

    updated = 0
    for pred in pending:
        match_id  = pred.get("match_id", "")
        home_team = pred.get("home_team", "")
        away_team = pred.get("away_team", "")

        for score in all_scores:
            if not score.get("completed"):
                continue

            score_id   = score.get("id", "")
            score_home = score.get("home_team", "")
            score_away = score.get("away_team", "")

            # Сопоставляем по match_id или командам
            match_found = (
                score_id == match_id
                or (score_home == home_team and score_away == away_team)
            )
            if not match_found:
                continue

            raw_scores = score.get("scores") or []
            score_map  = {s["name"]: int(s["score"]) for s in raw_scores
                          if s.get("name") and s.get("score")}
            h_score = score_map.get(score_home, 0)
            a_score = score_map.get(score_away, 0)

            if h_score > a_score:
                real_outcome = "home_win"
            elif a_score > h_score:
                real_outcome = "away_win"
            else:
                real_outcome = "draw"

            rec_outcome = pred.get("recommended_outcome", "")
            is_correct  = 1 if rec_outcome == real_outcome else 0

            # ROI: победа = (odds - 1), проигрыш = -1
            rec_odds = pred.get("bookmaker_odds_home") if rec_outcome == "home_win" else pred.get("bookmaker_odds_away")
            try:
                roi = round((float(rec_odds) - 1) if is_correct else -1.0, 3)
            except Exception:
                roi = -1.0 if not is_correct else None

            update_result(
                sport="hockey",
                match_id=match_id,
                real_home_score=h_score,
                real_away_score=a_score,
                real_outcome=real_outcome,
                is_correct=is_correct,
                roi_outcome=roi,
            )
            _update_elo(score_home, score_away, h_score, a_score)
            updated += 1
            break

    if updated:
        logger.info(f"[Hockey results] Обновлено {updated} прогнозов")
    return updated
