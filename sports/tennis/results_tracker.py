# -*- coding: utf-8 -*-
"""
sports/tennis/results_tracker.py — Авто-проверка результатов теннисных матчей.

Использует api-tennis.com: метод get_fixtures с фильтром status=finished.
Вызывается из check_results_task в main.py каждый час.
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def _norm(name: str) -> str:
    """Нормализует имя игрока для сопоставления."""
    return name.lower().strip()


def _last_name(name: str) -> str:
    """Возвращает фамилию игрока (последнее слово)."""
    parts = name.strip().split()
    return parts[-1].lower() if parts else name.lower()


def get_finished_tennis_matches(days_back: int = 3) -> list:
    """
    Получает завершённые теннисные матчи из api-tennis.com за последние N дней.
    Возвращает список dict: {p1, p2, winner, p1_score, p2_score, date}
    """
    try:
        import requests
        try:
            from config import API_TENNIS_KEY
        except ImportError:
            import os
            API_TENNIS_KEY = os.getenv("API_TENNIS_KEY", "")

        if not API_TENNIS_KEY:
            return []

        today     = datetime.now(timezone.utc)
        date_from = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        date_to   = today.strftime("%Y-%m-%d")

        r = requests.get(
            "https://api.api-tennis.com/tennis/",
            params={
                "method":     "get_fixtures",
                "APIkey":     API_TENNIS_KEY,
                "date_start": date_from,
                "date_stop":  date_to,
            },
            timeout=20,
        )
        data = r.json()
        is_ok = (data.get("error") in ("0", 0)) or (data.get("success") in (1, "1"))
        if not is_ok:
            return []

        results = []
        for m in data.get("result", []):
            if m.get("event_status", "").lower() != "finished":
                continue
            # Только одиночные
            etype = m.get("event_type_type", "").lower()
            if "double" in etype or "mixed" in etype:
                continue

            p1     = m.get("event_first_player", "").strip()
            p2     = m.get("event_second_player", "").strip()
            winner = m.get("event_winner", "")  # "First Player" / "Second Player"

            if not p1 or not p2 or not winner:
                continue

            actual_winner = p1 if winner == "First Player" else p2

            # Определяем поверхность из данных API или по названию турнира
            surface_raw = (m.get("event_ground") or m.get("surface") or "hard").lower()
            if "clay" in surface_raw:
                surface = "clay"
            elif "grass" in surface_raw:
                surface = "grass"
            else:
                surface = "hard"

            results.append({
                "p1":      p1,
                "p2":      p2,
                "winner":  actual_winner,
                "date":    m.get("event_date", ""),
                "score":   m.get("event_final_result", ""),
                "surface": surface,
            })

        return results

    except Exception as e:
        logger.error(f"[Tennis Tracker] Ошибка получения результатов: {e}")
        return []


def check_and_update_tennis_results() -> int:
    """
    Основная функция: сопоставляет pending теннисные прогнозы с результатами.
    Возвращает количество обновлённых записей.
    """
    try:
        from database import get_pending_predictions, update_result
    except ImportError:
        logger.error("[Tennis Tracker] Не удалось импортировать database")
        return 0

    pending = get_pending_predictions("tennis")
    if not pending:
        return 0

    finished = get_finished_tennis_matches(days_back=3)
    if not finished:
        logger.info("[Tennis Tracker] Нет завершённых матчей за 3 дня")
        return 0

    # Индекс по фамилиям: (last_name_p1, last_name_p2) → match
    finished_by_name: dict = {}
    for m in finished:
        k1 = (_last_name(m["p1"]), _last_name(m["p2"]))
        k2 = (_last_name(m["p2"]), _last_name(m["p1"]))
        finished_by_name[k1] = m
        finished_by_name[k2] = m

    updated = 0

    for pred in pending:
        home = pred.get("home_team", "")  # player1
        away = pred.get("away_team", "")  # player2

        key = (_last_name(home), _last_name(away))
        result = finished_by_name.get(key)

        if result is None:
            continue

        winner = result["winner"]
        # Определяем исход относительно home (player1)
        if _last_name(winner) == _last_name(home):
            actual_outcome = "home_win"
        else:
            actual_outcome = "away_win"

        recommended = pred.get("recommended_outcome", "")
        is_correct  = 1 if recommended == actual_outcome else 0

        # ROI — считаем только если была рекомендована ставка
        _bet_sig = pred.get("bet_signal", "")
        if "СТАВИТЬ" in _bet_sig:
            if is_correct:
                odds_key = "bookmaker_odds_home" if actual_outcome == "home_win" else "bookmaker_odds_away"
                odds = float(pred.get(odds_key) or 1.85)
                roi  = round(odds - 1, 3)
            else:
                roi = -1.0
        else:
            roi = None

        try:
            update_result(
                sport="tennis",
                match_id=pred["match_id"],
                real_home_score=1 if actual_outcome == "home_win" else 0,
                real_away_score=0 if actual_outcome == "home_win" else 1,
                real_outcome=actual_outcome,
                is_correct=is_correct,
                roi_outcome=roi,
            )
            updated += 1
            icon = "✅" if is_correct else "❌"
            logger.info(
                f"[Tennis Tracker] {icon} {home} vs {away} → {winner} "
                f"(прогноз: {recommended})"
            )

            # Обновляем surface ELO
            try:
                from sports.tennis.rankings import update_surface_elo, detect_tour
                surface = result.get("surface", "hard")
                loser   = away if actual_outcome == "home_win" else home
                tour    = "wta" if "wta" in pred.get("sport_key", "").lower() else "atp"
                update_surface_elo(winner, loser, surface, tour)
            except Exception as elo_err:
                logger.warning(f"[Tennis ELO] update failed: {elo_err}")

        except Exception as e:
            logger.error(f"[Tennis Tracker] Ошибка update_result {home} vs {away}: {e}")

    if updated:
        logger.info(f"[Tennis Tracker] Обновлено прогнозов: {updated}")
    return updated
