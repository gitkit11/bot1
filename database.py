import sqlite3
import json
from datetime import datetime, timezone

DB_FILE = "chimera_predictions.db"

def init_db():
    """Инициализирует базу данных и создаёт таблицы."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT DEFAULT 'soccer_epl',

            -- Прогнозы агентов
            gpt_verdict TEXT,
            llama_verdict TEXT,
            mixtral_verdict TEXT,
            gpt_confidence INTEGER,
            llama_confidence INTEGER,
            mixtral_confidence INTEGER,
            bet_signal TEXT,
            recommended_outcome TEXT,
            total_goals_prediction TEXT,
            btts_prediction TEXT,

            -- Математические модели
            poisson_home_win REAL,
            poisson_draw REAL,
            poisson_away_win REAL,
            poisson_over25 REAL,
            poisson_btts REAL,
            poisson_data_source TEXT,
            elo_home INTEGER,
            elo_away INTEGER,
            elo_home_win REAL,
            elo_draw REAL,
            elo_away_win REAL,

            -- Ансамбль
            ensemble_home REAL,
            ensemble_draw REAL,
            ensemble_away REAL,
            ensemble_best_outcome TEXT,

            -- Value ставки (первая/лучшая)
            value_bet_outcome TEXT,
            value_bet_odds REAL,
            value_bet_ev REAL,
            value_bet_kelly REAL,
            value_bet_correct INTEGER,

            -- Букмекерские коэффициенты
            bookmaker_odds_home REAL,
            bookmaker_odds_draw REAL,
            bookmaker_odds_away REAL,
            bookmaker_odds_over25 REAL,
            bookmaker_odds_under25 REAL,

            -- Результат матча
            real_home_score INTEGER,
            real_away_score INTEGER,
            real_outcome TEXT,
            is_correct INTEGER,
            is_goals_correct INTEGER,
            is_btts_correct INTEGER,
            is_ensemble_correct INTEGER,
            result_checked_at TIMESTAMP,

            -- ROI расчёт
            roi_outcome REAL,       -- прибыль/убыток по исходу (в единицах ставки)
            roi_value_bet REAL,     -- прибыль/убыток по value ставке

            -- Мета
            prediction_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Миграция: добавляем новые колонки если их нет (для существующих БД)
        new_columns = [
            ("league", "TEXT DEFAULT 'soccer_epl'"),
            ("mixtral_verdict", "TEXT"),
            ("mixtral_confidence", "INTEGER"),
            ("poisson_home_win", "REAL"),
            ("poisson_draw", "REAL"),
            ("poisson_away_win", "REAL"),
            ("poisson_over25", "REAL"),
            ("poisson_btts", "REAL"),
            ("poisson_data_source", "TEXT"),
            ("elo_home", "INTEGER"),
            ("elo_away", "INTEGER"),
            ("elo_home_win", "REAL"),
            ("elo_draw", "REAL"),
            ("elo_away_win", "REAL"),
            ("ensemble_home", "REAL"),
            ("ensemble_draw", "REAL"),
            ("ensemble_away", "REAL"),
            ("ensemble_best_outcome", "TEXT"),
            ("value_bet_outcome", "TEXT"),
            ("value_bet_odds", "REAL"),
            ("value_bet_ev", "REAL"),
            ("value_bet_kelly", "REAL"),
            ("value_bet_correct", "INTEGER"),
            ("is_ensemble_correct", "INTEGER"),
            ("roi_outcome", "REAL"),
            ("roi_value_bet", "REAL"),
        ]
        existing = {row[1] for row in cursor.execute("PRAGMA table_info(predictions)").fetchall()}
        for col_name, col_def in new_columns:
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE predictions ADD COLUMN {col_name} {col_def}")
                print(f"[База данных] Добавлена колонка: {col_name}")

        conn.commit()
        print("[База данных] База данных инициализирована.")


def save_prediction(match_id, match_date, home_team, away_team, prediction_data):
    """Сохраняет прогноз в базу данных."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        gpt_v = prediction_data.get("gpt_verdict", "")
        llama_v = prediction_data.get("llama_verdict", prediction_data.get("gemini_verdict", ""))
        mixtral_v = prediction_data.get("mixtral_verdict", "")
        recommended = gpt_v if gpt_v else llama_v

        # Ансамбль
        ensemble = prediction_data.get("ensemble_probs", {})
        ens_home = ensemble.get("home") if ensemble else None
        ens_draw = ensemble.get("draw") if ensemble else None
        ens_away = ensemble.get("away") if ensemble else None
        ens_best = prediction_data.get("ensemble_best_outcome", "")

        # Пуассон
        poisson = prediction_data.get("poisson_probs", {})
        p_home = poisson.get("home_win") if poisson else None
        p_draw = poisson.get("draw") if poisson else None
        p_away = poisson.get("away_win") if poisson else None
        p_over25 = poisson.get("over_25") if poisson else None
        p_btts = poisson.get("btts") if poisson else None
        p_src = poisson.get("data_source", "") if poisson else ""

        # ELO
        elo = prediction_data.get("elo_probs", {})
        elo_h = elo.get("home_elo") if elo else None
        elo_a = elo.get("away_elo") if elo else None
        elo_hw = elo.get("home") if elo else None
        elo_d = elo.get("draw") if elo else None
        elo_aw = elo.get("away") if elo else None

        # Value bet (лучшая)
        value_bets = prediction_data.get("value_bets", [])
        vb_outcome = value_bets[0]["outcome"] if value_bets else ""
        vb_odds = value_bets[0]["odds"] if value_bets else None
        vb_ev = value_bets[0]["ev"] if value_bets else None
        vb_kelly = value_bets[0]["kelly"] if value_bets else None

        cursor.execute("""
        INSERT OR REPLACE INTO predictions (
            match_id, match_date, home_team, away_team, league,
            gpt_verdict, llama_verdict, mixtral_verdict,
            gpt_confidence, llama_confidence, mixtral_confidence,
            bet_signal, recommended_outcome,
            total_goals_prediction, btts_prediction,
            poisson_home_win, poisson_draw, poisson_away_win,
            poisson_over25, poisson_btts, poisson_data_source,
            elo_home, elo_away, elo_home_win, elo_draw, elo_away_win,
            ensemble_home, ensemble_draw, ensemble_away, ensemble_best_outcome,
            value_bet_outcome, value_bet_odds, value_bet_ev, value_bet_kelly,
            bookmaker_odds_home, bookmaker_odds_draw, bookmaker_odds_away,
            bookmaker_odds_over25, bookmaker_odds_under25,
            prediction_data
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?
        )
        """, (
            match_id, match_date, home_team, away_team,
            prediction_data.get("league", "soccer_epl"),
            gpt_v, llama_v, mixtral_v,
            prediction_data.get("gpt_confidence", 0),
            prediction_data.get("llama_confidence", prediction_data.get("gemini_confidence", 0)),
            prediction_data.get("mixtral_confidence", 0),
            prediction_data.get("bet_signal", ""),
            recommended,
            prediction_data.get("total_goals", ""),
            prediction_data.get("btts", ""),
            p_home, p_draw, p_away, p_over25, p_btts, p_src,
            elo_h, elo_a, elo_hw, elo_d, elo_aw,
            ens_home, ens_draw, ens_away, ens_best,
            vb_outcome, vb_odds, vb_ev, vb_kelly,
            prediction_data.get("odds_home", 0),
            prediction_data.get("odds_draw", 0),
            prediction_data.get("odds_away", 0),
            prediction_data.get("odds_over25", 0),
            prediction_data.get("odds_under25", 0),
            json.dumps(prediction_data, ensure_ascii=False)
        ))
        conn.commit()
        print(f"[База данных] Прогноз для матча {home_team} vs {away_team} сохранён.")


def update_result(match_id, home_score, away_score):
    """Обновляет реальный результат матча и проверяет все прогнозы + считает ROI."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        row = cursor.execute("""
            SELECT home_team, away_team, recommended_outcome,
                   total_goals_prediction, btts_prediction,
                   ensemble_best_outcome,
                   value_bet_outcome, value_bet_odds,
                   bookmaker_odds_home, bookmaker_odds_draw, bookmaker_odds_away,
                   bet_signal
            FROM predictions WHERE match_id = ?
        """, (match_id,)).fetchone()

        if not row:
            return False

        (home_team, away_team, recommended_outcome,
         total_goals_pred, btts_pred,
         ensemble_best, vb_outcome, vb_odds,
         odds_home, odds_draw, odds_away,
         bet_signal) = row

        # Реальный исход
        if home_score > away_score:
            real_outcome = home_team
        elif away_score > home_score:
            real_outcome = away_team
        else:
            real_outcome = "Draw"

        # --- Проверка прогноза победителя (GPT/основной) ---
        is_correct = 0
        if recommended_outcome:
            rec = recommended_outcome.lower()
            if real_outcome == "Draw" and ("draw" in rec or "ничья" in rec):
                is_correct = 1
            elif real_outcome == home_team and home_team.lower() in rec:
                is_correct = 1
            elif real_outcome == away_team and away_team.lower() in rec:
                is_correct = 1

        # --- Проверка тотала ---
        total_goals = home_score + away_score
        is_goals_correct = None
        if total_goals_pred:
            pred_lower = total_goals_pred.lower()
            if "больше 2.5" in pred_lower or "over 2.5" in pred_lower:
                is_goals_correct = 1 if total_goals > 2 else 0
            elif "меньше 2.5" in pred_lower or "under 2.5" in pred_lower:
                is_goals_correct = 1 if total_goals <= 2 else 0

        # --- Проверка обе забьют ---
        is_btts_correct = None
        if btts_pred:
            both_scored = home_score > 0 and away_score > 0
            if "да" in btts_pred.lower() or "yes" in btts_pred.lower():
                is_btts_correct = 1 if both_scored else 0
            elif "нет" in btts_pred.lower() or "no" in btts_pred.lower():
                is_btts_correct = 1 if not both_scored else 0

        # --- Проверка ансамбля ---
        is_ensemble_correct = None
        if ensemble_best:
            eb = ensemble_best.lower()
            if real_outcome == "Draw" and ("ничья" in eb or "draw" in eb):
                is_ensemble_correct = 1
            elif real_outcome == home_team and home_team.lower() in eb:
                is_ensemble_correct = 1
            elif real_outcome == away_team and away_team.lower() in eb:
                is_ensemble_correct = 1
            else:
                is_ensemble_correct = 0

        # --- ROI по основной ставке ---
        roi_outcome = None
        if bet_signal == "СТАВИТЬ" and recommended_outcome:
            rec = recommended_outcome.lower()
            if real_outcome == "Draw" and ("draw" in rec or "ничья" in rec):
                roi_outcome = (odds_draw or 1) - 1  # прибыль
            elif real_outcome == home_team and home_team.lower() in rec:
                roi_outcome = (odds_home or 1) - 1
            elif real_outcome == away_team and away_team.lower() in rec:
                roi_outcome = (odds_away or 1) - 1
            else:
                roi_outcome = -1.0  # проигрыш

        # --- ROI по value ставке ---
        roi_value_bet = None
        vb_correct = None
        if vb_outcome and vb_odds:
            # Определяем выиграла ли value ставка
            vb_lower = vb_outcome.lower()
            if real_outcome == "Draw" and vb_lower in ("х", "draw", "ничья"):
                vb_correct = 1
                roi_value_bet = vb_odds - 1
            elif real_outcome == home_team and ("п1" in vb_lower or home_team.lower() in vb_lower):
                vb_correct = 1
                roi_value_bet = vb_odds - 1
            elif real_outcome == away_team and ("п2" in vb_lower or away_team.lower() in vb_lower):
                vb_correct = 1
                roi_value_bet = vb_odds - 1
            else:
                vb_correct = 0
                roi_value_bet = -1.0

        cursor.execute("""
        UPDATE predictions SET
            real_home_score = ?, real_away_score = ?,
            real_outcome = ?, is_correct = ?,
            is_goals_correct = ?, is_btts_correct = ?,
            is_ensemble_correct = ?,
            value_bet_correct = ?,
            roi_outcome = ?, roi_value_bet = ?,
            result_checked_at = ?
        WHERE match_id = ?
        """, (
            home_score, away_score, real_outcome,
            is_correct, is_goals_correct, is_btts_correct,
            is_ensemble_correct, vb_correct,
            roi_outcome, roi_value_bet,
            datetime.now(timezone.utc).isoformat(),
            match_id
        ))
        conn.commit()

        return {
            "home_team": home_team, "away_team": away_team,
            "score": f"{home_score}:{away_score}",
            "real_outcome": real_outcome,
            "predicted": recommended_outcome,
            "is_correct": is_correct,
            "is_goals_correct": is_goals_correct,
            "is_btts_correct": is_btts_correct,
            "is_ensemble_correct": is_ensemble_correct,
            "vb_correct": vb_correct,
            "roi_outcome": roi_outcome,
            "roi_value_bet": roi_value_bet,
        }


def get_pending_predictions():
    """Возвращает прогнозы без результата, матч которых уже прошёл."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        rows = cursor.execute("""
        SELECT match_id, home_team, away_team, match_date, league
        FROM predictions
        WHERE is_correct IS NULL AND match_date < ?
        ORDER BY match_date DESC
        LIMIT 30
        """, (now,)).fetchall()
        return [
            {"match_id": r[0], "home_team": r[1], "away_team": r[2],
             "match_date": r[3], "league": r[4] or "soccer_epl"}
            for r in rows
        ]


def get_statistics():
    """Возвращает полную статистику по всем прогнозам."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        checked = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_correct IS NOT NULL").fetchone()[0]
        correct = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_correct = 1").fetchone()[0]

        goals_checked = cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE is_goals_correct IS NOT NULL AND total_goals_prediction != ''"
        ).fetchone()[0]
        goals_correct = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_goals_correct = 1").fetchone()[0]

        btts_checked = cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE is_btts_correct IS NOT NULL AND btts_prediction != ''"
        ).fetchone()[0]
        btts_correct = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_btts_correct = 1").fetchone()[0]

        # Ансамбль точность
        ens_checked = cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE is_ensemble_correct IS NOT NULL"
        ).fetchone()[0]
        ens_correct = cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE is_ensemble_correct = 1"
        ).fetchone()[0]

        # Value bets точность и ROI
        vb_checked = cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE value_bet_correct IS NOT NULL AND value_bet_outcome != ''"
        ).fetchone()[0]
        vb_correct_count = cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE value_bet_correct = 1"
        ).fetchone()[0]
        roi_vb_row = cursor.execute(
            "SELECT SUM(roi_value_bet) FROM predictions WHERE roi_value_bet IS NOT NULL"
        ).fetchone()[0]
        roi_main_row = cursor.execute(
            "SELECT SUM(roi_outcome) FROM predictions WHERE roi_outcome IS NOT NULL"
        ).fetchone()[0]

        # Последние результаты
        recent = cursor.execute("""
        SELECT home_team, away_team, real_home_score, real_away_score,
               recommended_outcome, is_correct, created_at,
               is_ensemble_correct, value_bet_outcome, value_bet_correct, value_bet_odds
        FROM predictions
        WHERE is_correct IS NOT NULL
        ORDER BY result_checked_at DESC
        LIMIT 10
        """).fetchall()

        # По месяцам
        monthly = cursor.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct,
               SUM(CASE WHEN is_ensemble_correct = 1 THEN 1 ELSE 0 END) as ens_correct,
               SUM(CASE WHEN value_bet_correct = 1 THEN 1 ELSE 0 END) as vb_correct,
               SUM(COALESCE(roi_value_bet, 0)) as roi_vb
        FROM predictions
        WHERE is_correct IS NOT NULL
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
        """).fetchall()

        winner_accuracy = (correct / checked * 100) if checked > 0 else 0
        goals_accuracy = (goals_correct / goals_checked * 100) if goals_checked > 0 else 0
        btts_accuracy = (btts_correct / btts_checked * 100) if btts_checked > 0 else 0
        ens_accuracy = (ens_correct / ens_checked * 100) if ens_checked > 0 else 0
        vb_accuracy = (vb_correct_count / vb_checked * 100) if vb_checked > 0 else 0

        return {
            "total": total,
            "checked": checked,
            "pending": total - checked,
            "correct": correct,
            "winner_accuracy": winner_accuracy,
            "goals_accuracy": goals_accuracy,
            "btts_accuracy": btts_accuracy,
            "goals_checked": goals_checked,
            "btts_checked": btts_checked,
            "ens_accuracy": ens_accuracy,
            "ens_checked": ens_checked,
            "vb_accuracy": vb_accuracy,
            "vb_checked": vb_checked,
            "roi_value_bets": round(roi_vb_row or 0, 2),
            "roi_main": round(roi_main_row or 0, 2),
            "recent": recent,
            "monthly": monthly,
        }


def get_recent_predictions(limit=5):
    """Возвращает последние прогнозы для отображения."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        rows = cursor.execute("""
        SELECT home_team, away_team, recommended_outcome, bet_signal,
               gpt_confidence, real_home_score, real_away_score, is_correct, created_at
        FROM predictions
        ORDER BY created_at DESC
        LIMIT ?
        """, (limit,)).fetchall()
        return rows


if __name__ == '__main__':
    init_db()
    stats = get_statistics()
    print("Текущая статистика:", stats)
