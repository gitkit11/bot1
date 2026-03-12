# -*- coding: utf-8 -*-
import sqlite3
import json
from datetime import datetime

DB_FILE = "chimera_predictions.db"

def init_db():
    """Инициализирует базу данных и создаёт таблицы, если их нет."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Таблица для хранения прогнозов
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            prediction_data TEXT, -- JSON с полным прогнозом
            real_outcome TEXT, -- Реальный исход (заполняется после матча)
            is_correct INTEGER, -- 1 если прогноз верный, 0 если нет
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        print("[База данных] База данных инициализирована.")

def save_prediction(match_id, match_date, home_team, away_team, prediction_data):
    """Сохраняет прогноз в базу данных."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO predictions (match_id, match_date, home_team, away_team, prediction_data)
        VALUES (?, ?, ?, ?, ?)
        """, (match_id, match_date, home_team, away_team, json.dumps(prediction_data, ensure_ascii=False)))
        conn.commit()
        print(f"[База данных] Прогноз для матча {home_team} vs {away_team} сохранён.")

def get_statistics():
    """Возвращает статистику по всем прогнозам."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        total_predictions = cursor.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        correct_predictions = cursor.execute("SELECT COUNT(*) FROM predictions WHERE is_correct = 1").fetchone()[0]
        
        if total_predictions == 0:
            accuracy = 0
        else:
            accuracy = (correct_predictions / total_predictions) * 100
        
        return {
            "total_predictions": total_predictions,
            "correct_predictions": correct_predictions,
            "accuracy_percent": accuracy
        }

if __name__ == '__main__':
    init_db()
    stats = get_statistics()
    print("Текущая статистика:", stats)
