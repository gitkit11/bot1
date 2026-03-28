# -*- coding: utf-8 -*-
"""
Football Results Tracker — авто-проверка результатов и обновление ELO.

Как работает:
1. Берёт непроверенные прогнозы футбола из БД
2. Запрашивает завершённые матчи через The Odds API /scores/ (odds_cache)
3. Сопоставляет по ID матча, затем по нормализованным именам команд
4. Обновляет is_correct, is_ensemble_correct, roi_outcome, value_bet_correct
5. Записывает матч в ml/data/live_matches.csv для переобучения XGBoost
6. Вызывает on_elo_update(home, away, home_score, away_score) если передан
"""

import os
import re
import csv
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCORES_LEAGUES = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_usa_mls",
    "soccer_brazil_campeonato",
    "soccer_argentina_primera_division",
    "soccer_uefa_champs_league",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league",
    "soccer_uefa_europa_league",
]

_LIVE_CSV_COLS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
                  "B365H", "B365D", "B365A", "league", "season"]
_LIVE_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "data", "live_matches.csv")


def _norm_team_name(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r'\b(fc|afc|sc|cf|ac|as|ss|rc|vf[bl]|rb|bsc|rcd|ca)\b', '', n)
    n = re.sub(r'\bunited\b', 'utd', n)
    n = re.sub(r'\bhotspur\b', '', n)
    n = re.sub(r'\bwanderers\b', '', n)
    n = re.sub(r'[^a-z0-9 ]', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def record_match_for_training(pred: dict, home_score: int, away_score: int, outcome: str):
    """Записывает сыгранный матч в live_matches.csv. Дубликаты пропускаются."""
    date_str = (pred.get("match_date") or "")[:10]
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    else:
        try:
            date_str = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            pass

    ftr = "H" if outcome == "home_win" else ("A" if outcome == "away_win" else "D")
    row = {
        "Date":     date_str,
        "HomeTeam": pred.get("home_team", ""),
        "AwayTeam": pred.get("away_team", ""),
        "FTHG":     home_score,
        "FTAG":     away_score,
        "FTR":      ftr,
        "B365H":    pred.get("bookmaker_odds_home") or "",
        "B365D":    pred.get("bookmaker_odds_draw") or "",
        "B365A":    pred.get("bookmaker_odds_away") or "",
        "league":   pred.get("league", "soccer_epl"),
        "season":   "live",
    }

    write_header = not os.path.exists(_LIVE_CSV)
    try:
        if not write_header:
            with open(_LIVE_CSV, "r", encoding="utf-8") as f:
                for existing in csv.DictReader(f):
                    if (existing.get("HomeTeam") == row["HomeTeam"] and
                            existing.get("AwayTeam") == row["AwayTeam"] and
                            existing.get("Date") == row["Date"]):
                        return  # уже записан
        with open(_LIVE_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_LIVE_CSV_COLS)
            if write_header:
                w.writeheader()
            w.writerow(row)
        logger.info(f"[Football ML] Записан: {row['HomeTeam']} {home_score}:{away_score} {row['AwayTeam']}")
    except Exception as e:
        logger.error(f"[Football ML] Ошибка CSV: {e}")


def get_finished_football_matches(leagues: list) -> tuple:
    """
    Возвращает (by_id, by_name) завершённых матчей из The Odds API.
    by_id   = {match_id: (home_score, away_score)}
    by_name = {(norm_home, norm_away): (home_score, away_score)}
    """
    by_id: dict = {}
    by_name: dict = {}
    try:
        from odds_cache import get_scores as _get_scores
    except ImportError:
        logger.error("[Football Tracker] odds_cache недоступен")
        return by_id, by_name

    for league in leagues:
        try:
            scores_raw = _get_scores(league, days_from=7)
            for s in scores_raw:
                if not s.get('completed'):
                    continue
                sc = s.get('scores', [])
                home_team = s.get('home_team', '')
                away_team = s.get('away_team', '')
                home_score = away_score = None
                for sc_item in sc:
                    if sc_item['name'] == home_team:
                        home_score = int(sc_item['score'])
                    elif sc_item['name'] == away_team:
                        away_score = int(sc_item['score'])
                if home_score is not None and away_score is not None:
                    by_id[s['id']] = (home_score, away_score)
                    key = (_norm_team_name(home_team), _norm_team_name(away_team))
                    by_name[key] = (home_score, away_score)
        except Exception as e:
            logger.error(f"[Football Tracker] Ошибка лиги {league}: {e}")

    return by_id, by_name


def check_and_update_football_results(on_elo_update=None) -> int:
    """
    Основная функция. Вызывается каждый час из main.py.
    on_elo_update: callable(home, away, home_score, away_score) — колбэк для ELO
    Возвращает количество обновлённых прогнозов.
    """
    try:
        from database import get_pending_predictions, update_result
    except ImportError:
        logger.error("[Football Tracker] Не удалось импортировать database")
        return 0

    pending = get_pending_predictions("football")
    if not pending:
        logger.info("[Football Tracker] Нет непроверенных прогнозов футбола")
        return 0

    pending_leagues = set(p.get("league", "") for p in pending if p.get("league"))
    leagues_to_check = [
        lg for lg in SCORES_LEAGUES
        if any(lg in pl or pl in lg for pl in pending_leagues)
    ] or SCORES_LEAGUES[:3]

    all_scores, all_scores_by_name = get_finished_football_matches(leagues_to_check)
    logger.info(f"[Football Tracker] Получено {len(all_scores)} завершённых матчей")

    updated = 0
    for pred in pending:
        match_id = pred['match_id']
        home = pred['home_team']
        away = pred['away_team']

        score_pair = all_scores.get(match_id)
        if score_pair is None:
            name_key = (_norm_team_name(home), _norm_team_name(away))
            score_pair = all_scores_by_name.get(name_key)
            if score_pair:
                logger.info(f"[Football Tracker] Совпадение по именам: {home} vs {away}")

        if score_pair is None:
            logger.debug(f"[Football Tracker] Нет данных: {home} vs {away} (id={match_id})")
            continue

        home_score, away_score = score_pair
        try:
            # Реальный исход
            if home_score > away_score:
                real_outcome = "home_win"
            elif away_score > home_score:
                real_outcome = "away_win"
            else:
                real_outcome = "draw"

            recommended = pred.get('recommended_outcome') or ''
            bet_signal  = pred.get('bet_signal', '')

            if not recommended:
                is_correct = None
                roi = None
            else:
                is_correct = 1 if recommended == real_outcome else 0
                if bet_signal == 'СТАВИТЬ' and is_correct:
                    if real_outcome == "home_win":
                        win_odds = float(pred.get('bookmaker_odds_home') or 0)
                    elif real_outcome == "away_win":
                        win_odds = float(pred.get('bookmaker_odds_away') or 0)
                    else:
                        win_odds = float(pred.get('bookmaker_odds_draw') or 0)
                    roi = round(win_odds - 1, 3) if win_odds >= 1.02 else None
                elif bet_signal == 'СТАВИТЬ' and not is_correct:
                    roi = -1.0
                else:
                    roi = None

            # Ансамбль
            ensemble_best = pred.get('ensemble_best_outcome', '')
            is_ensemble_correct = (1 if ensemble_best == real_outcome else 0) if ensemble_best else None

            # Тотал голов
            total_pred = pred.get('total_goals_prediction', '') or ''
            is_goals_correct = None
            if total_pred:
                total_goals = home_score + away_score
                if 'over' in total_pred.lower() or 'больше' in total_pred.lower():
                    is_goals_correct = 1 if total_goals >= 3 else 0
                elif 'under' in total_pred.lower() or 'меньше' in total_pred.lower():
                    is_goals_correct = 1 if total_goals <= 2 else 0

            # BTTS
            btts_pred = pred.get('btts_prediction', '') or ''
            is_btts_correct = None
            if btts_pred:
                btts_real = home_score > 0 and away_score > 0
                if 'да' in btts_pred.lower() or 'yes' in btts_pred.lower():
                    is_btts_correct = 1 if btts_real else 0
                elif 'нет' in btts_pred.lower() or 'no' in btts_pred.lower():
                    is_btts_correct = 1 if not btts_real else 0

            # Value bet
            vb_outcome = pred.get('value_bet_outcome', '') or ''
            vb_correct = None
            roi_vb = None
            if vb_outcome:
                vb_correct = 1 if vb_outcome == real_outcome else 0
                roi_vb = round(float(pred.get('value_bet_odds') or 1.85) - 1, 3) if vb_correct else -1.0

            update_result(
                sport='football',
                match_id=match_id,
                real_home_score=home_score,
                real_away_score=away_score,
                real_outcome=real_outcome,
                is_correct=is_correct,
                is_ensemble_correct=is_ensemble_correct,
                is_goals_correct=is_goals_correct,
                is_btts_correct=is_btts_correct,
                roi_outcome=roi,
                roi_value_bet=roi_vb,
                value_bet_correct=vb_correct,
            )
            updated += 1

            icon     = "✅" if is_correct else "❌"
            ens_icon = (f" [Анс: {'✅' if is_ensemble_correct == 1 else '❌'}]"
                        if is_ensemble_correct is not None else "")
            vb_icon  = (f" [VB: {'✅' if vb_correct == 1 else '❌'}]"
                        if vb_correct is not None else "")
            logger.info(f"[Football Tracker] {icon} {home} {home_score}:{away_score} {away}{ens_icon}{vb_icon}")

            if on_elo_update:
                try:
                    on_elo_update(home, away, home_score, away_score)
                except Exception as _elo_e:
                    logger.error(f"[Football Tracker] ELO ошибка: {_elo_e}")

            try:
                record_match_for_training(pred, home_score, away_score, real_outcome)
            except Exception as _rec_e:
                logger.error(f"[Football Tracker] ML Record ошибка: {_rec_e}")

        except Exception as e:
            logger.error(f"[Football Tracker] Ошибка {home} vs {away}: {e}")

    logger.info(f"[Football Tracker] Обновлено прогнозов: {updated}")
    return updated
