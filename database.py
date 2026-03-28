import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

DB_FILE = "chimera_predictions.db"

_VALID_SPORTS = {"football", "cs2", "tennis", "basketball", "hockey"}

def _validate_sport(sport: str) -> str:
    if sport not in _VALID_SPORTS:
        raise ValueError(f"Invalid sport: {sport!r}")
    return sport

def _get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _migrate_old_predictions():
    """Мигрирует данные из старой таблицы 'predictions' в новые 'football_predictions' и 'cs2_predictions'."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()

        # Проверяем, существует ли старая таблица predictions
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='predictions';")
        if not cursor.fetchone():
            print("[database] Old 'predictions' table not found, migration not needed.")
            return

        print("[database] Migrating data from old 'predictions' table...")

        # Извлекаем все данные из старой таблицы
        old_predictions = cursor.execute("SELECT * FROM predictions;").fetchall()
        old_columns = [description[0] for description in cursor.description]

        for row in old_predictions:
            old_data = dict(zip(old_columns, row))
            league = old_data.get('league', 'soccer_epl')
            sport = 'cs2' if 'cs2' in league.lower() or 'esports' in league.lower() else 'football'

            prediction_data = json.loads(old_data.get('prediction_data', '{}'))

            # Определяем result_checked_at для миграции
            migrated_result_checked_at = old_data.get('result_checked_at', old_data.get('created_at'))

            if sport == 'football':
                # Подготовка данных для football_predictions
                football_data = {
                    'match_id': old_data['match_id'],
                    'match_date': old_data['match_date'],
                    'home_team': old_data['home_team'],
                    'away_team': old_data['away_team'],
                    'league': league,
                    'gpt_verdict': old_data.get('gpt_verdict'),
                    'llama_verdict': old_data.get('llama_verdict'),
                    'mixtral_verdict': old_data.get('mixtral_verdict'),
                    'gpt_confidence': old_data.get('gpt_confidence'),
                    'llama_confidence': old_data.get('llama_confidence'),
                    'mixtral_confidence': old_data.get('mixtral_confidence'),
                    'bet_signal': old_data.get('bet_signal'),
                    'recommended_outcome': old_data.get('recommended_outcome'),
                    'total_goals_prediction': old_data.get('total_goals_prediction'),
                    'btts_prediction': old_data.get('btts_prediction'),
                    'poisson_home_win': old_data.get('poisson_home_win'),
                    'poisson_draw': old_data.get('poisson_draw'),
                    'poisson_away_win': old_data.get('poisson_away_win'),
                    'poisson_over25': old_data.get('poisson_over25'),
                    'poisson_btts': old_data.get('poisson_btts'),
                    'poisson_data_source': old_data.get('poisson_data_source'),
                    'elo_home': old_data.get('elo_home'),
                    'elo_away': old_data.get('elo_away'),
                    'elo_home_win': old_data.get('elo_home_win'),
                    'elo_draw': old_data.get('elo_draw'),
                    'elo_away_win': old_data.get('elo_away_win'),
                    'ensemble_home': old_data.get('ensemble_home'),
                    'ensemble_draw': old_data.get('ensemble_draw'),
                    'ensemble_away': old_data.get('ensemble_away'),
                    'ensemble_best_outcome': old_data.get('ensemble_best_outcome'),
                    'value_bet_outcome': old_data.get('value_bet_outcome'),
                    'value_bet_odds': old_data.get('value_bet_odds'),
                    'value_bet_ev': old_data.get('value_bet_ev'),
                    'value_bet_kelly': old_data.get('value_bet_kelly'),
                    'value_bet_correct': old_data.get('value_bet_correct'),
                    'bookmaker_odds_home': old_data.get('bookmaker_odds_home'),
                    'bookmaker_odds_draw': old_data.get('bookmaker_odds_draw'),
                    'bookmaker_odds_away': old_data.get('bookmaker_odds_away'),
                    'bookmaker_odds_over25': old_data.get('bookmaker_odds_over25'),
                    'bookmaker_odds_under25': old_data.get('bookmaker_odds_under25'),
                    'real_home_score': old_data.get('real_home_score'),
                    'real_away_score': old_data.get('real_away_score'),
                    'real_outcome': old_data.get('real_outcome'),
                    'is_correct': old_data.get('is_correct'),
                    'is_goals_correct': old_data.get('is_goals_correct'),
                    'is_btts_correct': old_data.get('is_btts_correct'),
                    'is_ensemble_correct': old_data.get('is_ensemble_correct'),
                    'roi_outcome': old_data.get('roi_outcome'),
                    'roi_value_bet': old_data.get('roi_value_bet'),
                    'model_weights_at_prediction': prediction_data.get('model_weights_at_prediction', '{}'),
                    'prediction_data': json.dumps(prediction_data, ensure_ascii=False),
                    'created_at': old_data.get('created_at'),
                    'result_checked_at': migrated_result_checked_at, # Добавлено
                }
                columns = ', '.join(football_data.keys())
                placeholders = ', '.join(['?' for _ in football_data.keys()])
                cursor.execute(f"INSERT OR REPLACE INTO football_predictions ({columns}) VALUES ({placeholders})", list(football_data.values()))
            elif sport == 'cs2':
                # Подготовка данных для cs2_predictions
                cs2_data = {
                    'match_id': old_data['match_id'],
                    'match_date': old_data['match_date'],
                    'home_team': old_data['home_team'],
                    'away_team': old_data['away_team'],
                    'league': league,
                    'gpt_verdict': old_data.get('gpt_verdict'),
                    'llama_verdict': old_data.get('llama_verdict'),
                    'mixtral_verdict': old_data.get('mixtral_verdict'),
                    'gpt_confidence': old_data.get('gpt_confidence'),
                    'llama_confidence': old_data.get('llama_confidence'),
                    'mixtral_confidence': old_data.get('mixtral_confidence'),
                    'bet_signal': old_data.get('bet_signal'),
                    'recommended_outcome': old_data.get('recommended_outcome'),
                    'elo_home': old_data.get('elo_home'),
                    'elo_away': old_data.get('elo_away'),
                    'elo_home_win': old_data.get('elo_home_win'),
                    'elo_away_win': old_data.get('elo_away_win'),
                    'ensemble_home': old_data.get('ensemble_home'),
                    'ensemble_away': old_data.get('ensemble_away'),
                    'ensemble_best_outcome': old_data.get('ensemble_best_outcome'),
                    'value_bet_outcome': old_data.get('value_bet_outcome'),
                    'value_bet_odds': old_data.get('value_bet_odds'),
                    'value_bet_ev': old_data.get('value_bet_ev'),
                    'value_bet_kelly': old_data.get('value_bet_kelly'),
                    'value_bet_correct': old_data.get('value_bet_correct'),
                    'bookmaker_odds_home': old_data.get('bookmaker_odds_home'),
                    'bookmaker_odds_away': old_data.get('bookmaker_odds_away'),
                    'predicted_maps': prediction_data.get('predicted_maps', '[]'),
                    'map_advantage_score': prediction_data.get('map_advantage_score'),
                    'key_player_advantage': prediction_data.get('key_player_advantage'),
                    'ai_signal_reason': prediction_data.get('ai_signal_reason'),
                    'home_map_winrates': prediction_data.get('home_map_winrates', '{}'),
                    'away_map_winrates': prediction_data.get('away_map_winrates', '{}'),
                    'home_player_ratings': prediction_data.get('home_player_ratings', '[]'),
                    'away_player_ratings': prediction_data.get('away_player_ratings', '[]'),
                    'real_home_score': old_data.get('real_home_score'),
                    'real_away_score': old_data.get('real_away_score'),
                    'real_outcome': old_data.get('real_outcome'),
                    'is_correct': old_data.get('is_correct'),
                    'is_ensemble_correct': old_data.get('is_ensemble_correct'),
                    'roi_outcome': old_data.get('roi_outcome'),
                    'roi_value_bet': old_data.get('roi_value_bet'),
                    'model_weights_at_prediction': prediction_data.get('model_weights_at_prediction', '{}'),
                    'prediction_data': json.dumps(prediction_data, ensure_ascii=False),
                    'created_at': old_data.get('created_at'),
                    'result_checked_at': migrated_result_checked_at, # Добавлено
                }
                columns = ', '.join(cs2_data.keys())
                placeholders = ', '.join(['?' for _ in cs2_data.keys()])
                cursor.execute(f"INSERT OR REPLACE INTO cs2_predictions ({columns}) VALUES ({placeholders})", list(cs2_data.values()))

        # Удаляем старую таблицу после успешной миграции
        cursor.execute("DROP TABLE predictions;")
        conn.commit()
        print("[database] Migration complete. Old 'predictions' table dropped.")

def init_db():
    """Инициализирует базу данных и создаёт таблицы."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()

        # Создание таблицы football_predictions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS football_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
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
            ensemble_home REAL,
            ensemble_draw REAL,
            ensemble_away REAL,
            ensemble_best_outcome TEXT,
            value_bet_outcome TEXT,
            value_bet_odds REAL,
            value_bet_ev REAL,
            value_bet_kelly REAL,
            value_bet_correct INTEGER,
            bookmaker_odds_home REAL,
            bookmaker_odds_draw REAL,
            bookmaker_odds_away REAL,
            bookmaker_odds_over25 REAL,
            bookmaker_odds_under25 REAL,
            real_home_score INTEGER,
            real_away_score INTEGER,
            real_outcome TEXT,
            is_correct INTEGER,
            is_goals_correct INTEGER,
            is_btts_correct INTEGER,
            is_ensemble_correct INTEGER,
            roi_outcome REAL,
            roi_value_bet REAL,
            model_weights_at_prediction TEXT,
            prediction_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            result_checked_at TIMESTAMP -- Добавлено
        );
        """)

        # Создание таблицы cs2_predictions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cs2_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            gpt_verdict TEXT,
            llama_verdict TEXT,
            mixtral_verdict TEXT,
            gpt_confidence INTEGER,
            llama_confidence INTEGER,
            mixtral_confidence INTEGER,
            bet_signal TEXT,
            recommended_outcome TEXT,
            elo_home INTEGER,
            elo_away INTEGER,
            elo_home_win REAL,
            elo_away_win REAL,
            ensemble_home REAL,
            ensemble_away REAL,
            ensemble_best_outcome TEXT,
            value_bet_outcome TEXT,
            value_bet_odds REAL,
            value_bet_ev REAL,
            value_bet_kelly REAL,
            value_bet_correct INTEGER,
            bookmaker_odds_home REAL,
            bookmaker_odds_away REAL,
            predicted_maps TEXT, -- JSON строка
            map_advantage_score REAL,
            key_player_advantage REAL,
            ai_signal_reason TEXT,
            home_map_winrates TEXT, -- JSON строка
            away_map_winrates TEXT, -- JSON строка
            home_player_ratings TEXT, -- JSON строка
            away_player_ratings TEXT, -- JSON строка
            real_home_score INTEGER,
            real_away_score INTEGER,
            real_outcome TEXT,
            is_correct INTEGER,
            is_ensemble_correct INTEGER,
            roi_outcome REAL,
            roi_value_bet REAL,
            model_weights_at_prediction TEXT,
            prediction_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            result_checked_at TIMESTAMP -- Добавлено
        );
        """)
        # Добавляем новые колонки CS2 если ещё нет (миграция без пересоздания)
        existing = [r[1] for r in cursor.execute("PRAGMA table_info(cs2_predictions)").fetchall()]
        new_cols = {
            "total_prediction":  "TEXT",
            "total_odds":        "REAL",
            "top_bet_type":      "TEXT",
            "top_bet_odds":      "REAL",
            "top_bet_ev":        "REAL",
            "is_total_correct":  "INTEGER",
            "actual_total":      "TEXT",
        }
        for col, col_type in new_cols.items():
            if col not in existing:
                cursor.execute(f"ALTER TABLE cs2_predictions ADD COLUMN {col} {col_type}")

        # Создание таблицы tennis_predictions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tennis_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            recommended_outcome TEXT,
            bet_signal TEXT,
            ensemble_home REAL,
            ensemble_away REAL,
            ensemble_best_outcome TEXT,
            bookmaker_odds_home REAL,
            bookmaker_odds_away REAL,
            real_outcome TEXT,
            is_correct INTEGER,
            roi_outcome REAL,
            value_bet_correct INTEGER,
            roi_value_bet REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            result_checked_at TIMESTAMP
        );
        """)
        # Миграция: добавляем недостающие колонки
        _t_cols = [r[1] for r in cursor.execute("PRAGMA table_info(tennis_predictions)").fetchall()]
        if "bet_signal" not in _t_cols:
            cursor.execute("ALTER TABLE tennis_predictions ADD COLUMN bet_signal TEXT")
        if "gpt_verdict" not in _t_cols:
            cursor.execute("ALTER TABLE tennis_predictions ADD COLUMN gpt_verdict TEXT")
        if "llama_verdict" not in _t_cols:
            cursor.execute("ALTER TABLE tennis_predictions ADD COLUMN llama_verdict TEXT")

        # Создание таблицы basketball_predictions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS basketball_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            gpt_verdict TEXT,
            llama_verdict TEXT,
            bet_signal TEXT,
            recommended_outcome TEXT,
            elo_home INTEGER,
            elo_away INTEGER,
            elo_home_win REAL,
            elo_away_win REAL,
            ensemble_home REAL,
            ensemble_away REAL,
            ensemble_best_outcome TEXT,
            bookmaker_odds_home REAL,
            bookmaker_odds_away REAL,
            total_line REAL,
            total_lean TEXT,
            total_lean_odds REAL,
            total_ev REAL,
            spread_home REAL,
            spread_away REAL,
            real_outcome TEXT,
            is_correct INTEGER,
            roi_outcome REAL,
            value_bet_correct INTEGER,
            roi_value_bet REAL,
            prediction_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            result_checked_at TIMESTAMP
        );
        """)
        # Миграция: добавляем value_bet колонки если их нет
        _bb_cols = [r[1] for r in cursor.execute("PRAGMA table_info(basketball_predictions)").fetchall()]
        if "value_bet_correct" not in _bb_cols:
            cursor.execute("ALTER TABLE basketball_predictions ADD COLUMN value_bet_correct INTEGER")
        if "roi_value_bet" not in _bb_cols:
            cursor.execute("ALTER TABLE basketball_predictions ADD COLUMN roi_value_bet REAL")

        # Создание таблицы hockey_predictions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS hockey_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            gpt_verdict TEXT,
            llama_verdict TEXT,
            bet_signal TEXT,
            recommended_outcome TEXT,
            elo_home INTEGER,
            elo_away INTEGER,
            ensemble_home REAL,
            ensemble_away REAL,
            ensemble_best_outcome TEXT,
            bookmaker_odds_home REAL,
            bookmaker_odds_away REAL,
            total_line REAL,
            total_lean TEXT,
            real_outcome TEXT,
            is_correct INTEGER,
            roi_outcome REAL,
            value_bet_correct INTEGER,
            roi_value_bet REAL,
            prediction_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            result_checked_at TIMESTAMP
        );
        """)

        # Таблица пользователей (личный кабинет)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            first_seen  TEXT,
            last_active TEXT,
            analyses_football    INTEGER DEFAULT 0,
            analyses_cs2         INTEGER DEFAULT 0,
            analyses_tennis      INTEGER DEFAULT 0,
            analyses_basketball  INTEGER DEFAULT 0,
            analyses_total       INTEGER DEFAULT 0
        );
        """)
        # Миграция: добавляем недостающие колонки
        _u_cols = [r[1] for r in cursor.execute("PRAGMA table_info(users)").fetchall()]
        if "analyses_basketball" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN analyses_basketball INTEGER DEFAULT 0")
        if "analyses_hockey" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN analyses_hockey INTEGER DEFAULT 0")
        if "language" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
        if "bankroll" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN bankroll REAL DEFAULT NULL")
        if "subscription_until" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN subscription_until TEXT DEFAULT NULL")
        if "subscription_type" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN subscription_type TEXT DEFAULT 'free'")
        if "trial_used" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
        if "weekly_analyses_used" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN weekly_analyses_used INTEGER DEFAULT 0")
        if "weekly_reset_date" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN weekly_reset_date TEXT DEFAULT NULL")
        if "daily_analyses_used" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN daily_analyses_used INTEGER DEFAULT 0")
        if "daily_reset_date" not in _u_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN daily_reset_date TEXT DEFAULT NULL")

        # Таблица личных ставок пользователя
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sport TEXT NOT NULL,
            prediction_id INTEGER NOT NULL,
            odds REAL,
            units INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)
        # Миграция user_bets
        _ub_cols = [r[1] for r in cursor.execute("PRAGMA table_info(user_bets)").fetchall()]
        if "units" not in _ub_cols:
            cursor.execute("ALTER TABLE user_bets ADD COLUMN units INTEGER DEFAULT 1")
        if "notified" not in _ub_cols:
            cursor.execute("ALTER TABLE user_bets ADD COLUMN notified INTEGER DEFAULT 0")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_bets_user ON user_bets(user_id)")

        # Таблица действий пользователей
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_actions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            action     TEXT NOT NULL,
            ts         TEXT NOT NULL
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_user ON user_actions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_ts   ON user_actions(ts)")

        # Миграция tennis bet_signal
        _t_cols = [r[1] for r in cursor.execute("PRAGMA table_info(tennis_predictions)").fetchall()]
        if "bet_signal" not in _t_cols:
            cursor.execute("ALTER TABLE tennis_predictions ADD COLUMN bet_signal TEXT")

        conn.commit()
        print("[database] Tables initialized.")

    _migrate_old_predictions()

def save_prediction(
    sport: str,
    match_id: str,
    match_date: str,
    home_team: str,
    away_team: str,
    league: str,
    gpt_verdict: Optional[str] = None,
    llama_verdict: Optional[str] = None,
    mixtral_verdict: Optional[str] = None,
    gpt_confidence: Optional[int] = None,
    llama_confidence: Optional[int] = None,
    mixtral_confidence: Optional[int] = None,
    bet_signal: Optional[str] = None,
    recommended_outcome: Optional[str] = None,
    total_goals_prediction: Optional[str] = None,
    btts_prediction: Optional[str] = None,
    poisson_home_win: Optional[float] = None,
    poisson_draw: Optional[float] = None,
    poisson_away_win: Optional[float] = None,
    poisson_over25: Optional[float] = None,
    poisson_btts: Optional[float] = None,
    poisson_data_source: Optional[str] = None,
    elo_home: Optional[int] = None,
    elo_away: Optional[int] = None,
    elo_home_win: Optional[float] = None,
    elo_draw: Optional[float] = None,
    elo_away_win: Optional[float] = None,
    ensemble_home: Optional[float] = None,
    ensemble_draw: Optional[float] = None,
    ensemble_away: Optional[float] = None,
    ensemble_best_outcome: Optional[str] = None,
    value_bet_outcome: Optional[str] = None,
    value_bet_odds: Optional[float] = None,
    value_bet_ev: Optional[float] = None,
    value_bet_kelly: Optional[float] = None,
    value_bet_correct: Optional[int] = None,
    bookmaker_odds_home: Optional[float] = None,
    bookmaker_odds_draw: Optional[float] = None,
    bookmaker_odds_away: Optional[float] = None,
    bookmaker_odds_over25: Optional[float] = None,
    bookmaker_odds_under25: Optional[float] = None,
    # CS2 Specific
    predicted_maps: Optional[List[str]] = None,
    map_advantage_score: Optional[float] = None,
    key_player_advantage: Optional[float] = None,
    ai_signal_reason: Optional[str] = None,
    home_map_winrates: Optional[Dict[str, float]] = None,
    away_map_winrates: Optional[Dict[str, float]] = None,
    home_player_ratings: Optional[List[float]] = None,
    away_player_ratings: Optional[List[float]] = None,
    model_weights_at_prediction: Optional[Dict] = None,
    prediction_data: Optional[Dict] = None,
    # Basketball specific
    total_line: Optional[float] = None,
    total_lean: Optional[str] = None,
    total_lean_odds: Optional[float] = None,
    total_ev: Optional[float] = None,
    spread_home: Optional[float] = None,
    spread_away: Optional[float] = None,
):
    """Сохраняет прогноз в соответствующую таблицу базы данных."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        current_time = datetime.now(timezone.utc).isoformat()

        if sport == 'football':
            table_name = 'football_predictions'
            data = {
                'match_id': match_id,
                'match_date': match_date,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'gpt_verdict': gpt_verdict,
                'llama_verdict': llama_verdict,
                'mixtral_verdict': mixtral_verdict,
                'gpt_confidence': gpt_confidence,
                'llama_confidence': llama_confidence,
                'mixtral_confidence': mixtral_confidence,
                'bet_signal': bet_signal,
                'recommended_outcome': recommended_outcome,
                'total_goals_prediction': total_goals_prediction,
                'btts_prediction': btts_prediction,
                'poisson_home_win': poisson_home_win,
                'poisson_draw': poisson_draw,
                'poisson_away_win': poisson_away_win,
                'poisson_over25': poisson_over25,
                'poisson_btts': poisson_btts,
                'poisson_data_source': poisson_data_source,
                'elo_home': elo_home,
                'elo_away': elo_away,
                'elo_home_win': elo_home_win,
                'elo_draw': elo_draw,
                'elo_away_win': elo_away_win,
                'ensemble_home': ensemble_home,
                'ensemble_draw': ensemble_draw,
                'ensemble_away': ensemble_away,
                'ensemble_best_outcome': ensemble_best_outcome,
                'value_bet_outcome': value_bet_outcome,
                'value_bet_odds': value_bet_odds,
                'value_bet_ev': value_bet_ev,
                'value_bet_kelly': value_bet_kelly,
                'value_bet_correct': value_bet_correct,
                'bookmaker_odds_home': bookmaker_odds_home,
                'bookmaker_odds_draw': bookmaker_odds_draw,
                'bookmaker_odds_away': bookmaker_odds_away,
                'bookmaker_odds_over25': bookmaker_odds_over25,
                'bookmaker_odds_under25': bookmaker_odds_under25,
                'model_weights_at_prediction': json.dumps(model_weights_at_prediction) if model_weights_at_prediction else '{}',
                'prediction_data': json.dumps(prediction_data) if prediction_data else '{}',
                'created_at': current_time,
                'result_checked_at': None, # Изначально null
            }
        elif sport == 'cs2':
            table_name = 'cs2_predictions'
            data = {
                'match_id': match_id,
                'match_date': match_date,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'gpt_verdict': gpt_verdict,
                'llama_verdict': llama_verdict,
                'mixtral_verdict': mixtral_verdict,
                'gpt_confidence': gpt_confidence,
                'llama_confidence': llama_confidence,
                'mixtral_confidence': mixtral_confidence,
                'bet_signal': bet_signal,
                'recommended_outcome': recommended_outcome,
                'elo_home': elo_home,
                'elo_away': elo_away,
                'elo_home_win': elo_home_win,
                'elo_away_win': elo_away_win,
                'ensemble_home': ensemble_home,
                'ensemble_away': ensemble_away,
                'ensemble_best_outcome': ensemble_best_outcome,
                'value_bet_outcome': value_bet_outcome,
                'value_bet_odds': value_bet_odds,
                'value_bet_ev': value_bet_ev,
                'value_bet_kelly': value_bet_kelly,
                'value_bet_correct': value_bet_correct,
                'bookmaker_odds_home': bookmaker_odds_home,
                'bookmaker_odds_away': bookmaker_odds_away,
                'predicted_maps': json.dumps(predicted_maps) if predicted_maps else '[]',
                'map_advantage_score': map_advantage_score,
                'key_player_advantage': key_player_advantage,
                'ai_signal_reason': ai_signal_reason,
                'home_map_winrates': json.dumps(home_map_winrates) if home_map_winrates else '{}',
                'away_map_winrates': json.dumps(away_map_winrates) if away_map_winrates else '{}',
                'home_player_ratings': json.dumps(home_player_ratings) if home_player_ratings else '[]',
                'away_player_ratings': json.dumps(away_player_ratings) if away_player_ratings else '[]',
                'model_weights_at_prediction': json.dumps(model_weights_at_prediction) if model_weights_at_prediction else '{}',
                'prediction_data': json.dumps(prediction_data) if prediction_data else '{}',
                'created_at': current_time,
                'result_checked_at': None, # Изначально null
            }
        elif sport == 'tennis':
            table_name = 'tennis_predictions'
            data = {
                'match_id': match_id,
                'match_date': match_date,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'gpt_verdict': gpt_verdict,
                'llama_verdict': llama_verdict,
                'bet_signal': bet_signal,
                'recommended_outcome': recommended_outcome,
                'ensemble_home': ensemble_home,
                'ensemble_away': ensemble_away,
                'ensemble_best_outcome': ensemble_best_outcome,
                'bookmaker_odds_home': bookmaker_odds_home,
                'bookmaker_odds_away': bookmaker_odds_away,
                'created_at': current_time,
                'result_checked_at': None,
            }
        elif sport == 'basketball':
            table_name = 'basketball_predictions'
            data = {
                'match_id': match_id,
                'match_date': match_date,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'gpt_verdict': gpt_verdict,
                'llama_verdict': llama_verdict,
                'bet_signal': bet_signal,
                'recommended_outcome': recommended_outcome,
                'elo_home': elo_home,
                'elo_away': elo_away,
                'elo_home_win': elo_home_win,
                'elo_away_win': elo_away_win,
                'ensemble_home': ensemble_home,
                'ensemble_away': ensemble_away,
                'ensemble_best_outcome': ensemble_best_outcome,
                'bookmaker_odds_home': bookmaker_odds_home,
                'bookmaker_odds_away': bookmaker_odds_away,
                'total_line': total_line,
                'total_lean': total_lean,
                'total_lean_odds': total_lean_odds,
                'total_ev': total_ev,
                'spread_home': spread_home,
                'spread_away': spread_away,
                'prediction_data': json.dumps(prediction_data) if prediction_data else '{}',
                'created_at': current_time,
                'result_checked_at': None,
            }
        elif sport == 'hockey':
            table_name = 'hockey_predictions'
            data = {
                'match_id': match_id,
                'match_date': match_date,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'gpt_verdict': gpt_verdict,
                'llama_verdict': llama_verdict,
                'bet_signal': bet_signal,
                'recommended_outcome': recommended_outcome,
                'elo_home': elo_home,
                'elo_away': elo_away,
                'ensemble_home': ensemble_home,
                'ensemble_away': ensemble_away,
                'ensemble_best_outcome': ensemble_best_outcome,
                'bookmaker_odds_home': bookmaker_odds_home,
                'bookmaker_odds_away': bookmaker_odds_away,
                'total_line': total_line,
                'total_lean': total_lean,
                'prediction_data': json.dumps(prediction_data) if prediction_data else '{}',
                'created_at': current_time,
                'result_checked_at': None,
            }
        else:
            raise ValueError(f"Неизвестный вид спорта: {sport}")

        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data.keys()])
        cursor.execute(
            f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})",
            list(data.values())
        )
        conn.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        # Match already exists (UNIQUE on match_id) — return existing rowid
        existing = cursor.execute(
            f"SELECT rowid FROM {table_name} WHERE match_id = ?", (match_id,)
        ).fetchone()
        return existing[0] if existing else None

def update_result(
    sport: str,
    match_id: str,
    real_home_score: Optional[int],
    real_away_score: Optional[int],
    real_outcome: str,
    is_correct: Optional[int] = None,
    is_ensemble_correct: Optional[int] = None,
    is_goals_correct: Optional[int] = None,
    is_btts_correct: Optional[int] = None,
    roi_outcome: Optional[float] = None,
    roi_value_bet: Optional[float] = None,
    value_bet_correct: Optional[int] = None,
):
    """Обновляет результаты прогноза в соответствующей таблице."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        table_name = f"{_validate_sport(sport)}_predictions"
        current_time = datetime.now(timezone.utc).isoformat()

        # Получаем реальные колонки таблицы
        cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]

        # Строим UPDATE динамически — только существующие колонки
        # Используем append чтобы сохранить порядок set_parts == values
        set_parts = ["real_outcome = ?", "result_checked_at = ?"]
        values    = [real_outcome, current_time]

        if "real_home_score" in cols:
            set_parts.append("real_home_score = ?")
            values.append(real_home_score)
        if "real_away_score" in cols:
            set_parts.append("real_away_score = ?")
            values.append(real_away_score)
        # is_correct может быть None (нет рекомендации — не считать)
        if "is_correct" in cols:
            set_parts.append("is_correct = ?")
            values.append(is_correct)
        if "is_ensemble_correct" in cols and is_ensemble_correct is not None:
            set_parts.append("is_ensemble_correct = ?")
            values.append(is_ensemble_correct)
        if "is_goals_correct" in cols and is_goals_correct is not None:
            set_parts.append("is_goals_correct = ?")
            values.append(is_goals_correct)
        if "is_btts_correct" in cols and is_btts_correct is not None:
            set_parts.append("is_btts_correct = ?")
            values.append(is_btts_correct)
        if "roi_outcome" in cols:
            set_parts.append("roi_outcome = ?")
            values.append(roi_outcome)
        if "roi_value_bet" in cols and roi_value_bet is not None:
            set_parts.append("roi_value_bet = ?")
            values.append(roi_value_bet)
        if "value_bet_correct" in cols and value_bet_correct is not None:
            set_parts.append("value_bet_correct = ?")
            values.append(value_bet_correct)

        values.append(match_id)
        cursor.execute(
            f"UPDATE {table_name} SET {', '.join(set_parts)} WHERE match_id = ?",
            values
        )
        conn.commit()

def get_pending_predictions(sport: str) -> List[Dict]:
    """Возвращает список прогнозов, для которых ещё нет результатов."""
    with _get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        table_name = f"{_validate_sport(sport)}_predictions"
        cursor.execute(f"SELECT * FROM {table_name} WHERE real_outcome IS NULL")
        return [dict(row) for row in cursor.fetchall()]


def expire_stale_predictions(days: int = 4) -> int:
    """
    Помечает как 'expired' прогнозы старше N дней без результата.
    Это предотвращает бесконечный рост 'ожидают результата'.
    """
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    sports = ["football", "cs2", "tennis", "basketball", "hockey"]
    total_expired = 0
    with _get_db_connection() as conn:
        for sport in sports:
            try:
                table = f"{sport}_predictions"
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                if not cols:
                    continue
                cur = conn.execute(
                    f"UPDATE {table} SET real_outcome='expired', is_correct=-1 "
                    f"WHERE real_outcome IS NULL AND created_at < ?",
                    (cutoff,)
                )
                if cur.rowcount:
                    total_expired += cur.rowcount
                    logging.getLogger(__name__).info(
                        f"[DB] Expired {cur.rowcount} stale {sport} predictions (>{days}d)"
                    )
            except Exception:
                pass
        conn.commit()
    return total_expired

# ── Кеш get_statistics() — результаты не меняются чаще раза в 2 минуты ──────
import time as _stats_time
_stats_cache: dict = {}
_stats_cache_ts: dict = {}
_STATS_TTL = 30  # 30 секунд

def get_statistics(sport: Optional[str] = None) -> Dict:
    """Возвращает статистику по прогнозам (с кешем 2 мин). Если sport не указан — общая."""
    cache_key = sport or "__all__"
    now = _stats_time.time()
    if cache_key in _stats_cache and (now - _stats_cache_ts.get(cache_key, 0)) < _STATS_TTL:
        return _stats_cache[cache_key]
    stats = {}
    sports_to_check = [sport] if sport else ['football', 'cs2', 'tennis', 'basketball', 'hockey']

    with _get_db_connection() as conn:
        cursor = conn.cursor()

        for s in sports_to_check:
            table_name = f"{s}_predictions"
            try:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                if not cursor.fetchone():
                    continue
            except Exception:
                continue

            try:
                # Общая статистика (expired = -1 не считается как checked)
                _hf = "AND (hidden IS NULL OR hidden = 0)"
                total = cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE 1=1 {_hf}").fetchone()[0]
                correct = cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE is_correct = 1 {_hf}").fetchone()[0]
                total_checked = cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE is_correct IN (0, 1) {_hf}"
                ).fetchone()[0]
                # Настоящий pending — ещё нет результата (не expired)
                true_pending = cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE real_outcome IS NULL {_hf}"
                ).fetchone()[0]

                # Статистика по Value Bets
                cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]
                has_vb = "value_bet_correct" in cols
                has_roi_vb = "roi_value_bet" in cols

                vb_checked = cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE value_bet_correct IS NOT NULL"
                ).fetchone()[0] if has_vb else 0
                vb_correct_count = cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE value_bet_correct = 1"
                ).fetchone()[0] if has_vb else 0
                roi_vb_row = cursor.execute(
                    f"SELECT SUM(roi_value_bet) FROM {table_name} WHERE roi_value_bet IS NOT NULL"
                ).fetchone()[0] if has_roi_vb else None
                roi_main_row = cursor.execute(
                    f"SELECT SUM(roi_outcome) FROM {table_name} WHERE roi_outcome IS NOT NULL"
                ).fetchone()[0] if "roi_outcome" in cols else None
                vb_accuracy = (vb_correct_count / vb_checked * 100) if vb_checked > 0 else 0

                # Последние результаты — выбираем только существующие колонки
                base_cols = "home_team, away_team, recommended_outcome, is_correct, created_at"
                extra_cols = ""
                if "real_home_score" in cols:
                    extra_cols += ", real_home_score, real_away_score"
                else:
                    extra_cols += ", NULL as real_home_score, NULL as real_away_score"
                if "is_ensemble_correct" in cols:
                    extra_cols += ", is_ensemble_correct"
                else:
                    extra_cols += ", NULL as is_ensemble_correct"
                if "value_bet_outcome" in cols:
                    extra_cols += ", value_bet_outcome, value_bet_correct, value_bet_odds"
                else:
                    extra_cols += ", NULL as value_bet_outcome, NULL as value_bet_correct, NULL as value_bet_odds"

                recent = cursor.execute(f"""
                SELECT {base_cols}{extra_cols}
                FROM {table_name}
                WHERE is_correct IS NOT NULL AND (hidden IS NULL OR hidden = 0)
                ORDER BY result_checked_at DESC
                LIMIT 10
                """).fetchall()

                # По месяцам
                ens_expr = "SUM(CASE WHEN is_ensemble_correct = 1 THEN 1 ELSE 0 END)" if "is_ensemble_correct" in cols else "0"
                vb_expr = "SUM(CASE WHEN value_bet_correct = 1 THEN 1 ELSE 0 END)" if has_vb else "0"
                roi_vb_expr = "SUM(COALESCE(roi_value_bet, 0))" if has_roi_vb else "0"
                monthly = cursor.execute(f"""
                SELECT strftime('%Y-%m', created_at) as month,
                       COUNT(*) as total,
                       SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct,
                       {ens_expr} as ens_correct,
                       {vb_expr} as vb_correct,
                       {roi_vb_expr} as roi_vb
                FROM {table_name}
                WHERE is_correct IN (0, 1)
                GROUP BY month
                ORDER BY month DESC
                LIMIT 6
                """).fetchall()

                stats[s] = {
                    "total": total,
                    "total_checked": total_checked,
                    "correct": correct,
                    "pending": true_pending,
                    "accuracy": (correct / total_checked * 100) if total_checked > 0 else 0,
                    "roi_main": round(roi_main_row, 2) if roi_main_row is not None else 0,
                    "vb_checked": vb_checked,
                    "vb_correct": vb_correct_count,
                    "vb_accuracy": round(vb_accuracy, 2),
                    "roi_value_bet": round(roi_vb_row, 2) if roi_vb_row is not None else 0,
                    "recent": [dict(row) for row in recent],
                    "monthly": [dict(row) for row in monthly],
                }
            except Exception as _stat_err:
                import logging as _log
                _log.getLogger(__name__).warning(f"[DB] get_statistics {s} error: {_stat_err}")

    _stats_cache[cache_key] = stats
    _stats_cache_ts[cache_key] = _stats_time.time()
    return stats


def get_stavit_bets(sport: str = "football", limit: int = 30, offset: int = 0) -> list:
    """Возвращает прогнозы где бот сказал СТАВИТЬ, с результатами."""
    table = f"{sport}_predictions"
    with _get_db_connection() as conn:
        try:
            # bookmaker_odds_draw есть только у футбола
            _cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            _draw_col = "bookmaker_odds_draw," if "bookmaker_odds_draw" in _cols else "NULL as bookmaker_odds_draw,"
            _lim = f"LIMIT {limit} OFFSET {offset}" if limit > 0 else ""
            _stavit_filter = "(bet_signal LIKE 'СТАВИТЬ%' OR bet_signal LIKE '%СТАВИТЬ' AND bet_signal NOT LIKE 'НЕ СТАВИТЬ%')"
            rows = conn.execute(f"""
                SELECT home_team, away_team, recommended_outcome,
                       bookmaker_odds_home, {_draw_col} bookmaker_odds_away,
                       is_correct, NULL as real_home_score, NULL as real_away_score,
                       roi_outcome, match_date, created_at
                FROM {table}
                WHERE {_stavit_filter}
                ORDER BY created_at DESC
                {_lim}
            """).fetchall()
            _hf2 = "AND (hidden IS NULL OR hidden = 0)"
            total = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {_stavit_filter} {_hf2}"
            ).fetchone()[0]
            wins   = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {_stavit_filter} AND is_correct = 1 {_hf2}"
            ).fetchone()[0]
            losses = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {_stavit_filter} AND is_correct = 0 {_hf2}"
            ).fetchone()[0]
            roi_sum = conn.execute(
                f"SELECT SUM(roi_outcome) FROM {table} WHERE {_stavit_filter} AND roi_outcome IS NOT NULL {_hf2}"
            ).fetchone()[0] or 0.0
            return {
                "rows": [dict(r) for r in rows],
                "total": total,
                "wins": wins,
                "losses": losses,
                "pending": total - wins - losses,
                "roi": round(roi_sum, 2),
                "accuracy": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
            }
        except Exception:
            return {"rows": [], "total": 0, "wins": 0, "losses": 0, "pending": 0, "roi": 0, "accuracy": 0}


def get_pending_stavit(limit: int = 20) -> list:
    """Возвращает pending СТАВИТЬ прогнозы по всем видам спорта для ручного ввода результата."""
    sports = ["football", "cs2", "tennis", "basketball"]
    result = []
    with _get_db_connection() as conn:
        for sport in sports:
            table = f"{sport}_predictions"
            try:
                rows = conn.execute(f"""
                    SELECT match_id, home_team, away_team, recommended_outcome,
                           match_date, created_at, '{sport}' as sport
                    FROM {table}
                    WHERE (bet_signal LIKE 'СТАВИТЬ%' OR (bet_signal LIKE '%СТАВИТЬ' AND bet_signal NOT LIKE 'НЕ СТАВИТЬ%')) AND is_correct IS NULL
                      AND (real_outcome IS NULL OR real_outcome = '')
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                result.extend([dict(r) for r in rows])
            except Exception:
                pass
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result[:limit]


def set_manual_result(sport: str, match_id: str, real_outcome: str, is_correct: int):
    """Записывает результат вручную (без счёта)."""
    update_result(
        sport=sport,
        match_id=match_id,
        real_home_score=None,
        real_away_score=None,
        real_outcome=real_outcome,
        is_correct=is_correct,
    )
    invalidate_stats_cache()


def invalidate_stats_cache():
    """Сбрасывает кеш статистики — следующий вызов пойдёт в БД."""
    _stats_cache.clear()
    _stats_cache_ts.clear()


# ─── Личный кабинет пользователя ─────────────────────────────────────────────

def upsert_user(user_id: int, username: str = "", first_name: str = ""):
    """Создаёт или обновляет запись пользователя."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_db_connection() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                first_name  = excluded.first_name,
                last_active = excluded.last_active
        """, (user_id, username or "", first_name or "", now, now))
        conn.commit()


def track_analysis(user_id: int, sport: str):
    """Увеличивает счётчик анализов пользователя по виду спорта."""
    col_map = {"football": "analyses_football", "cs2": "analyses_cs2", "tennis": "analyses_tennis", "basketball": "analyses_basketball", "hockey": "analyses_hockey"}
    col = col_map.get(sport, "analyses_football")
    now = datetime.now(timezone.utc).isoformat()
    with _get_db_connection() as conn:
        conn.execute(f"""
            UPDATE users SET {col} = {col} + 1,
                             analyses_total = analyses_total + 1,
                             last_active = ?
            WHERE user_id = ?
        """, (now, user_id))
        conn.commit()


# ── Кеш профилей — каждый клик не должен открывать новое соединение ─────────
_user_profile_cache: dict = {}  # user_id → (ts, profile_dict)
_USER_PROFILE_TTL = 30  # 30 секунд достаточно — профиль меняется редко

def _invalidate_user_cache(user_id: int):
    """Сбрасывает кеш профиля при изменении данных пользователя."""
    _user_profile_cache.pop(user_id, None)

def get_user_profile(user_id: int) -> Optional[Dict]:
    """Возвращает профиль пользователя (с кешем 30 сек)."""
    now = _stats_time.time()
    cached = _user_profile_cache.get(user_id)
    if cached and (now - cached[0]) < _USER_PROFILE_TTL:
        return cached[1]
    with _get_db_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        result = dict(row) if row else None
    _user_profile_cache[user_id] = (now, result)
    return result


def get_user_language(user_id: int) -> str:
    """Возвращает язык пользователя (ru/en), по умолчанию ru."""
    profile = get_user_profile(user_id)  # из кеша
    if profile:
        return profile.get("language") or "ru"
    return "ru"


def set_user_language(user_id: int, lang: str):
    """Сохраняет выбранный язык пользователя."""
    with _get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, language) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET language = excluded.language",
            (user_id, lang)
        )
        conn.commit()
    _invalidate_user_cache(user_id)


def set_user_bankroll(user_id: int, amount: float):
    """Сохраняет размер банка пользователя."""
    with _get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, bankroll) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET bankroll = excluded.bankroll",
            (user_id, amount)
        )
        conn.commit()
    _invalidate_user_cache(user_id)


def get_user_bankroll(user_id: int) -> Optional[float]:
    """Возвращает банк пользователя (из кеша профиля)."""
    profile = get_user_profile(user_id)
    if profile:
        return profile.get("bankroll")
    return None


# ─── Подписки ─────────────────────────────────────────────────────────────────

def grant_subscription(user_id: int, days: int, sub_type: str = "full"):
    """Выдаёт или продлевает подписку пользователю на N дней."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    with _get_db_connection() as conn:
        row = conn.execute("SELECT subscription_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0]:
            try:
                current = datetime.fromisoformat(row[0])
                until = current + timedelta(days=days) if current > now else now + timedelta(days=days)
            except Exception:
                until = now + timedelta(days=days)
        else:
            until = now + timedelta(days=days)
        conn.execute(
            "UPDATE users SET subscription_until=?, subscription_type=? WHERE user_id=?",
            (until.isoformat(), sub_type, user_id)
        )
        conn.commit()
    _invalidate_user_cache(user_id)
    return until


def grant_trial(user_id: int) -> bool:
    """Выдаёт 3-дневный пробный период. Возвращает False если уже использован."""
    with _get_db_connection() as conn:
        row = conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or row[0]:
            return False
        conn.execute("UPDATE users SET trial_used=1 WHERE user_id=?", (user_id,))
        conn.commit()
    grant_subscription(user_id, 3, sub_type="trial")
    return True


def revoke_subscription(user_id: int):
    """Отзывает подписку пользователя."""
    with _get_db_connection() as conn:
        conn.execute("UPDATE users SET subscription_until=NULL WHERE user_id=?", (user_id,))
        conn.commit()
    _invalidate_user_cache(user_id)


def get_subscription_status(user_id: int) -> dict:
    """
    Возвращает статус подписки пользователя.
    {
        "has_sub": bool,        # активная подписка
        "sub_type": str,        # "free" | "trial" | "full"
        "until": str | None,    # дата окончания ISO
        "days_left": int,       # дней осталось
        "trial_used": bool,     # использовал ли пробный
        "weekly_used": int,     # анализов за неделю (free)
        "weekly_left": int,     # осталось бесплатных (0-2)
        "daily_used": int,      # анализов сегодня (trial)
        "daily_left": int,      # осталось сегодня (0-4)
    }
    """
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    today = now.date().isoformat()
    today_monday = (now.date() - _dt.timedelta(days=now.weekday())).isoformat()

    with _get_db_connection() as conn:
        row = conn.execute(
            "SELECT subscription_until, subscription_type, trial_used, "
            "weekly_analyses_used, weekly_reset_date, "
            "daily_analyses_used, daily_reset_date FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

    if not row:
        return {"has_sub": False, "sub_type": "free", "until": None, "days_left": 0,
                "trial_used": False, "weekly_used": 0, "weekly_left": 2,
                "daily_used": 0, "daily_left": 4}

    sub_until, sub_type, trial_used, weekly_used, weekly_reset, daily_used, daily_reset = row
    sub_type = sub_type or "free"

    # Сброс недельного счётчика (для бесплатных)
    if weekly_reset != today_monday:
        with _get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET weekly_analyses_used=0, weekly_reset_date=? WHERE user_id=?",
                (today_monday, user_id)
            )
            conn.commit()
        weekly_used = 0

    # Сброс дневного счётчика (для пробных)
    if daily_reset != today:
        with _get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET daily_analyses_used=0, daily_reset_date=? WHERE user_id=?",
                (today, user_id)
            )
            conn.commit()
        daily_used = 0

    has_sub = False
    days_left = 0
    if sub_until:
        try:
            until_dt = _dt.datetime.fromisoformat(sub_until)
            if until_dt > now:
                has_sub = True
                days_left = (until_dt.date() - now.date()).days
            else:
                sub_type = "free"
        except Exception:
            pass

    if not has_sub:
        sub_type = "free"

    return {
        "has_sub": has_sub,
        "sub_type": sub_type,
        "until": sub_until,
        "days_left": days_left,
        "trial_used": bool(trial_used),
        "weekly_used": weekly_used,
        "weekly_left": max(0, 2 - weekly_used),
        "daily_used": daily_used or 0,
        "daily_left": max(0, 4 - (daily_used or 0)),
    }


def increment_weekly_analysis(user_id: int):
    """Увеличивает счётчик бесплатных анализов за неделю."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    today_monday = (now.date() - _dt.timedelta(days=now.weekday())).isoformat()
    with _get_db_connection() as conn:
        conn.execute(
            "UPDATE users SET weekly_analyses_used=weekly_analyses_used+1, weekly_reset_date=? WHERE user_id=?",
            (today_monday, user_id)
        )
        conn.commit()


def increment_daily_analysis(user_id: int):
    """Увеличивает счётчик дневных анализов (для пробного тарифа)."""
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    with _get_db_connection() as conn:
        conn.execute(
            "UPDATE users SET daily_analyses_used=daily_analyses_used+1, daily_reset_date=? WHERE user_id=?",
            (today, user_id)
        )
        conn.commit()


def get_users_list(limit: int = 30) -> list:
    """Возвращает список пользователей с статусом подписки для /users команды."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _get_db_connection() as conn:
        rows = conn.execute("""
            SELECT user_id, username, first_name, last_active,
                   subscription_until, trial_used, analyses_total
            FROM users
            ORDER BY last_active DESC
            LIMIT ?
        """, (limit,)).fetchall()
    result = []
    for r in rows:
        uid, uname, fname, last_active, sub_until, trial_used, total = r
        has_sub = False
        days_left = 0
        if sub_until:
            try:
                until_dt = datetime.fromisoformat(sub_until)
                if until_dt.isoformat() > now:
                    has_sub = True
                    from datetime import datetime as _dt
                    days_left = (_dt.fromisoformat(sub_until).date() - _dt.fromisoformat(now).date()).days
            except Exception:
                pass
        result.append({
            "user_id": uid,
            "username": uname or fname or str(uid),
            "last_active": (last_active or "")[:10],
            "has_sub": has_sub,
            "days_left": days_left,
            "trial_used": bool(trial_used),
            "analyses_total": total or 0,
        })
    return result


def log_action(user_id: int, action: str, username: str = ""):
    """Логирует действие пользователя. Не блокирует — fire-and-forget."""
    import logging as _logging
    _log = _logging.getLogger("chimera.users")
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _get_db_connection() as conn:
            # Получаем username если не передан
            if not username:
                row = conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (user_id,)).fetchone()
                if row:
                    username = row[0] or row[1] or str(user_id)
            conn.execute(
                "INSERT INTO user_actions (user_id, action, ts) VALUES (?, ?, ?)",
                (user_id, action, now)
            )
            conn.execute(
                "UPDATE users SET last_active = ? WHERE user_id = ?",
                (now, user_id)
            )
            conn.commit()
        _log.info(f"[USER] {username or user_id} → {action}")
    except Exception:
        pass  # не ломаем бота из-за логирования


def get_admin_stats() -> dict:
    """Возвращает статистику для /admin панели."""
    with _get_db_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        now_iso = datetime.now(timezone.utc).isoformat()
        day_ago  = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=1)).isoformat()
        week_ago = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=7)).isoformat()

        active_today = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM users WHERE last_active >= ?", (day_ago,)
        ).fetchone()[0]
        active_week = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM users WHERE last_active >= ?", (week_ago,)
        ).fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE first_seen >= ?", (day_ago,)
        ).fetchone()[0]
        new_week = conn.execute(
            "SELECT COUNT(*) FROM users WHERE first_seen >= ?", (week_ago,)
        ).fetchone()[0]

        # Топ-10 активных
        top_users = conn.execute("""
            SELECT user_id, username, first_name, analyses_total, last_active
            FROM users ORDER BY analyses_total DESC LIMIT 10
        """).fetchall()

        # Последние действия (30 записей)
        last_actions = conn.execute("""
            SELECT ua.ts, ua.user_id, u.username, u.first_name, ua.action
            FROM user_actions ua
            LEFT JOIN users u ON ua.user_id = u.user_id
            ORDER BY ua.ts DESC LIMIT 30
        """).fetchall()

        # Популярные разделы за неделю
        popular = conn.execute("""
            SELECT action, COUNT(*) as cnt
            FROM user_actions WHERE ts >= ?
            GROUP BY action ORDER BY cnt DESC LIMIT 10
        """, (week_ago,)).fetchall()

    return {
        "total_users":   total_users,
        "active_today":  active_today,
        "active_week":   active_week,
        "new_today":     new_today,
        "new_week":      new_week,
        "top_users":     [dict(r) for r in top_users],
        "last_actions":  [dict(r) for r in last_actions],
        "popular":       [dict(r) for r in popular],
    }


def get_pl_stats(days: int = 30) -> dict:
    """
    Считает P&L статистику бота за последние N дней.
    Только сигналы где bet_signal='СТАВИТЬ' и есть real_outcome.
    Возвращает: total, wins, losses, roi, profit_units, best_streak, current_streak
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    tables = ["football_predictions", "cs2_predictions", "tennis_predictions", "basketball_predictions", "hockey_predictions"]

    all_bets = []
    with _get_db_connection() as conn:
        for table in tables:
            try:
                rows = conn.execute(f"""
                    SELECT recommended_outcome, real_outcome,
                           bookmaker_odds_home, bookmaker_odds_away,
                           created_at
                    FROM {table}
                    WHERE (bet_signal LIKE 'СТАВИТЬ%' OR (bet_signal LIKE '%СТАВИТЬ' AND bet_signal NOT LIKE 'НЕ СТАВИТЬ%'))
                      AND real_outcome IS NOT NULL
                      AND real_outcome != ''
                      AND real_outcome != 'expired'
                      AND created_at >= ?
                      AND (hidden IS NULL OR hidden = 0)
                    ORDER BY created_at ASC
                """, (cutoff,)).fetchall()
                all_bets.extend(rows)
            except Exception:
                continue

    if not all_bets:
        return {"total": 0, "wins": 0, "losses": 0, "roi": 0.0,
                "profit_units": 0.0, "best_streak": 0, "current_streak": 0}

    wins = 0
    losses = 0
    profit = 0.0
    best_streak = 0
    current_streak = 0
    streak_sign = None  # 'w' or 'l'

    for rec_outcome, real_outcome, odds_home, odds_away, _ in all_bets:
        is_win = (rec_outcome == real_outcome)
        # Определяем коэффициент рекомендованного исхода
        if rec_outcome == "home_win":
            odds = float(odds_home or 0)
        elif rec_outcome == "away_win":
            odds = float(odds_away or 0)
        else:
            odds = 0.0
        if odds < 1.02:
            odds = 1.85  # fallback

        if is_win:
            wins += 1
            profit += (odds - 1)
            if streak_sign == 'w':
                current_streak += 1
            else:
                current_streak = 1
                streak_sign = 'w'
        else:
            losses += 1
            profit -= 1.0
            if streak_sign == 'l':
                current_streak += 1
            else:
                current_streak = 1
                streak_sign = 'l'

        if streak_sign == 'w' and current_streak > best_streak:
            best_streak = current_streak

    total = wins + losses
    roi = round(profit / total * 100, 1) if total > 0 else 0.0

    return {
        "total":          total,
        "wins":           wins,
        "losses":         losses,
        "roi":            roi,
        "profit_units":   round(profit, 2),
        "best_streak":    best_streak,
        "current_streak": current_streak if streak_sign == 'w' else 0,
        "days":           days,
    }


def get_unnotified_bets() -> list:
    """
    Возвращает ставки пользователей у которых уже есть результат, но уведомление ещё не отправлено.
    """
    sport_tables = {
        "football": "football_predictions",
        "cs2": "cs2_predictions",
        "tennis": "tennis_predictions",
        "basketball": "basketball_predictions",
        "hockey": "hockey_predictions",
    }
    result = []
    with _get_db_connection() as conn:
        for sport, table in sport_tables.items():
            try:
                rows = conn.execute(f"""
                    SELECT ub.id, ub.user_id, ub.sport, ub.prediction_id, ub.odds, ub.units,
                           p.home_team, p.away_team, p.recommended_outcome, p.real_outcome,
                           p.bookmaker_odds_home, p.bookmaker_odds_away,
                           p.ensemble_home, p.ensemble_away
                    FROM user_bets ub
                    JOIN {table} p ON p.id = ub.prediction_id
                    WHERE ub.sport = ? AND ub.notified = 0
                      AND p.real_outcome IS NOT NULL
                      AND p.real_outcome NOT IN ('', 'expired')
                """, (sport,)).fetchall()
                for row in rows:
                    result.append(dict(zip(
                        ["bet_id","user_id","sport","prediction_id","odds","units",
                         "home","away","rec_outcome","real_outcome","odds_home","odds_away",
                         "ensemble_home","ensemble_away"],
                        row
                    )))
            except Exception:
                continue
    return result


def mark_bet_notified(bet_id: int):
    """Помечает ставку как уведомлённую."""
    with _get_db_connection() as conn:
        conn.execute("UPDATE user_bets SET notified=1 WHERE id=?", (bet_id,))
        conn.commit()


def get_all_tier_stats() -> dict:
    """
    Возвращает статистику точности по тирам ставок по всем видам спорта.
    Тиры: 'СТАВИТЬ 🔥🔥🔥', 'СТАВИТЬ 🔥🔥', 'СТАВИТЬ 🔥'
    """
    tables = [
        "football_predictions", "cs2_predictions",
        "tennis_predictions", "basketball_predictions", "hockey_predictions",
    ]
    tiers = ["СТАВИТЬ 🔥🔥🔥", "СТАВИТЬ 🔥🔥", "СТАВИТЬ 🔥"]
    totals = {t: {"total": 0, "checked": 0, "wins": 0} for t in tiers}

    with _get_db_connection() as conn:
        for table in tables:
            try:
                _cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                if "bet_signal" not in _cols:
                    continue
                for tier in tiers:
                    row = conn.execute(
                        f"SELECT COUNT(*), "
                        f"SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END), "
                        f"SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) "
                        f"FROM {table} WHERE bet_signal=?", (tier,)
                    ).fetchone()
                    if row:
                        totals[tier]["total"]   += row[0] or 0
                        totals[tier]["checked"] += row[1] or 0
                        totals[tier]["wins"]    += row[2] or 0
            except Exception:
                continue

    result = {}
    for tier, d in totals.items():
        acc = round(d["wins"] / d["checked"] * 100, 1) if d["checked"] > 0 else None
        result[tier] = {"total": d["total"], "checked": d["checked"], "wins": d["wins"], "acc": acc}
    return result


def get_recent_signal_streak() -> int:
    """
    Возвращает текущую серию проигрышей подряд среди сигналов СТАВИТЬ.
    Положительное = серия побед, отрицательное = серия поражений.
    """
    tables = ["football_predictions", "cs2_predictions", "tennis_predictions", "basketball_predictions"]
    all_results = []
    with _get_db_connection() as conn:
        for table in tables:
            try:
                rows = conn.execute(f"""
                    SELECT is_correct, created_at FROM {table}
                    WHERE (bet_signal LIKE 'СТАВИТЬ%' OR (bet_signal LIKE '%СТАВИТЬ' AND bet_signal NOT LIKE 'НЕ СТАВИТЬ%'))
                      AND real_outcome IS NOT NULL
                      AND real_outcome NOT IN ('', 'expired') AND is_correct IS NOT NULL
                      AND (hidden IS NULL OR hidden = 0)
                    ORDER BY created_at DESC LIMIT 10
                """).fetchall()
                all_results.extend(rows)
            except Exception:
                continue
    if not all_results:
        return 0
    all_results.sort(key=lambda x: x[1], reverse=True)
    streak = 0
    first = all_results[0][0]
    for is_correct, _ in all_results:
        if is_correct == first:
            streak += 1
        else:
            break
    return streak if first == 1 else -streak


def get_chimera_signal_history(limit: int = 10) -> list:
    """
    История сигналов дня (match_id начинается с 'chimera_').
    Возвращает список dict: home, away, sport, is_correct, odds, created_at, real_outcome.
    Баскетбольные пики с кэфом > 2.8 скрыты из публичной статистики (баг модели — данные
    хранятся в БД для обучения, но не портят видимый процент пользователям).
    """
    tables = [
        ("football_predictions",   "football"),
        ("cs2_predictions",        "cs2"),
        ("tennis_predictions",     "tennis"),
        ("basketball_predictions", "basketball"),
        ("hockey_predictions",     "hockey"),
    ]
    rows = []
    with _get_db_connection() as conn:
        for table, sport in tables:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                odds_col = ("bookmaker_odds_home" if "bookmaker_odds_home" in cols else "NULL")
                # Баскетбол: скрываем старые пики с кэфом > 2.8 (баг данных Евролиги/NBA)
                # Кэф хранится в home или away в зависимости от recommended_outcome
                has_away_odds = "bookmaker_odds_away" in cols
                if sport == "basketball" and has_away_odds:
                    odds_filter = (
                        "AND (COALESCE(bookmaker_odds_home, bookmaker_odds_away) IS NULL "
                        "OR COALESCE(bookmaker_odds_home, bookmaker_odds_away) <= 2.8)"
                    )
                else:
                    odds_filter = ""
                res = conn.execute(f"""
                    SELECT home_team, away_team, is_correct,
                           {odds_col} as odds,
                           created_at, real_outcome, recommended_outcome
                    FROM {table}
                    WHERE match_id LIKE 'chimera_%'
                    {odds_filter}
                    ORDER BY created_at DESC LIMIT {limit}
                """).fetchall()
                for r in res:
                    rows.append({
                        "sport":       sport,
                        "home":        r[0],
                        "away":        r[1],
                        "is_correct":  r[2],
                        "odds":        r[3],
                        "created_at":  r[4],
                        "real_outcome": r[5],
                        "rec":         r[6],
                    })
            except Exception:
                continue
    rows.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return rows[:limit]


def reset_user_bets(user_id: int) -> int:
    """Удаляет все личные ставки пользователя. Возвращает кол-во удалённых записей."""
    with _get_db_connection() as conn:
        cur = conn.execute("DELETE FROM user_bets WHERE user_id=?", (user_id,))
        conn.commit()
        return cur.rowcount


def reset_user_for_testing(user_id: int):
    """Сбрасывает пользователя в состояние нового: лимиты, подписка, пробный период."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    today_monday = (now.date() - _dt.timedelta(days=now.weekday())).isoformat()
    today = now.date().isoformat()
    with _get_db_connection() as conn:
        conn.execute("""
            UPDATE users SET
                subscription_until   = NULL,
                subscription_type    = 'free',
                trial_used           = 0,
                weekly_analyses_used = 0,
                weekly_reset_date    = ?,
                daily_analyses_used  = 0,
                daily_reset_date     = ?
            WHERE user_id = ?
        """, (today_monday, today, user_id))
        conn.commit()
    _invalidate_user_cache(user_id)


def mark_user_bet(user_id: int, sport: str, prediction_id: int, odds: float = 0.0, units: int = 1):
    """Записывает ставку пользователя на прогноз в его личную историю."""
    current_time = datetime.now(timezone.utc).isoformat()
    with _get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM user_bets WHERE user_id=? AND sport=? AND prediction_id=?",
            (user_id, sport, prediction_id)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO user_bets (user_id, sport, prediction_id, odds, units, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, sport, prediction_id, odds, units, current_time)
        )
        conn.commit()
        return True


def get_user_pl_stats(user_id: int, days: int = 30) -> dict:
    """
    Личная P&L статистика пользователя.
    Считает реальный профит в % банка с учётом юнитов и кэфа.
    1u = 1% банка, 2u = 2%, 3u = 3%.
    Выигрыш = units% * (odds-1), Проигрыш = -units%
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sport_tables = {
        "football": "football_predictions",
        "cs2": "cs2_predictions",
        "tennis": "tennis_predictions",
        "basketball": "basketball_predictions",
        "hockey": "hockey_predictions",
    }

    settled = []   # завершённые ставки
    pending = 0    # ждут результата

    with _get_db_connection() as conn:
        for sport, table in sport_tables.items():
            try:
                rows = conn.execute(f"""
                    SELECT p.home_team, p.away_team, p.recommended_outcome,
                           p.real_outcome, p.bookmaker_odds_home, p.bookmaker_odds_away,
                           ub.odds, ub.units, ub.created_at
                    FROM user_bets ub
                    JOIN {table} p ON p.id = ub.prediction_id
                    WHERE ub.user_id = ? AND ub.sport = ? AND ub.created_at >= ?
                    ORDER BY ub.created_at DESC
                """, (user_id, sport, cutoff)).fetchall()

                for row in rows:
                    home, away, rec, real, oh, oa, ub_odds, units, ts = row
                    units = units or 1
                    if not real or real in ('', 'expired'):
                        pending += 1
                        continue
                    odds = float(ub_odds or 0)
                    if odds < 1.02:
                        odds = float(oh if rec == "home_win" else oa or 0)
                    if odds < 1.02:
                        odds = 1.80
                    is_win = (rec == real)
                    profit_pct = units * (odds - 1) if is_win else -float(units)
                    settled.append({
                        "sport": sport,
                        "home": home, "away": away,
                        "rec": rec, "real": real,
                        "odds": round(odds, 2),
                        "units": units,
                        "profit_pct": round(profit_pct, 2),
                        "is_win": is_win,
                        "ts": ts,
                    })
            except Exception:
                continue

    # Сортируем по дате (новые первые)
    settled.sort(key=lambda x: x["ts"], reverse=True)

    wins = sum(1 for b in settled if b["is_win"])
    losses = sum(1 for b in settled if not b["is_win"])
    total_wagered_pct = sum(b["units"] for b in settled)  # % банка поставлено суммарно
    profit_pct = sum(b["profit_pct"] for b in settled)
    roi = round(profit_pct / total_wagered_pct * 100, 1) if total_wagered_pct > 0 else 0.0

    # Текущий стрик
    streak = 0
    for b in settled:
        if b["is_win"]:
            if streak >= 0:
                streak += 1
            else:
                break
        else:
            if streak <= 0:
                streak -= 1
            else:
                break

    return {
        "total":        len(settled),
        "wins":         wins,
        "losses":       losses,
        "roi":          roi,
        "profit_pct":   round(profit_pct, 2),   # профит в % от банка
        "wagered_pct":  round(total_wagered_pct, 1),
        "streak":       streak,   # >0 = серия побед, <0 = серия поражений
        "pending":      pending,
        "last_bets":    settled[:5],  # последние 5 ставок для отображения
        "days":         days,
    }


if __name__ == "__main__":
    init_db()
    # Пример использования (можно раскомментировать для ручного тестирования)
    # save_prediction(
    #     sport='football',
    #     match_id='match_123',
    #     match_date='2024-03-15',
    #     home_team='Team A',
    #     away_team='Team B',
    #     league='EPL',
    #     recommended_outcome='home_win',
    #     value_bet_outcome='home_win',
    #     value_bet_odds=1.8,
    #     value_bet_ev=0.1,
    #     value_bet_kelly=0.05,
    #     bookmaker_odds_home=1.8,
    #     bookmaker_odds_draw=3.5,
    #     bookmaker_odds_away=4.0,
    # )
    # update_result(
    #     sport='football',
    #     match_id='match_123',
    #     real_home_score=2,
    #     real_away_score=1,
    #     real_outcome='home_win',
    #     is_correct=1,
    #     roi_outcome=0.8,
    #     roi_value_bet=0.8,
    #     value_bet_correct=1,
    # )
    # print(get_statistics('football'))

    # save_prediction(
    #     sport='cs2',
    #     match_id='cs2_match_456',
    #     match_date='2024-03-15',
    #     home_team='Navi',
    #     away_team='G2',
    #     league='ESL Pro League',
    #     recommended_outcome='home_win',
    #     value_bet_outcome='home_win',
    #     value_bet_odds=1.7,
    #     value_bet_ev=0.08,
    #     value_bet_kelly=0.04,
    #     bookmaker_odds_home=1.7,
    #     bookmaker_odds_away=2.1,
    #     predicted_maps=['Inferno', 'Nuke'],
    #     map_advantage_score=0.12,
    #     key_player_advantage=0.1,
    # )
    # update_result(
    #     sport='cs2',
    #     match_id='cs2_match_456',
    #     real_home_score=2,
    #     real_away_score=0,
    #     real_outcome='home_win',
    #     is_correct=1,
    #     roi_outcome=0.7,
    #     roi_value_bet=0.7,
    #     value_bet_correct=1,
    # )
    # print(get_statistics('cs2'))

    # print(get_statistics())
