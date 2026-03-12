# -*- coding: utf-8 -*-
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
            -- Прогнозы
            gpt_verdict TEXT,
            llama_verdict TEXT,
            gpt_confidence INTEGER,
            llama_confidence INTEGER,
            bet_signal TEXT,
            recommended_outcome TEXT,
            total_goals_prediction TEXT,
            btts_prediction TEXT,
            bookmaker_odds_home REAL,
            bookmaker_odds_draw REAL,
            bookmaker_odds_away REAL,
            bookmaker_odds_over25 REAL,
            bookmaker_odds_under25 REAL,
            -- Результат
            real_home_score INTEGER,
            real_away_score INTEGER,
            real_outcome TEXT,
            is_correct INTEGER,
            is_goals_correct INTEGER,
            is_btts_correct INTEGER,
            result_checked_at TIMESTAMP,
            -- Мета
            prediction_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        print("[База данных] База данных инициализирована.")

def save_prediction(match_id, match_date, home_team, away_team, prediction_data):
    """Сохраняет прогноз в базу данных."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Определяем рекомендуемый исход (согласие моделей)
        gpt_v = prediction_data.get("gpt_verdict", "")
        llama_v = prediction_data.get("llama_verdict", prediction_data.get("gemini_verdict", ""))
        recommended = gpt_v if gpt_v else llama_v

        cursor.execute("""
        INSERT OR REPLACE INTO predictions (
            match_id, match_date, home_team, away_team,
            gpt_verdict, llama_verdict, gpt_confidence, llama_confidence,
            bet_signal, recommended_outcome,
            total_goals_prediction, btts_prediction,
            bookmaker_odds_home, bookmaker_odds_draw, bookmaker_odds_away,
            bookmaker_odds_over25, bookmaker_odds_under25,
            prediction_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id, match_date, home_team, away_team,
            gpt_v, llama_v,
            prediction_data.get("gpt_confidence", 0),
            prediction_data.get("llama_confidence", prediction_data.get("gemini_confidence", 0)),
            prediction_data.get("bet_signal", ""),
            recommended,
            prediction_data.get("total_goals", ""),
            prediction_data.get("btts", ""),
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
    """Обновляет реальный результат матча и проверяет прогноз."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Получаем прогноз
        row = cursor.execute(
            "SELECT home_team, away_team, recommended_outcome, total_goals_prediction, btts_prediction FROM predictions WHERE match_id = ?",
            (match_id,)
        ).fetchone()

        if not row:
            return False

        home_team, away_team, recommended_outcome, total_goals_pred, btts_pred = row

        # Определяем реальный исход
        if home_score > away_score:
            real_outcome = home_team
        elif away_score > home_score:
            real_outcome = away_team
        else:
            real_outcome = "Draw"

        # Проверяем прогноз победителя
        is_correct = 0
        if recommended_outcome:
            rec = recommended_outcome.lower()
            if real_outcome == "Draw" and ("draw" in rec or "ничья" in rec or "х" == rec):
                is_correct = 1
            elif real_outcome == home_team and home_team.lower() in rec:
                is_correct = 1
            elif real_outcome == away_team and away_team.lower() in rec:
                is_correct = 1

        # Проверяем прогноз тотала голов
        total_goals = home_score + away_score
        is_goals_correct = 0
        if total_goals_pred:
            pred_lower = total_goals_pred.lower()
            if "больше 2.5" in pred_lower or "over 2.5" in pred_lower:
                is_goals_correct = 1 if total_goals > 2 else 0
            elif "меньше 2.5" in pred_lower or "under 2.5" in pred_lower:
                is_goals_correct = 1 if total_goals <= 2 else 0

        # Проверяем обе забьют
        is_btts_correct = 0
        if btts_pred:
            both_scored = home_score > 0 and away_score > 0
            if "да" in btts_pred.lower() or "yes" in btts_pred.lower():
                is_btts_correct = 1 if both_scored else 0
            elif "нет" in btts_pred.lower() or "no" in btts_pred.lower():
                is_btts_correct = 1 if not both_scored else 0

        cursor.execute("""
        UPDATE predictions SET
            real_home_score = ?, real_away_score = ?,
            real_outcome = ?, is_correct = ?,
            is_goals_correct = ?, is_btts_correct = ?,
            result_checked_at = ?
        WHERE match_id = ?
        """, (
            home_score, away_score, real_outcome,
            is_correct, is_goals_correct, is_btts_correct,
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
            "is_btts_correct": is_btts_correct
        }

def get_pending_predictions():
    """Возвращает прогнозы без результата, матч которых уже прошёл."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        rows = cursor.execute("""
        SELECT match_id, home_team, away_team, match_date
        FROM predictions
        WHERE is_correct IS NULL AND match_date < ?
        ORDER BY match_date DESC
        LIMIT 20
        """, (now,)).fetchall()
        return [{"match_id": r[0], "home_team": r[1], "away_team": r[2], "match_date": r[3]} for r in rows]

def get_statistics():
    """Возвращает полную статистику по всем прогнозам."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        checked = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_correct IS NOT NULL").fetchone()[0]
        correct = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_correct = 1").fetchone()[0]
        goals_correct = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_goals_correct = 1").fetchone()[0]
        goals_checked = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_goals_correct IS NOT NULL AND total_goals_prediction != ''").fetchone()[0]
        btts_correct = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_btts_correct = 1").fetchone()[0]
        btts_checked = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_btts_correct IS NOT NULL AND btts_prediction != ''").fetchone()[0]

        # Последние 10 результатов
        recent = cursor.execute("""
        SELECT home_team, away_team, real_home_score, real_away_score,
               recommended_outcome, is_correct, created_at
        FROM predictions
        WHERE is_correct IS NOT NULL
        ORDER BY result_checked_at DESC
        LIMIT 10
        """).fetchall()

        # Статистика по месяцам
        monthly = cursor.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM predictions
        WHERE is_correct IS NOT NULL
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
        """).fetchall()

        winner_accuracy = (correct / checked * 100) if checked > 0 else 0
        goals_accuracy = (goals_correct / goals_checked * 100) if goals_checked > 0 else 0
        btts_accuracy = (btts_correct / btts_checked * 100) if btts_checked > 0 else 0

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
            "recent": recent,
            "monthly": monthly
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
