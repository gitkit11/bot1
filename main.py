# -*- coding: utf-8 -*-
import sys
import io
# Fix Windows cp1252 encoding — allow Cyrillic in print() on any terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import asyncio
import logging
import logging.handlers
import time
import requests

logger = logging.getLogger(__name__)
import os
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import tensorflow as tf
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from config import TELEGRAM_TOKEN, THE_ODDS_API_KEY
try:
    from config import API_FOOTBALL_KEY
except ImportError:
    API_FOOTBALL_KEY = None
from oracle_ai import oracle_analyze
try:
    from agents import (
        run_statistician_agent, run_scout_agent, run_arbitrator_agent,
        run_llama_agent, run_goals_market_agent,
        run_corners_market_agent, run_cards_market_agent, run_handicap_market_agent,
        run_mixtral_agent, build_math_ensemble, calculate_value_bets
    )
except ImportError as _agents_err:
    print(f"[agents] WARN: не удалось импортировать некоторые функции: {_agents_err}")
    # Заглушки — бот запустится, просто эти рынки вернут ошибку
    def run_statistician_agent(*a, **kw): return {"error": "недоступно"}
    def run_scout_agent(*a, **kw): return {"error": "недоступно"}
    def run_arbitrator_agent(*a, **kw): return {"error": "недоступно"}
    def run_llama_agent(*a, **kw): return {"error": "недоступно"}
    def run_goals_market_agent(*a, **kw): return {"error": "недоступно"}
    def run_corners_market_agent(*a, **kw): return {"error": "недоступно"}
    def run_cards_market_agent(*a, **kw): return {"error": "недоступно"}
    def run_handicap_market_agent(*a, **kw): return {"error": "недоступно"}
    def run_mixtral_agent(*a, **kw): return {"error": "недоступно"}
    def build_math_ensemble(*a, **kw): return {}
    def calculate_value_bets(*a, **kw): return []
from signal_engine import (
    check_football_signal, check_cs2_signal, check_draw_signal,
    format_signal, format_signals_list
)
from math_model import (
    load_elo_ratings, save_elo_ratings, update_elo, elo_win_probabilities,
    load_team_form, get_form_string, get_form_bonus,
    poisson_match_probabilities, calculate_expected_goals, format_math_report
)
# Загружаем ELO рейтинги и форму при старте
_elo_ratings = load_elo_ratings()
_team_form = load_team_form()
print(f"[ELO] Loaded {len(_elo_ratings)} teams | Form: {len(_team_form)} teams")

# Семафор: не более 5 параллельных AI-анализов (защита от перегрузки API)
_ai_semaphore = asyncio.Semaphore(5)

from api_football import get_match_stats
try:
    from understat_stats import format_xg_stats, get_team_xg_stats
    UNDERSTAT_AVAILABLE = True
except ImportError:
    UNDERSTAT_AVAILABLE = False
    def format_xg_stats(h, a, s='2025'): return ""
    def get_team_xg_stats(t, s='2025'): return None
from database import init_db, save_prediction, get_statistics, get_pending_predictions, update_result, upsert_user, track_analysis, get_user_profile, get_user_language, set_user_language, set_user_bankroll, get_user_bankroll, get_pl_stats, mark_user_bet, get_user_pl_stats, get_unnotified_bets, mark_bet_notified, get_recent_signal_streak, get_chimera_signal_history, log_action, get_admin_stats, invalidate_stats_cache, get_stavit_bets, get_pending_stavit, set_manual_result, reset_user_bets
from i18n import t
from meta_learner import MetaLearner
try:
    from injuries import get_match_injuries, get_match_injuries_async
    INJURIES_AVAILABLE = True
except ImportError:
    INJURIES_AVAILABLE = False
    def get_match_injuries(h, a): return {}, {}, ""
    async def get_match_injuries_async(h, a): return {}, {}, ""

# --- Импорты из вынесенных модулей ---
from state import (
    matches_cache as _state_matches_cache,
    _league_matches_cache, _LEAGUE_CACHE_TTL,
    cs2_matches_cache, tennis_matches_cache, analysis_cache,
    _report_cache, _REPORT_CACHE_TTL,
    _signals_scan_cache, SIGNALS_SCAN_TTL,
    _chimera_waiting, _chimera_daily, _chimera_history,
    _awaiting_bankroll,
    CHIMERA_DAILY_LIMIT, ADMIN_IDS,
    _error_log, _bot_start_time,
)
from circuit_breaker import get_breaker, all_statuses as cb_all_statuses
from keyboards import (
    FOOTBALL_LEAGUES, PAGE_SIZE,
    build_main_keyboard, build_football_keyboard,
    format_matches_list, build_matches_keyboard,
    build_markets_keyboard, build_back_to_markets_keyboard,
    _build_hunt_kb,
)
from formatters import (
    _safe_truncate, translate_outcome, conf_icon,
    format_main_report, format_goals_report,
    format_corners_report, format_cards_report, format_handicap_report,
    _format_chimera_page, _build_chimera_carousel_kb, _build_chimera_kb,
    _make_loss_explanation,
)
from background_tasks import (
    update_elo_after_match,
    run_update_internal, run_hltv_update_task,
    run_calibration_task, _run_calibration_sync,
    run_tennis_form_prefetch_task,
    check_results_task,
    auto_elo_recalibration_task,
    auto_refresh_matches_task,
)

# --- 1. Настройка логирования ---
os.makedirs("logs", exist_ok=True)
_log_handler = logging.handlers.TimedRotatingFileHandler(
    "logs/bot.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S %p',
    handlers=[logging.StreamHandler(), _log_handler]
)


class _ErrorLogHandler(logging.Handler):
    """Перехватывает WARNING+ и пишет в _error_log для /admin и /ping."""
    _NOISE = ("TensorFlow", "GPU support", "absl-py", "oneDNN")

    def emit(self, record: logging.LogRecord):
        if record.levelno >= logging.WARNING:
            msg = self.format(record)
            if any(s in msg for s in self._NOISE):
                return
            try:
                _error_log.append({
                    "ts": datetime.now(timezone.utc).strftime("%H:%M"),
                    "level": record.levelname,
                    "msg": msg[:200],
                })
            except Exception:
                pass

_error_handler = _ErrorLogHandler()
_error_handler.setLevel(logging.WARNING)
logging.getLogger().addHandler(_error_handler)

# --- 1.1. Инициализация aiogram ---
dp = Dispatcher()

# --- 1.2. Подключение роутеров handlers/ ---
from aiogram import Router as _Router
_fallback_router = _Router()   # handle_text + handle_callback идут последними

from handlers import stats as _h_stats
from handlers import admin as _h_admin
from handlers import user as _h_user
from handlers import express as _h_express
from handlers import basketball as _h_basketball
from handlers import tennis as _h_tennis
from handlers import hockey as _h_hockey
dp.include_router(_h_stats.router)
dp.include_router(_h_admin.router)
dp.include_router(_h_user.router)
dp.include_router(_h_express.router)
dp.include_router(_h_basketball.router)
dp.include_router(_h_tennis.router)
dp.include_router(_h_hockey.router)
# _fallback_router подключается ПОСЛЕДНИМ — после регистрации handle_text/handle_callback

# --- 2. Загрузка модели Пророка (через prophet_loader) ---
import prophet_loader as _prophet_loader
_prophet_loader.init()
prophet_model = _prophet_loader.prophet_model
data          = _prophet_loader.data
scaler        = _prophet_loader.scaler
team_encoder  = _prophet_loader.team_encoder
feature_cols  = _prophet_loader.feature_cols

# --- 3. Инициализация базы данных ---
init_db()

# --- 4. Глобальный кэш матчей и анализов (из state.py) ---
# matches_cache — используем напрямую (изменяемый список)
matches_cache = _state_matches_cache  # ссылка на список из state

# --- 5. Вспомогательные функции ---

# Таблица соответствия названий команд (Odds API → датасет АПЛ)
TEAM_NAME_MAP = {
    "Newcastle United": "Newcastle",
    "Wolverhampton Wanderers": "Wolves",
    "Leeds United": "Leeds",
    "Nottingham Forest": "Nott'm Forest",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "West Bromwich Albion": "West Brom",
    "West Ham United": "West Ham",
    "Sheffield Utd": "Sheffield United",
    "Sheffield United FC": "Sheffield United",
    "Brighton and Hove Albion": "Brighton",
    "Brighton & Hove Albion": "Brighton",
    "Tottenham Hotspur": "Tottenham",
    "Leicester City": "Leicester",
    "Aston Villa FC": "Aston Villa",
    "Ipswich Town": "Ipswich",
    "AFC Bournemouth": "Bournemouth",
    "Luton Town": "Luton",
    "Brentford FC": "Brentford",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Arsenal FC": "Arsenal",
    "Chelsea FC": "Chelsea",
    "Liverpool FC": "Liverpool",
    "Burnley FC": "Burnley",
    "Southampton FC": "Southampton",
    "Watford FC": "Watford",
}

def normalize_team(name):
    """Нормализует название команды для поиска в датасете."""
    return TEAM_NAME_MAP.get(name, name)

def get_prophet_prediction(home_team, away_team):
    """Получает предсказание от нейросети Пророк."""
    if not prophet_model or data is None or scaler is None:
        return [0.33, 0.33, 0.34]
    try:
        home_norm = normalize_team(home_team)
        away_norm = normalize_team(away_team)
        home_id = team_encoder.get(home_norm)
        away_id = team_encoder.get(away_norm)
        if home_id is None or away_id is None:
            # Возвращаем None — ансамбль пропустит этот компонент полностью
            # (33/33/33 только портит результат для не-АПЛ команд)
            print(f"[Пророк] Команды вне АПЛ: '{home_team}' / '{away_team}' — пропускаем")
            return None
        home_data = data[data['HomeTeam_encoded'] == home_id].tail(5)
        away_data = data[data['AwayTeam_encoded'] == away_id].tail(5)
        if len(home_data) < 3 or len(away_data) < 3:
            print(f"[Пророк] Мало данных для {home_team}/{away_team}, используем общую выборку")
            sample = data.tail(10)
        else:
            sample = pd.concat([home_data, away_data]).tail(10)
        if len(sample) < 10:
            sample = pd.concat([sample, data.tail(10 - len(sample))])
        sample = sample[feature_cols].tail(10)
        scaled = scaler.transform(sample)
        sequence = np.array([scaled])
        prediction = prophet_model.predict(sequence, verbose=0)[0]
        print(f"[Пророк] {home_team} vs {away_team}: П1={prediction[1]:.2f} Х={prediction[0]:.2f} П2={prediction[2]:.2f}")
        return [float(prediction[0]), float(prediction[1]), float(prediction[2])]
    except Exception as e:
        print(f"[Пророк Ошибка] {e}")
        return [0.33, 0.33, 0.34]

# FOOTBALL_LEAGUES импортирован из keyboards.py

# Белый список лиг для CS2
CS2_WHITELIST_LEAGUES = [
    # ── Tier S / A ──────────────────────────────
    "ESL Pro League",
    "BLAST",
    "IEM",
    "PGL",
    "Majors",
    "ESL One",
    # ── Tier B (стандарт) ───────────────────────
    "CCT",
    "Game Masters",
    "Dust2.dk Ligaen",
    "Exort Series",
    "NODWIN Clutch Series",
    # ── Tier 3 (региональные) ───────────────────
    "Roman Imperium Cup",
    "Regional",
    "Open",
    "Online",
    "Qualifier",
    "Championship",
    "League",
    "Cup",
    "Series",
    "Division",
    "Masters",
]

# Leagues that belong to Tier 3 — lower signal threshold
CS2_TIER3_KEYWORDS = [
    "regional", "open", "qualifier", "division", "roman imperium",
    "nodwin", "exort", "dust2.dk", "game masters",
]

# Текущая выбранная лига (_current_league и _last_matches_refresh из state.py)
_current_league = "soccer_epl"
_last_matches_refresh = 0  # timestamp последнего обновления

def get_matches(league: str = None, force: bool = False):
    """Получает список ближайших матчей через The Odds API для выбранной лиги (кеш 20 мин)."""
    global matches_cache, _last_matches_refresh, _current_league, _league_matches_cache
    import time
    if league:
        _current_league = league
    league_key = _current_league

    # Проверяем кеш по лиге (если force=False и кеш свежий)
    if not force:
        cached_entry = _league_matches_cache.get(league_key)
        if cached_entry and (time.time() - cached_entry["ts"]) < _LEAGUE_CACHE_TTL:
            matches_cache = cached_entry["matches"]
            return cached_entry["matches"]

    # force=True или кеш устарел — инвалидируем только эту лигу
    if force:
        try:
            from odds_cache import invalidate as _inv
            _inv(league_key)
        except ImportError:
            pass
    try:
        from odds_cache import get_odds as _get_odds
        from datetime import datetime, timezone, timedelta
        data = _get_odds(league_key, markets="h2h,totals,spreads")
        if data:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=3)).isoformat()[:19]
            future = [m for m in data if m.get('commence_time', '') > cutoff]
            result = future[:20]
            _league_matches_cache[league_key] = {"matches": result, "ts": time.time()}
            matches_cache = result
            _last_matches_refresh = time.time()
            league_name = dict(FOOTBALL_LEAGUES).get(league_key, league_key)
            print(f"[API] {league_name}: {len(result)} матчей.")
            return result
    except Exception as e:
        print(f"[API Ошибка] {e}")
    # Возвращаем кеш этой лиги если есть, иначе глобальный matches_cache
    cached_entry = _league_matches_cache.get(league_key)
    if cached_entry:
        return cached_entry["matches"]
    return matches_cache

def _blend_ai(base_home_prob: float, ai_results: list,
               home_team: str, away_team: str, ai_weight: float = 0.10) -> float:
    """
    Добавляет AI-вердикты к математической модели с заданным весом.
    base_home_prob — вероятность победы хозяев из математической модели.
    ai_results — список dict-ов от AI агентов (gpt, llama, etc).
    Возвращает скорректированную вероятность.
    """
    votes, total_conf = 0.0, 0.0
    h_low = home_team.lower()
    a_low = away_team.lower()
    win_keys  = {"home_win", "победа хозяев", "п1", "p1", "home"}
    loss_keys = {"away_win", "победа гостей", "п2", "p2", "away"}
    for res in ai_results:
        if not isinstance(res, dict):
            continue
        outcome = str(res.get("recommended_outcome", res.get("outcome", ""))).lower().strip()
        conf = float(res.get("confidence", res.get("final_confidence_percent", 50))) / 100.0
        if outcome in win_keys or any(t in outcome for t in [h_low[:5]]):
            votes += conf
        elif outcome in loss_keys or any(t in outcome for t in [a_low[:5]]):
            votes += 0.0   # голос за away = 0 для home
        else:
            continue
        total_conf += conf
    if total_conf == 0:
        return base_home_prob
    ai_home_prob = votes / total_conf
    return round(base_home_prob * (1 - ai_weight) + ai_home_prob * ai_weight, 3)


def get_bookmaker_odds(match_data):
    """
    Извлекает коэффициенты из данных матча.

    Стратегия (платный план — 62 букмекера):
    1. Pinnacle no-vig → самая точная вероятность в мире
    2. Усреднение по шарп-букмекерам (Pinnacle, Betfair, Betsson, 1xBet)
    3. Fallback на лучшие обычные коэффициенты

    Дополнительно возвращает:
      no_vig_home, no_vig_draw, no_vig_away — вероятности без маржи (из Pinnacle/шарп)
      bookmakers_count — кол-во букмекеров с линией на этот матч
    """
    result = {
        "home_win": 0, "draw": 0, "away_win": 0,
        "over_2_5": 0, "under_2_5": 0,
        "over_1_5": 0, "under_1_5": 0,
        "over_3_5": 0, "under_3_5": 0,
        "handicap_home": 0, "handicap_away": 0, "handicap_line": 0,
        "no_vig_home": 0.0, "no_vig_draw": 0.0, "no_vig_away": 0.0,
        "bookmakers_count": 0,
        "pinnacle_home": 0, "pinnacle_draw": 0, "pinnacle_away": 0,
    }

    SHARP_BOOKS = ["pinnacle", "betfair_ex", "betfair", "matchbook",
                   "smarkets", "lowvig", "betsson", "nordicbet", "marathonbet"]
    PREFERRED   = ["pinnacle", "betfair_ex", "betfair", "marathonbet",
                   "betsson", "unibet", "nordicbet", "1xbet"]

    def _v(v):
        try:
            f = float(v)
            return f if f >= 1.02 else 0.0
        except Exception:
            return 0.0

    try:
        home_team = match_data.get("home_team", "")
        away_team = match_data.get("away_team", "")
        bookmakers = match_data.get("bookmakers", [])
        result["bookmakers_count"] = len(bookmakers)

        # ── Собираем h2h от всех шарп-букмекеров для усреднения ──────────
        sharp_h, sharp_d, sharp_a = [], [], []
        all_h,   all_d,   all_a   = [], [], []

        for bm in bookmakers:
            bm_key = bm.get("key", "").lower()
            is_sharp = any(s in bm_key for s in SHARP_BOOKS)

            for market in bm.get("markets", []):
                if market.get("key") == "h2h":
                    oc = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                    h = _v(oc.get(home_team, 0))
                    a = _v(oc.get(away_team, 0))
                    d = _v(oc.get("Draw", 0))
                    if h and a and d:
                        all_h.append(h); all_d.append(d); all_a.append(a)
                        if is_sharp:
                            sharp_h.append(h); sharp_d.append(d); sharp_a.append(a)
                        # Pinnacle отдельно
                        if "pinnacle" in bm_key:
                            result["pinnacle_home"] = h
                            result["pinnacle_draw"] = d
                            result["pinnacle_away"] = a

                elif market.get("key") == "totals" and result["over_2_5"] == 0:
                    for o in market.get("outcomes", []):
                        pt   = o.get("point", 0)
                        name = o.get("name", "")
                        price = _v(o.get("price", 0))
                        if not price:
                            continue
                        if pt == 2.5 and name == "Over"  and not result["over_2_5"]:
                            result["over_2_5"] = price
                        elif pt == 2.5 and name == "Under" and not result["under_2_5"]:
                            result["under_2_5"] = price
                        elif pt == 1.5 and name == "Over"  and not result["over_1_5"]:
                            result["over_1_5"] = price
                        elif pt == 1.5 and name == "Under" and not result["under_1_5"]:
                            result["under_1_5"] = price
                        elif pt == 3.5 and name == "Over"  and not result["over_3_5"]:
                            result["over_3_5"] = price
                        elif pt == 3.5 and name == "Under" and not result["under_3_5"]:
                            result["under_3_5"] = price

                elif market.get("key") == "spreads" and not result["handicap_home"]:
                    for o in market.get("outcomes", []):
                        name  = o.get("name", "")
                        price = _v(o.get("price", 0))
                        line  = o.get("point", 0)
                        if not price:
                            continue
                        if name == home_team:
                            result["handicap_home"] = price
                            result["handicap_line"] = line
                        elif name == away_team:
                            result["handicap_away"] = price

        # ── Выбираем финальные коэффициенты ───────────────────────────────
        # Приоритет: шарп-буки → все буки
        src_h = sharp_h if sharp_h else all_h
        src_d = sharp_d if sharp_d else all_d
        src_a = sharp_a if sharp_a else all_a

        if src_h:
            # Медиана защищает от выбросов у одного букмекера
            src_h.sort(); src_d.sort(); src_a.sort()
            mid = len(src_h) // 2
            result["home_win"] = round(src_h[mid], 3)
            result["draw"]     = round(src_d[mid], 3)
            result["away_win"] = round(src_a[mid], 3)

        # ── No-vig вероятность (снимаем маржу букмекера) ──────────────────
        # Используем Pinnacle если есть, иначе медиану шарп-буков
        nv_h = result["pinnacle_home"] or result["home_win"]
        nv_d = result["pinnacle_draw"] or result["draw"]
        nv_a = result["pinnacle_away"] or result["away_win"]
        if nv_h and nv_d and nv_a:
            imp_h = 1 / nv_h
            imp_d = 1 / nv_d
            imp_a = 1 / nv_a
            total = imp_h + imp_d + imp_a  # сумма > 1.0 = маржа букмекера
            if total > 0:
                result["no_vig_home"] = round(imp_h / total, 4)
                result["no_vig_draw"] = round(imp_d / total, 4)
                result["no_vig_away"] = round(imp_a / total, 4)

    except Exception as e:
        print(f"[API Ошибка коэффициентов] {e}")
    return result

# translate_outcome и conf_icon импортированы из formatters.py

# --- 6. AI Thinking Animation ---

async def show_ai_thinking(msg, home: str, away: str, sport: str = "football"):
    """
    Живая анимация мышления агентов с указанием моделей под каждым спортом.
    """
    sport_icons = {
        "football":   "⚽",
        "cs2":        "🎮",
        "basketball": "🏀",
        "tennis":     "🎾",
        "hockey":     "🏒",
    }
    icon = sport_icons.get(sport, "🔮")

    # Модели для каждого спорта
    sport_models = {
        "football": (
            "📐 Dixon-Coles\n"
            "📊 ELO + форма\n"
            "🎯 Пуассон / xG\n"
            "🧠 Prophet нейросеть\n"
            "📈 Линия букмекеров"
        ),
        "cs2": (
            "🗺️ MIS — анализ карт\n"
            "📊 ELO + LAN-коэффициент\n"
            "📋 Винрейт (last5 + last20)\n"
            "👤 Рейтинг игроков HLTV\n"
            "🤝 H2H история"
        ),
        "basketball": (
            "📊 ELO рейтинг\n"
            "📈 Линия букмекеров\n"
            "📋 Форма команды\n"
            "🏠 Домашний корт\n"
            "⚡ Back-to-back штраф"
        ),
        "tennis": (
            "🎾 ATP/WTA рейтинг → ELO\n"
            "🏟️ Специализация покрытия\n"
            "📋 Форма (последние матчи)\n"
            "🤝 H2H очные встречи"
        ),
    }

    models_block = sport_models.get(sport, "")

    base = (
        f"<b>{icon} {home}  <code>vs</code>  {away}</b>\n"
        f"<b>🔮 CHIMERA AI</b> — запускаю анализ...\n\n"
        f"<i>Модели:</i>\n{models_block}\n\n"
    )

    steps = [
        ("🐍", "Змея",   "считает математику..."),
        ("🦁", "Лев",    "читает новости и травмы..."),
        ("🐐", "Козёл",  "взвешивает всё..."),
        ("🌀", "Тень",   "независимая проверка..."),
    ]

    active = []
    try:
        for emoji, name, action in steps:
            active.append(f"{emoji} <b>{name}:</b> {action}")
            await msg.edit_text(base + "\n".join(active), parse_mode="HTML")
            await asyncio.sleep(0.9)

        done = "\n".join(f"{e} <b>{n}:</b> <i>готово ✓</i>" for e, n, _ in steps)
        await msg.edit_text(
            base + done + "\n\n<i>⚡ Формирую итоговый отчёт...</i>",
            parse_mode="HTML"
        )
        await asyncio.sleep(0.6)
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")


# --- 6. Клавиатуры импортированы из keyboards.py ---
# build_main_keyboard, build_football_keyboard, format_matches_list,
# build_matches_keyboard, build_markets_keyboard, build_back_to_markets_keyboard, _build_hunt_kb

# --- 7. Форматирование отчётов — импортировано из formatters.py ---

# --- 8. Хендлеры Telegram ---

async def _handle_chimera_question(message: types.Message, question: str):
    """Отвечает на вопрос пользователя от имени Химеры через Llama/Groq."""
    from datetime import date as _date
    today = str(_date.today())
    user_id = message.from_user.id

    # Обновляем счётчик (администраторы — без лимита)
    is_admin = user_id in ADMIN_IDS
    _d = _chimera_daily.get(user_id, ("", 0))
    count = (_d[1] + 1) if _d[0] == today else 1
    if not is_admin:
        _chimera_daily[user_id] = (today, count)
    left = 999 if is_admin else max(0, CHIMERA_DAILY_LIMIT - count)

    # Контекст пользователя из БД
    profile = get_user_profile(user_id)
    total   = profile.get("analyses_total", 0) if profile else 0
    fav_map = {
        "analyses_football":   "⚽ Футбол",
        "analyses_cs2":        "🎮 CS2",
        "analyses_tennis":     "🎾 Теннис",
        "analyses_basketball": "🏀 Баскетбол",
    }
    fav = "—"
    if profile:
        best = max(fav_map, key=lambda k: profile.get(k, 0))
        if profile.get(best, 0) > 0:
            fav = fav_map[best]

    thinking = await message.answer("🐉 <i>Химера думает...</i>", parse_mode="HTML")

    def _ask():
        try:
            from agents import groq_client as _gc, client as _oc
            user_lang = get_user_language(user_id)
            lang_instruction = "Отвечай только на русском языке." if user_lang != "en" else "Reply in English only."
            system_prompt = (
                "Ты — Химера. Не бот, не программа — существо женского рода из трёх голов, "
                "рождённая на стыке математики, интуиции и опыта тысяч матчей.\n\n"
                "Твой характер: мудрая, спокойная, немного загадочная. "
                "Говоришь редко — но каждое слово весит. "
                "Не повторяешь одни и те же мысли. Каждый ответ — новый угол зрения.\n\n"
                "Говори о себе в женском роде. "
                "Ты не хвалишь и не осуждаешь пользователя — ты просто видишь суть. "
                "Отвечай на то, о чём спрашивают — не тащи в ответ лишний контекст про спорт или статистику если тебя не спрашивали. "
                "Когда нужно — философски. Когда нужно — жёстко и коротко. Когда нужно — с юмором.\n\n"
                "Никогда не называй себя ИИ, GPT, ботом или программой. "
                "Не давай советы ставить на конкретные матчи без данных. "
                "Максимум 3-4 предложения. "
                f"{lang_instruction}"
            )
            # История диалога (последние 10 сообщений)
            history = _chimera_history.get(user_id, [])
            if not history:
                # Первый вопрос — добавляем контекст пользователя
                first_msg = (
                    f"[Контекст: пользователь сделал {total} анализов]\n{question}"
                )
                history.append({"role": "user", "content": first_msg})
            else:
                history.append({"role": "user", "content": question})
            # Ограничиваем историю до 10 сообщений (5 пар)
            if len(history) > 10:
                history = history[-10:]
            _chimera_history[user_id] = history
            # Ограничение памяти: если словарь вырос > 200 записей — удаляем самые старые
            if len(_chimera_history) > 200:
                oldest_keys = list(_chimera_history.keys())[:len(_chimera_history) - 200]
                for _ok in oldest_keys:
                    _chimera_history.pop(_ok, None)

            messages = [{"role": "system", "content": system_prompt}] + history
            used_model = None
            result = None
            if _gc:
                try:
                    resp = _gc.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=messages,
                        max_tokens=200,
                        temperature=0.8,
                    )
                    result = resp.choices[0].message.content.strip()
                    used_model = "llama"
                except Exception as groq_err:
                    logger.warning(f"[Химера] Groq недоступен: {groq_err}")
            if result is None and _oc:
                resp = _oc.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=messages,
                    max_tokens=200,
                    temperature=0.8,
                )
                result = resp.choices[0].message.content.strip()
                used_model = "gpt"
            if result:
                _chimera_history.setdefault(user_id, []).append({"role": "assistant", "content": result})
            return (result, used_model)
        except Exception as e:
            logger.error(f"[Химера] Ошибка: {e}")
            return (None, None)

    loop = asyncio.get_running_loop()
    _result = await loop.run_in_executor(None, _ask)
    answer, used_model = _result if isinstance(_result, tuple) else (_result, None)

    if not answer:
        answer = "Древний огонь угас на мгновение. Попробуй ещё раз."
        used_model = None

    if is_admin:
        footer = ""
    elif left > 0:
        footer = f"\n\n<i>Осталось вопросов сегодня: {left}/5</i>"
    else:
        footer = "\n\n<i>Лимит на сегодня исчерпан.</i>"

    # Остаёмся в режиме чата — следующее сообщение тоже пойдёт к Химере
    if len(_chimera_waiting) > 500:
        _chimera_waiting.clear()
    _chimera_waiting.add(user_id)

    exit_kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="🚪 Выйти из чата")]],
        resize_keyboard=True
    )
    await thinking.edit_text(
        f"🐉 <b>Химера:</b>\n\n{answer}{footer}",
        parse_mode="HTML",
    )
    # Показываем кнопку выхода только один раз (при первом ответе)
    if len(_chimera_history.get(user_id, [])) <= 2:
        await message.answer(
            "<i>Продолжай писать — Химера слушает. Нажми «Выйти из чата» чтобы вернуться в меню.</i>",
            parse_mode="HTML",
            reply_markup=exit_kb,
        )


def _build_hunt_kb(page: int, total: int) -> types.InlineKeyboardMarkup:
    """Клавиатура Охоты: пагинация + кнопка обновить."""
    from line_tracker import PER_PAGE
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"hunt_page_{page-1}"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"hunt_page_{page+1}"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([types.InlineKeyboardButton(text="🔄 Обновить", callback_data="hunt_refresh")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def cmd_chimera_hunt(message: types.Message):
    """Охота Химеры — паровые удары: движение острых денег на рынках Pinnacle."""
    try:
        from line_tracker import get_steam_moves, format_steam_moves
        moves = get_steam_moves(hours_back=2)
        text  = format_steam_moves(moves, page=0)
    except Exception as e:
        text  = "🔥 <b>ОХОТА ХИМЕРЫ</b>\n\n😔 Произошёл сбой. Напиши нам в поддержку."
        moves = []
    kb = _build_hunt_kb(0, len(moves))
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(lambda c: c.data == "hunt_refresh")
async def cb_hunt_refresh(call: types.CallbackQuery):
    await call.answer("Обновляю...")
    try:
        from line_tracker import get_steam_moves, format_steam_moves
        moves = get_steam_moves(hours_back=2)
        text  = format_steam_moves(moves, page=0)
    except Exception as e:
        text  = "🔥 <b>ОХОТА ХИМЕРЫ</b>\n\n😔 Произошёл сбой. Напиши нам в поддержку."
        moves = []
    kb = _build_hunt_kb(0, len(moves))
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")


@dp.callback_query(lambda c: c.data.startswith("hunt_page_"))
async def cb_hunt_page(call: types.CallbackQuery):
    await call.answer()
    try:
        page = int(call.data.split("_")[-1])
        from line_tracker import get_steam_moves, format_steam_moves
        moves = get_steam_moves(hours_back=2)
        text  = format_steam_moves(moves, page=page)
    except Exception as e:
        text  = "🔥 <b>ОХОТА ХИМЕРЫ</b>\n\n😔 Произошёл сбой. Напиши нам в поддержку."
        moves = []
        page  = 0
    kb = _build_hunt_kb(page, len(moves))
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")


async def _send_access_denied(message: types.Message, reason: str):
    """Отправляет сообщение об отказе в доступе. При no_channel — добавляет кнопки подписки."""
    from access import get_access_denied_text
    text = get_access_denied_text(reason)
    if reason == "no_channel":
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="📢 Подписаться на канал",
                url="https://t.me/chimera_bet_community"
            )],
            [types.InlineKeyboardButton(
                text="✅ Я подписался",
                callback_data="reenter_main"
            )],
        ])
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@_fallback_router.message()
async def handle_text(message: types.Message):
    text = message.text
    user_id = message.from_user.id

    # ── Химера-чат: пользователь в режиме диалога ────────────────────────────
    MENU_BUTTONS = {
        "📡 Сигналы дня", "📡 Daily Signals",
        "🎯 Экспресс (бета)", "🎯 Express (beta)",
        "⚽ Футбол", "⚽ Football",
        "🎾 Теннис", "🎾 Tennis",
        "🎮 CS2 (бета)", "🎮 CS2 (beta)",
        "🏀 Баскетбол", "🏀 Basketball",
        "🏒 Хоккей", "🏒 Hockey",
        "🔥 Охота Химеры 📈", "🔥 Chimera Hunt 📈",
        "📊 Статистика", "📊 Statistics",
        "👤 Кабинет", "👤 Profile",
        "💎 Подписка Химера", "💎 Chimera Subscription",
        "💬 Поддержка", "💬 Support",
        "/start", "🚪 Выйти из чата",
    }
    if user_id in _chimera_waiting:
        if text in MENU_BUTTONS:
            _chimera_waiting.discard(user_id)
            # продолжаем обработку как обычная кнопка меню
        else:
            await _handle_chimera_question(message, text)
            return

    lang = get_user_language(user_id)

    if text == "🚪 Выйти из чата":
        _chimera_waiting.discard(user_id)
        _chimera_history.pop(user_id, None)
        back_msg = "Returning to menu." if lang == "en" else "Возвращаю тебя в меню."
        await message.answer(back_msg, reply_markup=build_main_keyboard(lang), parse_mode="HTML")
        return

    if text in ("📡 Сигналы дня", "📡 Daily Signals"):
        await cmd_signals(message)
        return

    # ── Проверка доступа ──────────────────────────────────────────────────────
    # Только подписка: Экспресс, Охота Химеры, Сигналы (signals проверяет сам)
    _SUB_ONLY_BUTTONS = {
        "🎯 Экспресс (бета)", "🎯 Express (beta)",
        "🔥 Охота Химеры 📈", "🔥 Chimera Hunt 📈",
    }
    # Бесплатно 2/неделю: все виды спорта
    _SPORT_BUTTONS = {
        "⚽ Футбол", "⚽ Football",
        "🎾 Теннис", "🎾 Tennis",
        "🎮 CS2 (бета)", "🎮 CS2 (beta)",
        "🏀 Баскетбол", "🏀 Basketball",
        "🏒 Хоккей", "🏒 Hockey",
    }
    if message.from_user:
        from access import check_access
        if text in _SUB_ONLY_BUTTONS:
            # Экспресс, Охота: нужна подписка (free не может), trial/full — без счётчика
            _access = await check_access(message.from_user.id, message.bot,
                                         require_full=True, count_analysis=False)
            if _access != "ok":
                await _send_access_denied(message, _access)
                return
        elif text in _SPORT_BUTTONS:
            # Спорт-анализы: free=2/нед, trial=4/день, full=∞
            _access = await check_access(message.from_user.id, message.bot,
                                         require_full=False, count_analysis=True)
            if _access != "ok":
                await _send_access_denied(message, _access)
                return

    if text in ("🎯 Экспресс (бета)", "🎯 Express (beta)"):
        await _h_express.cmd_express(message)

    elif text in ("⚽ Футбол", "⚽ Football"):
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "АПЛ")
        await message.answer(
            f"⚽ *Футбол* — выбери лигу:\n"
            f"Текущая: *{league_name}*",
            parse_mode="Markdown",
            reply_markup=build_football_keyboard()
        )

    elif text in ("🎾 Теннис", "🎾 Tennis"):
        await _h_tennis.cmd_tennis(message)

    elif text in ("🎮 CS2 (бета)", "🎮 CS2 (beta)"):
        await message.answer("⏳ Загружаю матчи CS2...")
        try:
            from sports.cs2 import get_combined_cs2_matches
            _cs2_loop = asyncio.get_running_loop()
            all_cs2_matches = await _cs2_loop.run_in_executor(None, get_combined_cs2_matches)
            
            # Группировка по лигам
            leagues_dict = {}
            for m in all_cs2_matches:
                league_name = m.get('league', 'Other')
                tournament_name = m.get('tournament', '')
                full_name = f"{league_name} {tournament_name}".lower()
                
                matched_league = None
                for allowed in CS2_WHITELIST_LEAGUES:
                    if allowed.lower() in full_name:
                        matched_league = allowed
                        break
                
                if matched_league:
                    if matched_league not in leagues_dict:
                        leagues_dict[matched_league] = []
                    leagues_dict[matched_league].append(m)

            if not leagues_dict:
                await message.answer(
                    "🎮 *Киберспорт CS2*\n\n"
                    "❌ Нет доступных матчей в выбранных лигах.\n\n"
                    "Убедись что в .env есть PANDASCORE_API_KEY",
                    parse_mode="Markdown"
                )
                return

            # Сохраняем все отфильтрованные матчи в кэш для последующего доступа
            cs2_matches_cache.clear()
            all_filtered = []
            for l_matches in leagues_dict.values():
                all_filtered.extend(l_matches)
            cs2_matches_cache.extend(all_filtered)

            # Строим клавиатуру со списком лиг
            builder = InlineKeyboardBuilder()
            for league in sorted(leagues_dict.keys()):
                count = len(leagues_dict[league])
                builder.button(text=f"🏆 {league} ({count})", callback_data=f"cs2_league_{league}")
            builder.adjust(1)
            
            await message.answer(
                f"🎮 *CS2* — Выберите лигу:",
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logger.error(f"[CS2] Ошибка: {e}")
            _cs2_err_kb = InlineKeyboardBuilder()
            _cs2_err_kb.button(text="🔄 Повторить", callback_data="cs2_matches")
            _cs2_err_kb.button(text="🏠 Меню", callback_data="back_to_main")
            _cs2_err_kb.adjust(2)
            await message.answer(
                "🎮 <b>Киберспорт CS2</b>\n\n😔 Произошёл сбой. Напиши нам в поддержку.",
                parse_mode="HTML", reply_markup=_cs2_err_kb.as_markup()
            )

    elif text in ("📊 Статистика", "📊 Statistics"):
        from handlers.stats import get_stats_command
        await get_stats_command(message)

    elif text in ("👤 Кабинет", "👤 Profile"):
        upsert_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
        profile = get_user_profile(message.from_user.id)

        def _get_level(total: int):
            if total >= 100: return ("🐉 Химера",     "Достиг высшего уровня — стал частью Химеры")
            if total >= 50:  return ("👁 Голова",      "Видит то, что скрыто от других")
            if total >= 20:  return ("🔥 Коготь",     "Острый, точный, опасный")
            if total >= 5:   return ("🦴 Лапа",       "Твёрдо стоит на пути")
            return              ("🌱 Хвост",       "Путь только начинается")

        total = profile.get("analyses_total", 0) if profile else 0
        lvl, lvl_desc = _get_level(total)

        # Прогресс до следующего уровня (полоска)
        thresholds = [5, 20, 50, 100]
        next_t = next((t for t in thresholds if t > total), None)
        prev_t = [t for t in thresholds if t <= total]
        prev_t = prev_t[-1] if prev_t else 0
        if next_t:
            bar_filled = round((total - prev_t) / (next_t - prev_t) * 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            progress = f"[{bar}] {total}/{next_t}"
        else:
            progress = "[██████████] Максимум достигнут"

        # Любимый спорт
        fav = "—"
        if profile:
            sport_counts = {
                "⚽ Футбол":    profile.get("analyses_football", 0),
                "🎾 Теннис":    profile.get("analyses_tennis", 0),
                "🎮 CS2":       profile.get("analyses_cs2", 0),
                "🏀 Баскетбол": profile.get("analyses_basketball", 0),
                "🏒 Хоккей":    profile.get("analyses_hockey", 0),
            }
            fav_key = max(sport_counts, key=sport_counts.get)
            fav = fav_key if sport_counts[fav_key] > 0 else "—"

        # Дата регистрации
        since = ""
        if profile and profile.get("first_seen"):
            try:
                dt = datetime.fromisoformat(profile["first_seen"])
                since = dt.strftime("%d.%m.%Y")
            except Exception:
                since = profile["first_seen"][:10]

        name = message.from_user.first_name or "Аналитик"
        username = f"@{message.from_user.username}" if message.from_user.username else ""

        # Дневной лимит вопросов Химере
        from datetime import date as _date
        today = str(_date.today())
        _d = _chimera_daily.get(message.from_user.id, ("", 0))
        questions_used = _d[1] if _d[0] == today else 0
        questions_left = "∞" if message.from_user.id in ADMIN_IDS else max(0, CHIMERA_DAILY_LIMIT - questions_used)

        p = profile or {}
        q_line = f"∞ (admin)" if message.from_user.id in ADMIN_IDS else f"{questions_left}/{CHIMERA_DAILY_LIMIT}"

        bankroll = get_user_bankroll(message.from_user.id)
        pl_block = ""  # трекрекорд бота скрыт

        # Личный P&L пользователя
        upl = get_user_pl_stats(message.from_user.id, days=30)
        if upl["total"] > 0 or upl.get("pending", 0) > 0:
            profit_pct = upl["profit_pct"]
            p_sign = "+" if profit_pct >= 0 else ""
            # Деньги если есть банк
            if bankroll and bankroll > 0:
                profit_money = round(bankroll * profit_pct / 100, 1)
                m_sign = "+" if profit_money >= 0 else ""
                bankroll_now = round(bankroll + profit_money, 1)
                bank_line = f"  💰 <b>{bankroll:.0f}</b>  →  <b>{bankroll_now:.0f}</b>  ({m_sign}{profit_money:.0f})\n"
            else:
                bank_line = f"  💰 <i>Укажи банк — увидишь прибыль в числах</i>\n"
            # Стрик
            s = upl["streak"]
            if s >= 2:
                streak_line = f"  🔥 {s} побед подряд\n"
            elif s <= -2:
                streak_line = f"  ❄️ {abs(s)} поражений подряд\n"
            else:
                streak_line = ""
            # Ожидающие
            pending_line = f"  ⏳ Ждём результат: <b>{upl['pending']}</b>\n" if upl.get("pending", 0) > 0 else ""
            # История последних ставок
            history_lines = []
            for b in upl.get("last_bets", []):
                icon = "✅" if b["is_win"] else "❌"
                p_str = f"+{b['profit_pct']:.1f}%" if b["is_win"] else f"{b['profit_pct']:.1f}%"
                sport_icon = {"football": "⚽", "cs2": "🎮", "tennis": "🎾", "basketball": "🏀", "hockey": "🏒"}.get(
                    b.get("sport", "football"), "🎯")
                team = b["home"] if b["rec"] == "home_win" else b["away"]
                history_lines.append(
                    f"  {icon} {sport_icon} {team[:16]} @ {b['odds']} · {b['units']}u · {p_str}"
                )
            history_block = "\n".join(history_lines)
            _user_wr = round(upl['wins'] / upl['total'] * 100) if upl['total'] > 0 else 0
            _wr_line = f"  Ставок: <b>{upl['total']}</b>  ✅{upl['wins']} ❌{upl['losses']}  Угадано: <b>{_user_wr}%</b>\n"
            upl_block = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 <b>Мои ставки (30 дней)</b>\n"
                f"{bank_line}"
                f"{_wr_line}"
                + f"{streak_line}"
                + f"{pending_line}"
                + (f"\n{history_block}\n" if history_lines else "")
            )
        else:
            upl_block = (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 <b>Мои ставки</b>\n"
                f"  <i>Нажми ✅ под сигналом — ставка запишется сюда.</i>\n"
            )

        # Статус подписки
        from database import get_subscription_status
        sub = get_subscription_status(message.from_user.id)
        if message.from_user.id in ADMIN_IDS:
            sub_line = "👑 <b>Администратор</b>\n"
        elif sub["sub_type"] == "trial":
            sub_line = f"🎁 <b>Пробный период</b> — осталось {sub['days_left']} дн. · {sub['daily_left']}/4 анализов сегодня\n"
        elif sub["sub_type"] == "full":
            sub_line = f"✅ <b>Подписка Химера</b> — осталось {sub['days_left']} дн.\n"
        else:
            sub_line = f"🆓 <b>Бесплатный тариф</b> — {sub['weekly_used']}/2 анализа на этой неделе\n"

        cab_text = (
            f"👤 <b>Личный кабинет</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>{name}</b> {username}\n"
            f"📅 С нами с: <b>{since}</b>\n"
            f"{sub_line}\n"
            f"🏆 <b>Статус:</b> {lvl}\n"
            f"<i>{lvl_desc}</i>\n"
            f"<code>{progress}</code>\n\n"
            f"📊 <b>Статистика анализов</b>\n"
            f"  ⚽ Футбол       <b>{p.get('analyses_football', 0)}</b>\n"
            f"  🎮 CS2          <b>{p.get('analyses_cs2', 0)}</b>\n"
            f"  🏀 Баскетбол    <b>{p.get('analyses_basketball', 0)}</b>\n"
            f"  🏒 Хоккей       <b>{p.get('analyses_hockey', 0)}</b>\n"
            f"  🎾 Теннис       <b>{p.get('analyses_tennis', 0)}</b>\n"
            f"  ─────────────────────\n"
            f"  Всего:          <b>{total}</b>\n\n"
            f"❤️ Любимый спорт: <b>{fav}</b>\n\n"
            f"{pl_block}"
            f"{upl_block}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🐉 <b>Химера</b> — вопросов сегодня: <b>{q_line}</b>"
        )
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="💼 Мой банк", callback_data="set_bankroll"),
             types.InlineKeyboardButton(text="🐉 Спросить Химеру", callback_data="chimera_ask")]
        ])
        await message.answer(cab_text, parse_mode="HTML", reply_markup=kb)

    elif text in ("🏀 Баскетбол", "🏀 Basketball"):
        await _h_basketball.cmd_basketball(message)

    elif text in ("🏒 Хоккей", "🏒 Hockey"):
        await _h_hockey.cmd_hockey(message)

    elif text in ("🔥 Охота Химеры 📈", "🔥 Chimera Hunt 📈"):
        await cmd_chimera_hunt(message)

    elif text in ("💎 Подписка Химера", "💎 Chimera Subscription"):
        from database import get_subscription_status
        sub = get_subscription_status(message.from_user.id)

        if sub["has_sub"]:
            is_trial = sub["days_left"] <= 3 and sub.get("trial_used")
            if is_trial:
                status_block = (
                    f"🎁 <b>Пробная подписка активна</b>\n"
                    f"⏳ Осталось: <b>{sub['days_left']} дн.</b>\n\n"
                    f"Понравилось? Напиши нам — оформим полную подписку.\n"
                ) if lang == "ru" else (
                    f"🎁 <b>Trial subscription active</b>\n"
                    f"⏳ Days left: <b>{sub['days_left']}</b>\n\n"
                    f"Enjoying it? Write to us for a full subscription.\n"
                )
            else:
                until_str = ""
                if sub["until"]:
                    try:
                        from datetime import datetime, timezone
                        until_str = datetime.fromisoformat(sub["until"]).strftime("%d.%m.%Y")
                    except Exception:
                        pass
                status_block = (
                    f"✅ <b>Подписка Химера активирована</b>\n"
                    f"📅 Действует до: <b>{until_str}</b> ({sub['days_left']} дн.)\n\n"
                    f"Полный доступ ко всем функциям открыт.\n"
                ) if lang == "ru" else (
                    f"✅ <b>Chimera Subscription active</b>\n"
                    f"📅 Valid until: <b>{until_str}</b> ({sub['days_left']} days)\n\n"
                    f"Full access to all features is open.\n"
                )
            vip_text = (
                f"💎 <b>Подписка Химера</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{status_block}"
            ) if lang == "ru" else (
                f"💎 <b>Chimera Subscription</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{status_block}"
            )
            await message.answer(vip_text, parse_mode="HTML")
        else:
            free_line = (
                f"📊 Бесплатный тариф: <b>{sub['weekly_used']}/2</b> анализа использовано на этой неделе\n\n"
            ) if lang == "ru" else (
                f"📊 Free plan: <b>{sub['weekly_used']}/2</b> analyses used this week\n\n"
            )
            if lang == "ru":
                vip_text = (
                    "💎 <b>Подписка Химера</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{free_line}"
                    "🆓 <b>Бесплатно</b> — навсегда\n"
                    "  🐉 Химера-чат  ·  📊 Статистика  ·  👤 Кабинет\n"
                    "  ⚽🎾🏀🏒🎮 Анализы — <b>2 в неделю</b> на все виды\n"
                    "  ❌ Сигналы дня / Экспресс / Охота\n\n"
                    "🎁 <b>Пробный</b> — 3 дня бесплатно\n"
                    "  Всё из бесплатного +\n"
                    "  ⚽🎾🏀🏒🎮 Анализы — <b>4 в день</b> на все виды\n"
                    "  ✅ Сигналы дня  ·  ✅ Экспресс  ·  ✅ Охота\n\n"
                    "💎 <b>Подписка</b> — 30 дней · <b>$70</b>\n"
                    "  Всё без ограничений\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🎁 <b>Хочешь попробовать бесплатно?</b>\n"
                    "Напиши нам — дадим <b>3 дня пробного доступа</b> прямо сейчас.\n\n"
                    "👇 Нажми кнопку ниже:"
                )
            else:
                vip_text = (
                    "💎 <b>Chimera Subscription</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{free_line}"
                    "🆓 <b>Free</b> — forever\n"
                    "  🐉 Chimera chat  ·  📊 Statistics  ·  👤 Profile\n"
                    "  ⚽🎾🏀🏒🎮 Analyses — <b>2 per week</b> across all sports\n"
                    "  ❌ Daily Signals / Express / Hunt\n\n"
                    "🎁 <b>Trial</b> — 3 days free\n"
                    "  Everything from Free +\n"
                    "  ⚽🎾🏀🏒🎮 Analyses — <b>4 per day</b> across all sports\n"
                    "  ✅ Daily Signals  ·  ✅ Express  ·  ✅ Hunt\n\n"
                    "💎 <b>Subscription</b> — 30 days · <b>$70</b>\n"
                    "  Everything, unlimited\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🎁 <b>Want to try for free?</b>\n"
                    "Write to us — get <b>3 days trial access</b> right now.\n\n"
                    "👇 Tap the button below:"
                )
            kb = types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(
                    text="✍️ Хочу подписку" if lang == "ru" else "✍️ I want subscription",
                    url="https://t.me/pankotsk1"
                )
            ]])
            await message.answer(vip_text, parse_mode="HTML", reply_markup=kb)

    elif text in ("💬 Поддержка", "💬 Support"):
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="💬 Написать", url="https://t.me/pankotsk1")]
        ])
        await message.answer(
            "🛡 <b>Поддержка CHIMERA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <b>Чем могу помочь:</b>\n"
            "  • Ошибки и баги в боте\n"
            "  • Вопросы по прогнозам и сигналам\n"
            "  • Сотрудничество и партнёрство\n\n"
            "📩 Нажми кнопку — отвечу на все вопросы.",
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True
        )


@_fallback_router.callback_query()
async def handle_callback(call: types.CallbackQuery):

    # --- CHIMERA: счётчик страниц (просто глушим) ---
    if call.data == "chimera_noop":
        await call.answer()
        return

    # --- CHIMERA: обновить (сброс кеша) ---
    if call.data == "chimera_refresh":
        _signals_scan_cache.clear()
        await call.answer("Запускаю новый скан...", show_alert=False)
        await cmd_signals(call.message)
        return

    # --- CHIMERA: записать ставку по индексу кандидата ---
    if call.data.startswith("chimera_bet_"):
        try:
            parts = call.data.split("_")
            idx   = int(parts[2])
            units = int(parts[3]) if len(parts) > 3 else 1
        except (IndexError, ValueError):
            await call.answer("Ошибка формата", show_alert=True)
            return
        cached = _signals_scan_cache.get("last", {})
        candidates = cached.get("candidates", [])
        if not candidates or idx >= len(candidates):
            await call.answer("Данные устарели — обновите сигналы /signals", show_alert=True)
            return
        c = candidates[idx]
        sp     = c.get("sport", "football")
        home   = c.get("home", "")
        away   = c.get("away", "")
        odds   = c.get("odds", 0)
        t_str  = c.get("commence_time", "")
        rec    = "home_win" if c.get("team") == home else "away_win"
        mid    = f"chimera_{home}_{away}_{t_str[:10]}"
        # Ленивое сохранение в БД
        pred_id = c.get("_pred_id")
        if not pred_id:
            try:
                pred_id = save_prediction(
                    sport=sp, match_id=mid, match_date=t_str,
                    home_team=home, away_team=away,
                    league=c.get("league_name", sp),
                    recommended_outcome=rec, bet_signal="СТАВИТЬ",
                    bookmaker_odds_home=odds if rec == "home_win" else None,
                    bookmaker_odds_away=odds if rec == "away_win" else None,
                    ensemble_home=round(c.get("prob", 50) / 100, 3),
                    ensemble_away=round(1 - c.get("prob", 50) / 100, 3),
                    ensemble_best_outcome=rec,
                )
                if not pred_id:
                    from database import _get_db_connection
                    _tbl = {"football": "football_predictions", "cs2": "cs2_predictions",
                            "tennis": "tennis_predictions", "basketball": "basketball_predictions",
                            "hockey": "hockey_predictions"}.get(sp, "football_predictions")
                    with _get_db_connection() as _conn:
                        _row = _conn.execute(f"SELECT id FROM {_tbl} WHERE match_id=?", (mid,)).fetchone()
                        if _row:
                            pred_id = _row[0]
                c["_pred_id"] = pred_id
            except Exception as _e:
                # UNIQUE constraint — запись уже есть, ищем по match_id
                try:
                    from database import _get_db_connection
                    _tbl = {"football": "football_predictions", "cs2": "cs2_predictions",
                            "tennis": "tennis_predictions", "basketball": "basketball_predictions",
                            "hockey": "hockey_predictions"}.get(sp, "football_predictions")
                    with _get_db_connection() as _conn:
                        _row = _conn.execute(f"SELECT id FROM {_tbl} WHERE match_id=?", (mid,)).fetchone()
                        if _row:
                            pred_id = _row[0]
                            c["_pred_id"] = pred_id
                except Exception:
                    pass
                if not pred_id:
                    logger.error(f"[chimera_bet] Ошибка сохранения: {_e}")
        if not pred_id:
            await call.answer("Не удалось записать — попробуйте ещё раз", show_alert=True)
            return
        odds_enc = int(round(odds * 100))
        saved = mark_user_bet(call.from_user.id, sp, pred_id, odds, units)
        if saved:
            await call.answer("✅ Записано! Результат добавится автоматически после матча.", show_alert=True)
            # Заменяем кнопку на "уже записано"
            try:
                kb = _build_chimera_carousel_kb(candidates, idx, call.from_user.id)
                # Подменяем строку ставки
                new_rows = [kb.inline_keyboard[0], [types.InlineKeyboardButton(
                    text="📝 Ставка уже записана", callback_data="noop"
                )]]
                await call.message.edit_reply_markup(
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=new_rows)
                )
            except Exception as _e:
                logger.debug(f"[ignore] {_e}")
        else:
            await call.answer("Ты уже записал эту ставку.", show_alert=True)
        return

    # --- CHIMERA карусель ---
    if call.data.startswith("chimera_page_"):
        try:
            idx = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            await call.answer()
            return
        cached = _signals_scan_cache.get("last", {})
        candidates = cached.get("candidates", [])
        if not candidates or idx >= len(candidates):
            await call.answer("Данные устарели — нажмите /signals снова", show_alert=True)
            return
        _broll = get_user_bankroll(call.from_user.id) or 0
        text = _format_chimera_page(candidates, idx, bankroll=_broll)
        kb   = _build_chimera_carousel_kb(candidates, idx, call.from_user.id)
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")
        await call.answer()
        return

    # --- CS2 анализ матча ---
    if call.data.startswith("cs2_m_"):
        try:
            match_index = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            await call.answer("⚠️ Некорректные данные.", show_alert=True)
            return
        if match_index >= len(cs2_matches_cache):
            await call.answer("⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.", show_alert=True)
            return
        m = cs2_matches_cache[match_index]
        home_team = m["home"]
        away_team = m["away"]
        # Проверяем кеш готового отчёта (45 мин)
        import time as _time_cs2
        _cs2_cache_key = f"cs2_{match_index}"
        _cs2_cached = _report_cache.get(_cs2_cache_key)
        if _cs2_cached and _time_cs2.time() - _cs2_cached.get("ts", 0) < _REPORT_CACHE_TTL:
            await call.answer()
            await call.message.edit_text(
                _cs2_cached["text"], parse_mode=_cs2_cached.get("parse_mode"),
                reply_markup=_cs2_cached.get("kb"),
            )
            return
        status_msg = await call.message.edit_text(f"⏳ {home_team} vs {away_team}", parse_mode="HTML")
        await show_ai_thinking(status_msg, home_team, away_team, sport="cs2")
        try:
            from sports.cs2 import calculate_cs2_win_prob, get_golden_signal, format_cs2_full_report, run_cs2_analyst_agent
            from sports.cs2.pandascore import classify_tournament
            from signal_engine import check_cs2_signal, predict_cs2_totals, get_cs2_ranked_bets
            # Классифицируем турнир по данным матча
            _league = m.get("league", "")
            _tournament = m.get("tournament", "")
            _ctx = classify_tournament(_league, _tournament)
            analysis = calculate_cs2_win_prob(home_team, away_team, tournament_context=_ctx)
            analysis["home_team"] = home_team
            analysis["away_team"] = away_team
            odds = m.get("odds", {"home_win": 1.90, "away_win": 1.90})
            # Записываем снимок коэффициентов для отслеживания движения линий
            try:
                from line_movement import make_match_key, record_odds as _record_cs2_odds
                _cs2_lm_key = make_match_key(home_team, away_team, m.get("commence_time", ""))
                _record_cs2_odds(_cs2_lm_key, odds)
            except Exception as _e:
                logger.debug(f"[ignore] {_e}")
            golden_signals = get_golden_signal(analysis, odds)
            h_stats = analysis.get("home_stats", {})
            a_stats = analysis.get("away_stats", {})
            h2h = analysis.get("h2h", {})
            _h_si = analysis.get("home_standin", {})
            _a_si = analysis.get("away_standin", {})
            map_stats_for_ai = {mp: {"home_prob": round(hp, 2), "away_prob": round(ap, 2)} for mp, hp, ap in analysis.get("maps", [])}
            _data_conf = analysis.get("data_confidence", 1.0)
            gpt_text = run_cs2_analyst_agent(
                home_team, away_team, map_stats_for_ai, odds,
                agent_type="gpt-4o", home_stats=h_stats, away_stats=a_stats, h2h=h2h,
                tournament_context=_ctx, home_standin=_h_si, away_standin=_a_si,
                data_confidence=_data_conf,
            )
            llama_text = run_cs2_analyst_agent(
                home_team, away_team, map_stats_for_ai, odds,
                agent_type="llama-3.3", home_stats=h_stats, away_stats=a_stats, h2h=h2h,
                tournament_context=_ctx, home_standin=_h_si, away_standin=_a_si,
                data_confidence=_data_conf,
            )

            # Запускаем signal engine для показа пользователю
            h_players = analysis.get("home_players", [])
            a_players = analysis.get("away_players", [])
            h_avg_rating = sum(p['rating'] for p in h_players) / len(h_players) if h_players else 0
            a_avg_rating = sum(p['rating'] for p in a_players) / len(a_players) if a_players else 0
            predicted_maps = [mp for mp, _, _ in analysis.get("maps", [])]
            home_map_wr = {mp: hp for mp, hp, _ in analysis.get("maps", [])}
            away_map_wr = {mp: ap for mp, _, ap in analysis.get("maps", [])}
            ai_agrees = None
            if gpt_text and not gpt_text.startswith("❌") and home_team.lower() in gpt_text.lower():
                ai_agrees = True
            signal_checks = check_cs2_signal(
                home_team=home_team, away_team=away_team,
                home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
                bookmaker_odds=odds,
                home_form=h_stats.get("form", ""), away_form=a_stats.get("form", ""),
                elo_home=analysis.get("elo_home", 0), elo_away=analysis.get("elo_away", 0),
                mis_home=analysis["detail"].get("mis", 0), mis_away=1 - analysis["detail"].get("mis", 0),
                home_avg_rating=h_avg_rating, away_avg_rating=a_avg_rating,
                home_map_winrates=home_map_wr, away_map_winrates=away_map_wr,
                predicted_maps=predicted_maps,
                ai_cs2_agrees=ai_agrees,
            )

            # Тотал карт и раундов
            home_map_stats_raw = {mp: hp * 100 for mp, hp, _ in analysis.get("maps", [])}
            away_map_stats_raw = {mp: ap * 100 for mp, _, ap in analysis.get("maps", [])}
            totals_data = predict_cs2_totals(
                home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
                home_map_stats=home_map_stats_raw, away_map_stats=away_map_stats_raw,
                predicted_maps=predicted_maps,
            )
            # Расширенный тотал: карты + раунды первой карты
            try:
                from signal_engine import predict_cs2_round_totals
                round_totals = predict_cs2_round_totals(
                    home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
                    home_map_stats=home_map_stats_raw, away_map_stats=away_map_stats_raw,
                    predicted_maps=predicted_maps,
                )
                # Объединяем с totals_data
                if totals_data and round_totals:
                    totals_data["round_prediction"]   = round_totals["rounds_prediction"]
                    totals_data["round_confidence"]    = round_totals["rounds_confidence"]
                    totals_data["round_reason"]        = round_totals["rounds_reason"]
            except Exception as _rte:
                print(f"[CS2 Rounds] {_rte}")

            # Ранжированные ставки
            ranked_bets = get_cs2_ranked_bets(
                home_team=home_team, away_team=away_team,
                home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
                bookmaker_odds=odds,
                totals_data=totals_data,
                home_form=h_stats.get("form", ""),
                away_form=a_stats.get("form", ""),
            )

            # CHIMERA Multi-Agent
            _cs2_verdict_block = ""
            try:
                from sports.cs2.agents import run_cs2_chimera_agents
                _math_probs_cs2 = {"home": analysis.get("home_prob", 0.5), "away": analysis.get("away_prob", 0.5)}
                _chimera_cs2 = run_cs2_chimera_agents(
                    home_team, away_team, _math_probs_cs2, odds,
                    home_stats=h_stats, away_stats=a_stats, h2h=h2h,
                    tournament_context=_ctx, home_standin=_h_si, away_standin=_a_si,
                )
                _cs2_verdict_block = _chimera_cs2.get("verdict_block", "")
            except Exception as _ce:
                print(f"[CS2 Chimera] Ошибка агентов: {_ce}")

            # Экспертное мнение (Google News + Sport News Live)
            try:
                from expert_oracle import get_expert_consensus, format_expert_block
                _loop_cs2 = asyncio.get_running_loop()
                _exp_cs2 = await _loop_cs2.run_in_executor(
                    None, get_expert_consensus, home_team, away_team, "cs2"
                )
                _expert_block_cs2 = format_expert_block(_exp_cs2, home_team, away_team)
                if _expert_block_cs2:
                    _cs2_verdict_block = (_cs2_verdict_block + "\n\n" + _expert_block_cs2).strip()
                    print(f"[ExpertOracle CS2] {home_team} vs {away_team}: {_exp_cs2.get('sources_count')} источн.")
            except Exception as _ee_cs2:
                print(f"[ExpertOracle CS2] Ошибка: {_ee_cs2}")

            report = format_cs2_full_report(
                home_team, away_team, analysis, gpt_text, llama_text,
                golden_signals, bookmaker_odds=odds, signal_checks=signal_checks,
                ranked_bets=ranked_bets, totals_data=totals_data,
                chimera_verdict_block=_cs2_verdict_block,
                commence_time=m.get("commence_time"),
            )

            # ── Сохраняем прогноз в БД ────────────────────────────────────
            try:
                top_bet = ranked_bets[0] if ranked_bets else None
                rec_outcome = None
                if top_bet:
                    if top_bet["type"] == "П1":
                        rec_outcome = "home_win"
                    elif top_bet["type"] == "П2":
                        rec_outcome = "away_win"
                # Fallback: всегда заполняем recommended_outcome из ensemble
                if not rec_outcome:
                    rec_outcome = "home_win" if analysis["home_prob"] >= analysis["away_prob"] else "away_win"
                _cs2_home_odds = odds.get("home_win") or None
                _cs2_away_odds = odds.get("away_win") or None
                if not _cs2_home_odds:
                    logger.warning(f"[CS2 Save] Нет коэффициентов для {home_team} vs {away_team} — odds не будут сохранены")
                # Парсим структурированный verdict для CS2 (из текста агентов)
                def _cs2_parse_verdict(txt, ht, at):
                    if not txt or txt.startswith("❌"):
                        return ""
                    tl = txt.lower()
                    h_words = [w.lower() for w in ht.split() if len(w) > 3]
                    a_words = [w.lower() for w in at.split() if len(w) > 3]
                    h_score = sum(tl.count(w) for w in h_words)
                    a_score = sum(tl.count(w) for w in a_words)
                    if h_score > a_score: return "home_win"
                    if a_score > h_score: return "away_win"
                    return ""
                _cs2_gpt_verdict   = _cs2_parse_verdict(gpt_text,   home_team, away_team)
                _cs2_llama_verdict = _cs2_parse_verdict(llama_text, home_team, away_team)

                _cs2_pred_id = save_prediction(
                    sport="cs2",
                    match_id=str(m.get("id", f"{home_team}_{away_team}")),
                    match_date=m.get("commence_time") or m.get("time", ""),
                    home_team=home_team,
                    away_team=away_team,
                    league=m.get("league", "CS2"),
                    gpt_verdict=_cs2_gpt_verdict,
                    llama_verdict=_cs2_llama_verdict,
                    recommended_outcome=rec_outcome,
                    bet_signal="СТАВИТЬ" if signal_checks else "ПРОПУСТИТЬ",
                    elo_home=analysis.get("elo_home"),
                    elo_away=analysis.get("elo_away"),
                    elo_home_win=analysis["detail"].get("elo"),
                    elo_away_win=round(1 - analysis["detail"].get("elo", 0.5), 3),
                    ensemble_home=analysis["home_prob"],
                    ensemble_away=analysis["away_prob"],
                    ensemble_best_outcome="home_win" if analysis["home_prob"] >= analysis["away_prob"] else "away_win",
                    bookmaker_odds_home=_cs2_home_odds,
                    bookmaker_odds_away=_cs2_away_odds,
                    predicted_maps=predicted_maps,
                    prediction_data={
                        "total_prediction": totals_data.get("prediction") if totals_data else None,
                        "top_bet_type":  top_bet["type"]  if top_bet else None,
                        "top_bet_odds":  top_bet["odds"]  if top_bet else None,
                        "top_bet_ev":    top_bet["ev"]    if top_bet else None,
                        "signal_score":  signal_checks[0]["score"] if signal_checks else None,
                    }
                )
            except Exception as save_err:
                _cs2_pred_id = None
                print(f"[CS2 Save] Ошибка сохранения прогноза: {save_err}")
            try:
                upsert_user(call.from_user.id, call.from_user.username or "", call.from_user.first_name or "")
                track_analysis(call.from_user.id, "cs2")
                log_action(call.from_user.id, "анализ CS2")
            except Exception as _e:
                logger.debug(f"[ignore] {_e}")

            cs2_markets_kb = InlineKeyboardBuilder()
            cs2_markets_kb.button(text="🏆 Победитель матча", callback_data=f"cs2_mkt_winner_{match_index}")
            cs2_markets_kb.button(text="🗺️ По картам", callback_data=f"cs2_mkt_maps_{match_index}")
            cs2_markets_kb.button(text="🎯 Тотал раундов", callback_data=f"cs2_mkt_rounds_{match_index}")
            cs2_markets_kb.button(text="⬅️ Матчи", callback_data="back_to_cs2")
            cs2_markets_kb.button(text="🏠 Меню", callback_data="back_to_main")
            if _cs2_pred_id and ranked_bets:
                _cs2_bet_odds = ranked_bets[0].get("odds", 0) or odds.get("home_win" if rec_outcome == "home_win" else "away_win", 0) or 0
                _cs2_odds_enc = int(round(_cs2_bet_odds * 100))
                _cs2_kelly = ranked_bets[0].get("kelly", 2)
                _cs2_units = 3 if _cs2_kelly >= 4 else (2 if _cs2_kelly >= 2 else 1)
                cs2_markets_kb.button(
                    text=f"✅ Я поставил {_cs2_units}u — записать в статистику",
                    callback_data=f"mybet_cs2_{_cs2_pred_id}_{_cs2_odds_enc}_{_cs2_units}"
                )
            cs2_markets_kb.adjust(2)
            _cs2_kb = cs2_markets_kb.as_markup()
            report = _safe_truncate(report)
            try:
                await call.message.edit_text(report, parse_mode="Markdown", reply_markup=_cs2_kb)
            except Exception as _md_err:
                # Markdown сломан спецсимволом в названии — отправляем без форматирования
                logger.warning(f"[CS2 Markdown] Fallback plain text: {_md_err}")
                import re as _re
                plain_report = _re.sub(r'[*_`\[\]]', '', report)
                await call.message.edit_text(plain_report, parse_mode=None, reply_markup=_cs2_kb)
            import time as _time
            _report_cache[f"cs2_{match_index}"] = {
                "text": report, "kb": _cs2_kb,
                "parse_mode": "Markdown", "ts": _time.time(),
            }
        except Exception as e:
            logger.error(f"[CS2 анализ] Ошибка: {e}")
            import traceback; logger.error(traceback.format_exc())
            _fail_kb = InlineKeyboardBuilder()
            _fail_kb.button(text="🔄 Повторить", callback_data=call.data)
            _fail_kb.button(text="🏠 Меню", callback_data="back_to_main")
            _fail_kb.adjust(2)
            await call.message.edit_text(
                "😔 Произошёл сбой. Напиши нам в поддержку.",
                reply_markup=_fail_kb.as_markup()
            )

    # --- Выбор лиги CS2 ---
    elif call.data.startswith("cs2_league_"):
        league_name = call.data[11:]
        league_matches = [m for m in cs2_matches_cache if league_name.lower() in f"{m.get('league','')} {m.get('tournament','')}".lower()]
        
        if not league_matches:
            await call.answer("Матчи не найдены.", show_alert=True)
            return
            
        builder = InlineKeyboardBuilder()
        for m in league_matches:
            # Находим индекс в общем кэше
            idx = cs2_matches_cache.index(m)
            tier_icon = {"S": "🏆", "A": "🎯", "B": "🎮"}.get(m.get("tier", "B"), "🎮")
            label = f"{tier_icon} {m['home']} vs {m['away']} | {m['time']}"
            builder.button(text=label, callback_data=f"cs2_m_{idx}")
        builder.button(text="⬅️ Назад к лигам", callback_data="back_to_cs2_leagues")
        builder.adjust(1)
        
        await call.message.edit_text(
            f"🏆 *{league_name}* — матчи:\nВыберите матч для анализа:",
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )

    # --- Назад к списку лиг CS2 ---
    elif call.data == "back_to_cs2_leagues" or call.data == "back_to_cs2":
        if not cs2_matches_cache:
            await call.answer("⏰ Список устарел. Нажми ⬅️ Назад и открой лигу заново.", show_alert=True)
            return
            
        leagues = sorted(list(set([m.get('league', 'Other') for m in cs2_matches_cache])))
        # Пытаемся сопоставить с белым списком для красивых названий
        display_leagues = {}
        for m in cs2_matches_cache:
            full_name = f"{m.get('league','')} {m.get('tournament','')}".lower()
            for allowed in CS2_WHITELIST_LEAGUES:
                if allowed.lower() in full_name:
                    if allowed not in display_leagues:
                        display_leagues[allowed] = 0
                    display_leagues[allowed] += 1
                    break
        
        builder = InlineKeyboardBuilder()
        for league, count in sorted(display_leagues.items()):
            builder.button(text=f"🏆 {league} ({count})", callback_data=f"cs2_league_{league}")
        builder.adjust(1)
        
        await call.message.edit_text(
            f"🎮 *CS2* — Выберите лигу:",
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )



    # --- Выбор лиги ---
    elif call.data.startswith("league_"):
        league_key = call.data[7:]
        league_name = dict(FOOTBALL_LEAGUES).get(league_key, league_key)
        await call.answer()
        # Пробуем кеш (20 мин TTL из odds_cache) — без force, чтобы не блокировать
        _loop_lg = asyncio.get_running_loop()
        matches = await _loop_lg.run_in_executor(None, lambda: get_matches(league=league_key, force=False))
        if not matches:
            # Кеш пустой — грузим с API, показываем индикатор
            await call.message.edit_text(f"⚽ *{league_name}*\n\n⏳ Загружаю матчи...", parse_mode="Markdown")
            try:
                matches = await asyncio.wait_for(
                    _loop_lg.run_in_executor(None, lambda: get_matches(league=league_key, force=True)),
                    timeout=20.0
                )
            except asyncio.TimeoutError:
                _err_kb = InlineKeyboardBuilder()
                _err_kb.button(text="🔄 Повторить", callback_data=f"league_{league_key}")
                _err_kb.button(text="⬅️ Лиги", callback_data="football")
                _err_kb.adjust(2)
                await call.message.edit_text(
                    f"⚽ <b>{league_name}</b>\n\n⚠️ API не отвечает. Попробуй ещё раз.",
                    parse_mode="HTML", reply_markup=_err_kb.as_markup()
                )
                return
        if not matches:
            _empty_kb = InlineKeyboardBuilder()
            _empty_kb.button(text="🔄 Обновить", callback_data=f"league_{league_key}")
            _empty_kb.button(text="⬅️ Лиги", callback_data="football")
            _empty_kb.adjust(2)
            await call.message.edit_text(
                f"⚽ <b>{league_name}</b>\n\n❌ Матчей пока нет. Попробуй через 5 минут.",
                parse_mode="HTML", reply_markup=_empty_kb.as_markup()
            )
            return
        await call.message.edit_text(
            f"⚽ *{league_name}*\n\nВыберите матч для анализа:",
            parse_mode="Markdown",
            reply_markup=build_matches_keyboard(matches)
        )

    # --- Сменить лигу ---
    elif call.data == "change_league":
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "АПЛ")
        await call.message.edit_text(
            f"⚽ *Футбол* — выбери лигу:\nТекущая: *{league_name}*",
            parse_mode="Markdown",
            reply_markup=build_football_keyboard()
        )

    # --- Быстрый возврат к анализу матча из кэша ---
    elif call.data.startswith("back_to_report_"):
        import time as _time
        # Формат: back_to_report_{sport}_{key...}
        # football_{idx} | cs2_{idx} | tennis_{sport_key}_{idx} | bball_{league}_{idx}
        suffix = call.data[len("back_to_report_"):]  # e.g. "football_3" or "tennis_atp_2"
        cached_report = _report_cache.get(suffix)
        if cached_report and _time.time() - cached_report.get("ts", 0) < _REPORT_CACHE_TTL:
            await call.answer()
            await call.message.edit_text(
                cached_report["text"],
                parse_mode=cached_report["parse_mode"],
                reply_markup=cached_report["kb"],
            )
        else:
            # Кэш устарел — предупреждаем и предлагаем пересчитать
            await call.answer("⏰ Анализ устарел (>45 мин). Открой матч заново.", show_alert=True)

    # --- Обновление статистики (сброс кеша) ---
    elif call.data == "stats_refresh":
        await call.answer("🔄 Обновляю...", show_alert=False)
        invalidate_stats_cache()
        # Пересчитываем и редактируем сообщение
        _loop_sr = asyncio.get_running_loop()
        _fresh_stats = await _loop_sr.run_in_executor(None, get_statistics)
        _fresh_chimera = get_chimera_signal_history(limit=10)

        def _acc_bar_r(acc):
            filled = round(acc / 10)
            return "▓" * filled + "░" * (10 - filled)

        _main_sports_r = ("football", "tennis", "basketball", "hockey")
        all_total   = sum(_fresh_stats.get(k, {}).get("total", 0)         for k in _main_sports_r)
        all_checked = sum(_fresh_stats.get(k, {}).get("total_checked", 0) for k in _main_sports_r)
        all_correct = sum(_fresh_stats.get(k, {}).get("correct", 0)       for k in _main_sports_r)
        all_acc     = round(all_correct / all_checked * 100, 1) if all_checked > 0 else 0

        txt = "📊 *Статистика Chimera AI*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if all_checked > 0:
            txt += (
                f"🎯 *Общий бот (без CS2):* *{all_correct} из {all_checked}*\n"
                f"`{_acc_bar_r(all_acc)}` *{all_acc}%*\n"
                f"📋 Всего: *{all_total}* | Ожидают: *{all_total - all_checked}*\n"
            )
        txt += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        _sl = [("football","⚽ Футбол"),("cs2","🎮 CS2 _(бета)_"),("tennis","🎾 Теннис"),("basketball","🏀 Баскетбол"),("hockey","🏒 Хоккей")]
        _sl.sort(key=lambda x: _fresh_stats.get(x[0], {}).get("accuracy", 0), reverse=True)
        for sport_key, sport_label in _sl:
            s = _fresh_stats.get(sport_key, {})
            if not s.get("total"): continue
            checked = s.get("total_checked", 0)
            correct = s.get("correct", 0)
            acc     = s.get("accuracy", 0)
            pending = s.get("total", 0) - checked
            recent_icons = ["✅" if r.get("is_correct") == 1 else "❌"
                            for r in s.get("recent", []) if r.get("is_correct") in (0, 1)][:5]
            txt += f"*{sport_label}*\n"
            if checked > 0:
                txt += f"`{_acc_bar_r(acc)}` *{acc:.0f}%* — *{correct}/{checked}*"
                if pending: txt += f"  ⏳ *{pending}*"
                txt += "\n"
            else:
                txt += f"⏳ Ожидают результата: *{s.get('total',0)}*\n"
            if recent_icons:
                txt += f"Последние: {''.join(recent_icons)}\n"
            txt += "\n"

        if _fresh_chimera:
            ch_checked = [r for r in _fresh_chimera if r["is_correct"] is not None]
            ch_wins = sum(1 for r in ch_checked if r["is_correct"] == 1)
            ch_acc  = round(ch_wins / len(ch_checked) * 100) if ch_checked else 0
            txt += "━━━━━━━━━━━━━━━━━━━━━━━━━\n*🎯 Сигналы дня*\n"
            if ch_checked:
                txt += f"`{_acc_bar_r(ch_acc)}` *{ch_acc}%* — *{ch_wins}/{len(ch_checked)}*\n"
            done_icons = ["✅" if r["is_correct"] == 1 else "❌"
                          for r in _fresh_chimera if r["is_correct"] in (0,1)][:5]
            if done_icons:
                txt += f"Последние: {''.join(done_icons)}\n"

        _ref_kb = InlineKeyboardBuilder()
        _ref_kb.button(text="🔄 Обновить", callback_data="stats_refresh")
        _ref_kb.button(text="🏠 Меню", callback_data="back_to_main")
        _ref_kb.adjust(2)
        try:
            await call.message.edit_text(txt, parse_mode="Markdown", reply_markup=_ref_kb.as_markup())
        except Exception as _e:
            logger.debug(f"[stats_refresh] {_e}")

    # --- Возврат к списку матчей ---
    elif call.data == "back_to_main":
        lang = "ru"
        try:
            lang = get_user_language(call.from_user.id)
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")
        try:
            await call.message.delete()
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")
        await call.message.answer(
            "🏠 <b>Главное меню</b>",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(lang),
        )

    elif call.data == "back_to_matches":
        if not matches_cache:
            get_matches()
        await call.message.edit_text("Выберите матч для анализа:", reply_markup=build_matches_keyboard(matches_cache, page=0))

    # --- Пагинация матчей ---
    elif call.data.startswith("matches_page_"):
        try:
            pg = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            pg = 0
        if not matches_cache:
            get_matches()
        await call.answer()
        total = len(matches_cache)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "Матчи")
        await call.message.edit_text(
            f"⚽ <b>{league_name}</b> — {total} матчей (стр. {pg+1}/{total_pages})\nВыберите матч:",
            parse_mode="HTML",
            reply_markup=build_matches_keyboard(matches_cache, page=pg)
        )

    # --- Обновление матчей ---
    elif call.data == "refresh_matches":
        await call.answer("🔄 Обновляю...")
        _loop_rm = asyncio.get_running_loop()
        try:
            matches = await asyncio.wait_for(
                _loop_rm.run_in_executor(None, lambda: get_matches(force=True)),
                timeout=20.0
            )
        except asyncio.TimeoutError:
            await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.", reply_markup=build_matches_keyboard(matches_cache))
            return
        if not matches:
            await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.", reply_markup=build_matches_keyboard(matches_cache))
            return
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "")
        await call.message.edit_text(
            f"✅ Список обновлён! {league_name}: {len(matches)} матчей.",
            reply_markup=build_matches_keyboard(matches)
        )

    # --- Показать меню рынков ---
    elif call.data.startswith("show_markets_"):
        try:
            match_index = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            await call.answer("⚠️ Некорректные данные.", show_alert=True)
            return
        if match_index >= len(matches_cache):
            await call.answer("⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.", show_alert=True)
            return
        match = matches_cache[match_index]
        home_team = match["home_team"]
        away_team = match["away_team"]

        cached = analysis_cache.get(match_index, {})
        if cached:
            report = format_main_report(
                home_team, away_team,
                cached["prophet_data"], cached["oracle_results"],
                cached["gpt_result"], cached["llama_result"],
                mixtral_result=cached.get("mixtral_result"),
                poisson_probs=cached.get("poisson_probs"),
                elo_probs=cached.get("elo_probs"),
                ensemble_probs=cached.get("ensemble_probs"),
                home_xg_stats=cached.get("home_xg_stats"),
                away_xg_stats=cached.get("away_xg_stats"),
                value_bets=cached.get("value_bets"),
                injuries_block=cached.get("injuries_block"),
                match_time=match.get('commence_time', ''),
                bookmaker_odds=cached.get("bookmaker_odds"),
            )
            await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_markets_keyboard(match_index))

    # --- Выбор матча для анализа ---
    elif call.data.startswith("m_"):
        try:
            match_index = int(call.data.split("_")[1])
        except (IndexError, ValueError):
            await call.answer("⚠️ Некорректные данные.", show_alert=True)
            return
        if match_index >= len(matches_cache):
            await call.answer("⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.", show_alert=True)
            return

        match = matches_cache[match_index]
        home_team = match["home_team"]
        away_team = match["away_team"]

        # Проверяем кеш готового отчёта (45 мин)
        import time as _time_fb
        _fb_cache_key = f"football_{match_index}"
        _fb_cached = _report_cache.get(_fb_cache_key)
        if _fb_cached and _time_fb.time() - _fb_cached.get("ts", 0) < _REPORT_CACHE_TTL:
            await call.answer()
            await call.message.edit_text(
                _fb_cached["text"], parse_mode=_fb_cached.get("parse_mode"),
                reply_markup=_fb_cached.get("kb"),
            )
            return

        _base = f"<b>⚽ {home_team}  <code>vs</code>  {away_team}</b>\n<b>🔮 CHIMERA AI</b> — запускаю анализ...\n\n"
        _sm = await call.message.edit_text(_base + "🔮 <b>Пророк:</b> нейросеть считает вероятности...", parse_mode="HTML")

        prophet_data = get_prophet_prediction(home_team, away_team)
        oracle_results = oracle_analyze(home_team, away_team)
        home_news = oracle_results.get(home_team, {})
        away_news = oracle_results.get(away_team, {})
        news_summary = (
            f"Новости {home_team}: настроение {home_news.get('sentiment', 0):.2f}, "
            f"найдено {home_news.get('news_count', 0)} статей.\n"
            f"Новости {away_team}: настроение {away_news.get('sentiment', 0):.2f}, "
            f"найдено {away_news.get('news_count', 0)} статей."
        )

        try:
            await _sm.edit_text(
                _base +
                "🔮 <b>Пророк:</b> <i>готово ✓</i>\n"
                "🦁 <b>Лев:</b> <i>готово ✓</i>\n"
                "🐍 <b>Змея:</b> считает ELO, Пуассон, xG...",
                parse_mode="HTML"
            )
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")

        bookmaker_odds = get_bookmaker_odds(match)

        # Получаем реальную статистику команд из API-Football
        team_stats_text = get_match_stats(home_team, away_team)
        if team_stats_text:
            print(f"[API-Football] Статистика получена для {home_team} vs {away_team}")
        else:
            print(f"[API-Football] Статистика недоступна для {home_team} vs {away_team}")

        # Получаем xG статистику из Understat → fallback на API-Football
        xg_stats_text = ""
        home_xg_stats = None
        away_xg_stats = None
        if UNDERSTAT_AVAILABLE:
            try:
                home_xg_stats = get_team_xg_stats(home_team)
                away_xg_stats = get_team_xg_stats(away_team)
                xg_stats_text = format_xg_stats(home_team, away_team)
                if xg_stats_text:
                    print(f"[Understat] xG статистика получена для {home_team} vs {away_team}")
                    if team_stats_text:
                        team_stats_text = team_stats_text + "\n\n" + xg_stats_text
                    else:
                        team_stats_text = xg_stats_text
            except Exception as _xe:
                print(f"[Understat] Недоступен: {_xe}")
        # Fallback: если Understat дал пустые данные — берём avg_goals из API-Football
        if not home_xg_stats and API_FOOTBALL_KEY:
            try:
                from api_football import get_team_stats as _get_tf_stats
                _hf = _get_tf_stats(home_team)
                _af = _get_tf_stats(away_team)
                if _hf:
                    home_xg_stats = {
                        "avg_xg_last5": _hf.get("goals_scored_avg", 1.35),
                        "avg_xg_against_last5": _hf.get("goals_conceded_avg", 1.1),
                    }
                if _af:
                    away_xg_stats = {
                        "avg_xg_last5": _af.get("goals_scored_avg", 1.1),
                        "avg_xg_against_last5": _af.get("goals_conceded_avg", 1.35),
                    }
                if _hf or _af:
                    print(f"[Understat→API-Football] Fallback xG: {home_team}={home_xg_stats}, {away_team}={away_xg_stats}")
            except Exception as _fb:
                print(f"[Understat fallback] API-Football тоже недоступен: {_fb}")

        # Пуассон + ELO математические модели
        poisson_probs = None
        elo_probs = None
        try:
            # ELO рейтинги + форма
            elo_probs = elo_win_probabilities(home_team, away_team, _elo_ratings, _team_form)
            print(f"[ELO] {home_team}={elo_probs['home_elo']}({elo_probs.get('home_form','?')}) vs {away_team}={elo_probs['away_elo']}({elo_probs.get('away_form','?')})")
            print(f"[ELO] Форма-бонус: {home_team}={elo_probs.get('home_form_bonus',0):+.0f} | {away_team}={elo_probs.get('away_form_bonus',0):+.0f}")
        except Exception as _ee:
            print(f"[ELO] Ошибка: {_ee}")

        xg_data_source = "fallback"  # Источник данных для Пуассона
        try:
            # Пуассон на основе xG
            if home_xg_stats and away_xg_stats:
                home_exp, away_exp = calculate_expected_goals(home_xg_stats, away_xg_stats)
                xg_data_source = "understat"  # Реальные данные из Understat
                print(f"[Understat] ✅ Реальные xG: {home_team}={home_xg_stats.get('avg_xg_last5','?')}, {away_team}={away_xg_stats.get('avg_xg_last5','?')}")
            elif home_xg_stats and not away_xg_stats:
                # Есть данные только для хозяев
                home_exp = home_xg_stats.get('avg_xg_last5', 1.35)
                away_exp = 1.10
                xg_data_source = "partial"  # Частичные данные
                print(f"[Understat] ⚠️ Частичные xG: есть данные только для {home_team}")
            elif not home_xg_stats and away_xg_stats:
                # Есть данные только для гостей
                home_exp = 1.35
                away_exp = away_xg_stats.get('avg_xg_last5', 1.10)
                xg_data_source = "partial"  # Частичные данные
                print(f"[Understat] ⚠️ Частичные xG: есть данные только для {away_team}")
            else:
                # Нет данных — среднелиговые значения
                home_exp, away_exp = 1.35, 1.10
                xg_data_source = "fallback"  # Резервные значения
                print(f"[Understat] ❌ Данных нет — использую среднелиговые ({home_exp}/{away_exp})")
            poisson_probs = poisson_match_probabilities(home_exp, away_exp)
            # Добавляем источник данных в poisson_probs
            poisson_probs['data_source'] = xg_data_source
            poisson_probs['home_exp'] = round(home_exp, 2)
            poisson_probs['away_exp'] = round(away_exp, 2)
            print(f"[Пуассон] xG хозяев={home_exp:.2f}, гостей={away_exp:.2f} (источник: {xg_data_source})")
        except Exception as _pe:
            print(f"[Пуассон] Ошибка: {_pe}")

        # ── Dixon-Coles (до ансамбля!) ────────────────────────────────────
        # Запускаем здесь, чтобы его вероятности ВОШЛИ в ансамбль
        _ml_block = ""
        try:
            from ml.predictor import get_football_prediction, format_ml_block as _fmt_ml
            _h_elo = elo_probs.get("home_elo", 1500) if elo_probs else 1500
            _a_elo = elo_probs.get("away_elo", 1500) if elo_probs else 1500
            _ml_pred = get_football_prediction(
                home_team, away_team, bookmaker_odds,
                home_elo=_h_elo, away_elo=_a_elo,
            )
            _ml_block = _fmt_ml(_ml_pred, home_team, away_team)
            if _ml_pred.get("model_used") == "Dixon-Coles":
                print(f"[DC] ✅ П1={round(_ml_pred['home_win']*100)}% "
                      f"| Х={round(_ml_pred['draw']*100)}% | П2={round(_ml_pred['away_win']*100)}%")
            else:
                print(f"[ML] {_ml_pred.get('model_used','?')} — Dixon-Coles не знает эти команды")
        except Exception as _mle:
            print(f"[ML] Ошибка Dixon-Coles: {_mle}")

        # Травмы и дисквалификации
        home_injuries = {}
        away_injuries = {}
        injuries_block = ""
        try:
            home_injuries, away_injuries, injuries_block = await get_match_injuries_async(home_team, away_team)
            # Добавляем данные о травмах в контекст для AI агентов
            if injuries_block:
                injuries_context = (
                    f"\n\n{injuries_block.replace('*', '')}"
                )
                if team_stats_text:
                    team_stats_text = team_stats_text + injuries_context
                else:
                    team_stats_text = injuries_context
        except Exception as _inj_e:
            print(f"[Травмы] Ошибка: {_inj_e}")

        _loop = asyncio.get_running_loop()
        _form_h = get_form_string(home_team, _team_form)
        _form_a = get_form_string(away_team, _team_form)
        _cb_openai = get_breaker("openai", max_failures=3, recovery_timeout=300)
        async with _ai_semaphore:
            try:
                stats_result, scout_result = await asyncio.wait_for(
                    asyncio.gather(
                        _loop.run_in_executor(None, lambda: run_statistician_agent(
                            prophet_data, team_stats_text,
                            poisson_probs=poisson_probs, elo_probs=elo_probs,
                            home_form=_form_h, away_form=_form_a,
                        )),
                        _loop.run_in_executor(None, run_scout_agent, home_team, away_team, news_summary),
                    ),
                    timeout=90.0
                )
                if not stats_result.get("error") and not scout_result.get("error"):
                    _cb_openai.record_success()
                else:
                    _cb_openai.record_failure()
            except asyncio.TimeoutError:
                stats_result = {"error": "Таймаут агента Статистик/Скаут (>90с)"}
                scout_result = {"error": "Таймаут агента Статистик/Скаут (>90с)"}
                _cb_openai.record_failure()
                print("[AI Таймаут] Статистик/Скаут не ответили за 90с")
            try:
                gpt_result = await asyncio.wait_for(
                    _loop.run_in_executor(None, lambda: run_arbitrator_agent(
                        stats_result, scout_result, bookmaker_odds,
                        poisson_probs=poisson_probs, elo_probs=elo_probs,
                    )),
                    timeout=90.0
                )
                if not gpt_result.get("error"):
                    _cb_openai.record_success()
            except asyncio.TimeoutError:
                gpt_result = {"error": "Таймаут агента Арбитр (>90с)", "bet_signal": "ПРОПУСТИТЬ"}
                _cb_openai.record_failure()
                print("[AI Таймаут] Арбитр не ответил за 90с")

        try:
            await _sm.edit_text(
                _base +
                "🔮 <b>Пророк:</b> <i>готово ✓</i>\n"
                "🦁 <b>Лев:</b> <i>готово ✓</i>\n"
                "🐍 <b>Змея:</b> <i>готово ✓</i>\n"
                "🐐 <b>Козёл:</b> <i>готово ✓</i>\n"
                "🌀 <b>Тень:</b> независимая проверка...",
                parse_mode="HTML"
            )
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")

        _cb_groq = get_breaker("groq", max_failures=3, recovery_timeout=300)
        async with _ai_semaphore:
            try:
                llama_result, mixtral_result = await asyncio.wait_for(
                    asyncio.gather(
                        _loop.run_in_executor(None, lambda: run_llama_agent(
                            home_team, away_team, prophet_data, news_summary, bookmaker_odds,
                            team_stats_text, poisson_probs=poisson_probs, elo_probs=elo_probs,
                        )),
                        _loop.run_in_executor(None, run_mixtral_agent, home_team, away_team, prophet_data, news_summary, bookmaker_odds, team_stats_text, poisson_probs, elo_probs),
                    ),
                    timeout=90.0
                )
                if not llama_result.get("error"):
                    _cb_groq.record_success()
                else:
                    _cb_groq.record_failure()
            except asyncio.TimeoutError:
                llama_result = {"error": "Таймаут агента Тень/Mixtral (>90с)"}
                mixtral_result = {"error": "Таймаут агента Тень/Mixtral (>90с)"}
                _cb_groq.record_failure()
                print("[AI Таймаут] Тень/Mixtral не ответили за 90с")

        # Взвешенный ансамбль всех моделей
        ensemble_probs = None
        value_bets = []
        try:
            ensemble_probs = build_math_ensemble(
                prophet_data, poisson_probs, elo_probs,
                gpt_result, llama_result, mixtral_result,
                bookmaker_odds,
                dc_probs=_ml_pred if _ml_pred.get("model_used") == "Dixon-Coles" else None,
            )
            # Ищем value bets
            odds_for_value = {
                'home': bookmaker_odds.get('home_win', 0),
                'draw': bookmaker_odds.get('draw', 0),
                'away': bookmaker_odds.get('away_win', 0),
            }
            value_bets = calculate_value_bets(ensemble_probs, odds_for_value)
            print(f"[Ансамбль] П1={round(ensemble_probs['home']*100)}% | Х={round(ensemble_probs['draw']*100)}% | П2={round(ensemble_probs['away']*100)}%")
            if value_bets:
                print(f"[Value Bets] Найдено: {len(value_bets)} ставок с EV>5%")
        except Exception as _ense:
            print(f"[Ансамбль] Ошибка: {_ense}")

        # ── Сигналы от полного ансамбля с AI ─────────────────────────────
        football_ai_signals = []
        try:
            # Защита: агенты должны возвращать dict, но на случай ошибки
            if not isinstance(gpt_result, dict):
                gpt_result = {}
            if not isinstance(llama_result, dict):
                llama_result = {}
            if not isinstance(mixtral_result, dict):
                mixtral_result = {}
            # Определяем согласен ли AI ставить
            gpt_bet_signal = gpt_result.get("bet_signal", "")
            llama_outcome  = llama_result.get("recommended_outcome", "")
            gpt_outcome    = gpt_result.get("recommended_outcome", "")
            _valid_outcomes = ("home_win", "away_win", "draw")
            _gpt_out   = gpt_result.get("recommended_outcome", "")
            _llama_out = llama_result.get("recommended_outcome", "")
            if _gpt_out in _valid_outcomes and _llama_out in _valid_outcomes:
                # Оба агента дали чёткий вердикт
                if _gpt_out == _llama_out:
                    ai_agrees_flag = True   # полное согласие
                else:
                    ai_agrees_flag = False  # явное расхождение — красный флаг
            elif _gpt_out in _valid_outcomes or _llama_out in _valid_outcomes:
                ai_agrees_flag = None   # один агент не определился — нейтрально
            else:
                ai_agrees_flag = None   # нет данных

            # Используем ансамблевые вероятности если есть, иначе ELO
            sig_probs = ensemble_probs or elo_probs or {}
            h_sig = sig_probs.get("home", 0.34)
            d_sig = sig_probs.get("draw", 0.33)
            a_sig = sig_probs.get("away", 0.33)

            elo_h = _elo_ratings.get(home_team, 1500)
            elo_a = _elo_ratings.get(away_team, 1500)
            form_h = get_form_string(home_team, _team_form)
            form_a = get_form_string(away_team, _team_form)

            football_ai_signals = check_football_signal(
                home_team=home_team,
                away_team=away_team,
                home_prob=h_sig,
                away_prob=a_sig,
                draw_prob=d_sig,
                bookmaker_odds=bookmaker_odds,
                home_form=form_h,
                away_form=form_a,
                elo_home=elo_h,
                elo_away=elo_a,
                ai_agrees=ai_agrees_flag,
            )
            if football_ai_signals:
                print(f"[AI Сигнал ⚽] Найдено: {len(football_ai_signals)} сигналов с ансамблем")

            # Сигнал на ничью
            _draw_odds = bookmaker_odds.get("draw") or bookmaker_odds.get("draw_win") or 0.0
            if not _draw_odds:
                try:
                    _draw_odds = float(match.get("bookmakers", [{}])[0].get("markets", [{}])[0].get("outcomes", [{}])[1].get("price", 0) or 0)
                except Exception:
                    _draw_odds = 0.0
            draw_signal = check_draw_signal(home_team, away_team, h_sig, a_sig, _draw_odds)
            if draw_signal:
                football_ai_signals = list(football_ai_signals) + [draw_signal]
                print(f"[Ничья ⚽] {draw_signal['tier']} | EV={draw_signal['ev']:+.1f}% | odds={_draw_odds}")
        except Exception as _sig_e:
            print(f"[AI Сигнал] Ошибка: {_sig_e}")
            draw_signal = None

        # Сохраняем в кэш для повторного использования при выборе рынков
        analysis_cache[match_index] = {
            "prophet_data": prophet_data,
            "oracle_results": oracle_results,
            "news_summary": news_summary,
            "bookmaker_odds": bookmaker_odds,
            "gpt_result": gpt_result,
            "llama_result": llama_result,
            "mixtral_result": mixtral_result,
            "poisson_probs": poisson_probs,
            "elo_probs": elo_probs,
            "ensemble_probs": ensemble_probs,
            "home_xg_stats": home_xg_stats,
            "away_xg_stats": away_xg_stats,
            "value_bets": value_bets,
            "home_team": home_team,
            "away_team": away_team,
            "match": match,
            "team_stats_text": team_stats_text,
            "injuries_block": injuries_block,
            "home_injuries": home_injuries,
            "away_injuries": away_injuries,
        }

        # Сохранение в базу данных
        # Определяем лучший исход — из ансамбля, fallback на ELO, fallback на Poisson
        _probs_for_rec = (
            ensemble_probs or
            ({"home": elo_probs.get("home", 0), "draw": elo_probs.get("draw", 0), "away": elo_probs.get("away", 0)} if elo_probs else None) or
            ({"home": poisson_probs.get("home_win", 0), "draw": poisson_probs.get("draw", 0), "away": poisson_probs.get("away_win", 0)} if poisson_probs else None)
        )
        ens_best_key = max(['home', 'draw', 'away'], key=lambda k: (_probs_for_rec or {}).get(k, 0)) if _probs_for_rec else "home"
        ens_best_map = {'home': home_team, 'draw': 'Ничья', 'away': away_team}
        ens_best_label = ens_best_map.get(ens_best_key, home_team)

        # Используем реальный bet_signal из football_ai_signals (не из GPT-ответа)
        _fb_bet_signal = "СТАВИТЬ" if football_ai_signals else "НЕ СТАВИТЬ"
        prediction_data = {
            "gpt_verdict": gpt_result.get("recommended_outcome", ""),
            "llama_verdict": llama_result.get("recommended_outcome", ""),
            "mixtral_verdict": (mixtral_result or {}).get("recommended_outcome", ""),
            "gpt_confidence": gpt_result.get("final_confidence_percent", 0),
            "llama_confidence": llama_result.get("final_confidence_percent", 0),
            "mixtral_confidence": (mixtral_result or {}).get("final_confidence_percent", 0),
            "bet_signal": _fb_bet_signal,
            "total_goals": llama_result.get("total_goals_prediction", ""),
            "btts": llama_result.get("both_teams_to_score_prediction", ""),
            "odds_home": bookmaker_odds.get("home_win") or None,
            "odds_draw": bookmaker_odds.get("draw") or None,
            "odds_away": bookmaker_odds.get("away_win") or None,
            "odds_over25": bookmaker_odds.get("over_2_5") or None,
            "odds_under25": bookmaker_odds.get("under_2_5") or None,
            # Математические модели
            "poisson_probs": poisson_probs,
            "elo_probs": elo_probs,
            "ensemble_probs": ensemble_probs,
            "ensemble_best_outcome": ens_best_label,
            "value_bets": value_bets,
            "league": match.get('sport_key', 'soccer_epl'),
        }
        try:
            _football_pred_id = save_prediction(
                sport='football',
                match_id=str(match['id']),
                match_date=match.get('commence_time', ''),
                home_team=home_team,
                away_team=away_team,
                league=match.get('sport_key', 'soccer_epl'),
                gpt_verdict=prediction_data.get('gpt_verdict'),
                llama_verdict=prediction_data.get('llama_verdict'),
                gpt_confidence=prediction_data.get('gpt_confidence'),
                llama_confidence=prediction_data.get('llama_confidence'),
                bet_signal=prediction_data.get('bet_signal'),
                total_goals_prediction=prediction_data.get('total_goals'),
                btts_prediction=prediction_data.get('btts'),
                bookmaker_odds_home=prediction_data.get('odds_home'),
                bookmaker_odds_draw=prediction_data.get('odds_draw'),
                bookmaker_odds_away=prediction_data.get('odds_away'),
                bookmaker_odds_over25=prediction_data.get('odds_over25'),
                bookmaker_odds_under25=prediction_data.get('odds_under25'),
                ensemble_home=(ensemble_probs or {}).get('home'),
                ensemble_draw=(ensemble_probs or {}).get('draw'),
                ensemble_away=(ensemble_probs or {}).get('away'),
                ensemble_best_outcome=ens_best_label,
                recommended_outcome={'home': 'home_win', 'draw': 'draw', 'away': 'away_win'}.get(ens_best_key, 'home_win'),
                prediction_data=prediction_data,
            )
        except Exception as _save_err:
            _football_pred_id = None
            print(f"[DB Save] Ошибка сохранения футбол: {_save_err}")

        # Трекинг активности пользователя
        try:
            upsert_user(call.from_user.id, call.from_user.username or "", call.from_user.first_name or "")
            track_analysis(call.from_user.id, "football")
            log_action(call.from_user.id, "анализ Футбол")
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")

        # CHIMERA Multi-Agent
        _football_chimera_block = ""
        try:
            from agents import run_football_chimera_agents
            _fc = run_football_chimera_agents(
                home_team, away_team,
                ensemble_probs or elo_probs or {},
                bookmaker_odds,
                news_summary=news_summary,
                stats_text=team_stats_text or "",
                gpt_summary=gpt_result.get("final_verdict_summary", "") if gpt_result else "",
                llama_summary=llama_result.get("analysis_summary", "") if llama_result else "",
            )
            _football_chimera_block = _fc.get("verdict_block", "")
        except Exception as _fce:
            print(f"[Football CHIMERA] Ошибка: {_fce}")

        # Экспертное мнение (Google News + AI-сводка)
        _expert_block = ""
        try:
            from expert_oracle import get_expert_consensus, format_expert_block
            _loop2 = asyncio.get_running_loop()
            _exp = await _loop2.run_in_executor(
                None, get_expert_consensus, home_team, away_team, "football"
            )
            _expert_block = format_expert_block(_exp, home_team, away_team)
            if _expert_block:
                print(f"[ExpertOracle] {home_team} vs {away_team}: консенсус={_exp.get('consensus')} ({_exp.get('sources_count')} источн.)")
        except Exception as _ee2:
            print(f"[ExpertOracle] Ошибка: {_ee2}")

        # Добавляем экспертный блок к chimera-вердикту если есть
        if _expert_block:
            _football_chimera_block = (_football_chimera_block + "\n\n" + _expert_block).strip()

        # Движение линий — записываем снимок и получаем блок (передаём в отчёт отдельно, не в chimera-блок)
        _movement_block = ""
        try:
            from line_movement import make_match_key, record_odds, get_movement, format_movement_block
            _lm_key = make_match_key(home_team, away_team, match.get("commence_time", ""))
            record_odds(_lm_key, bookmaker_odds)
            _movement = get_movement(_lm_key, bookmaker_odds)
            _movement_block = format_movement_block(_movement) or ""
        except Exception as _lme:
            logger.debug(f"[ignore] {_lme}")

        final_report = format_main_report(
            home_team, away_team,
            prophet_data, oracle_results,
            gpt_result, llama_result,
            mixtral_result=mixtral_result,
            poisson_probs=poisson_probs,
            elo_probs=elo_probs,
            ensemble_probs=ensemble_probs,
            home_xg_stats=home_xg_stats,
            away_xg_stats=away_xg_stats,
            value_bets=value_bets,
            injuries_block=injuries_block,
            match_time=match.get('commence_time', ''),
            chimera_verdict_block=_football_chimera_block,
            ml_block=_ml_block,
            bookmaker_odds=bookmaker_odds,
            movement_block=_movement_block,
        )

        _football_kb = build_markets_keyboard(match_index)
        final_report = _safe_truncate(final_report)
        await call.message.edit_text(
            final_report,
            parse_mode="Markdown",
            reply_markup=_football_kb,
        )
        # Сохраняем в report_cache для быстрого возврата
        import time as _time
        _report_cache[f"football_{match_index}"] = {
            "text": final_report, "kb": _football_kb,
            "parse_mode": "Markdown", "ts": _time.time(),
        }

        # Отправляем AI-сигнал отдельным сообщением если есть
        if football_ai_signals:
            # Сортируем по EV — лучший сигнал первым (ничья или П1/П2)
            football_ai_signals.sort(key=lambda s: s.get("ev", 0), reverse=True)
            from signal_engine import format_signal
            top_sig = football_ai_signals[0]
            top_sig["sport"] = "football"
            # Вариант A: движение линии Pinnacle с момента открытия рынка
            try:
                from line_tracker import get_line_movement as _get_lm
                _lm = _get_lm(str(match.get("id", "")), top_sig.get("outcome", ""))
                if _lm:
                    top_sig["line_movement"] = _lm
            except Exception as _e:
                logger.debug(f"[ignore] {_e}")
            sig_text = format_signal(top_sig)
            # Для ничьей — добавляем мнения AI агентов (они уже посчитаны выше)
            if top_sig.get("draw_signal"):
                _gpt_s  = gpt_result.get("summary", "") or ""
                _llm_s  = llama_result.get("summary", "") or ""
                _gpt_c  = gpt_result.get("confidence", 0)
                _llm_c  = llama_result.get("confidence", 0)
                if _gpt_s or _llm_s:
                    sig_text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    sig_text += "🤖 <b>Мнения агентов о матче:</b>\n"
                    if _gpt_s:
                        sig_text += f"🐍🦁🐐 Химера ({_gpt_c}%): <i>{_gpt_s[:250]}</i>\n"
                    if _llm_s:
                        sig_text += f"🌀 Тень ({_llm_c}%): <i>{_llm_s[:250]}</i>\n"
                    sig_text += "⚠️ <i>Агенты анализировали исход матча, не ставку на ничью</i>"
            sig_text = "🐉 <b>ХИМЕРА (Змея + Лев + Козёл + Тень)</b>\n\n" + sig_text
            # Кнопка "Я поставил"
            _sig_kb = None
            if _football_pred_id:
                _f_kelly = top_sig.get("kelly", 2)
                _f_units = 3 if _f_kelly >= 4 else (2 if _f_kelly >= 2 else 1)
                _f_rec = top_sig.get("outcome", "home_win")
                _f_odds = top_sig.get("odds", 0)
                _f_odds_enc = int(round((_f_odds or 0) * 100))
                _sig_kb = types.InlineKeyboardMarkup(inline_keyboard=[[
                    types.InlineKeyboardButton(
                        text=f"✅ Я поставил {_f_units}u — записать в статистику",
                        callback_data=f"mybet_football_{_football_pred_id}_{_f_odds_enc}_{_f_units}"
                    )
                ]])
            try:
                await call.message.answer(sig_text, parse_mode="HTML", reply_markup=_sig_kb)
            except Exception as _e:
                logger.debug(f"[ignore] {_e}")

            # Если есть дополнительные сигналы (напр. ничья) — показываем отдельно
            for _extra_sig in football_ai_signals[1:]:
                try:
                    _extra_text = "🔀 <b>Дополнительный сигнал</b>\n\n" + format_signal(_extra_sig)
                    if _extra_sig.get("draw_signal"):
                        _gpt_s2 = gpt_result.get("summary", "") or ""
                        _llm_s2 = llama_result.get("summary", "") or ""
                        _gpt_c2 = gpt_result.get("confidence", 0)
                        _llm_c2 = llama_result.get("confidence", 0)
                        if _gpt_s2 or _llm_s2:
                            _extra_text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            _extra_text += "🤖 <b>Мнения агентов о матче:</b>\n"
                            if _gpt_s2:
                                _extra_text += f"🐍🦁🐐 Химера ({_gpt_c2}%): <i>{_gpt_s2[:250]}</i>\n"
                            if _llm_s2:
                                _extra_text += f"🌀 Тень ({_llm_c2}%): <i>{_llm_s2[:250]}</i>\n"
                            _extra_text += "⚠️ <i>Агенты анализировали исход матча, не ставку на ничью</i>"
                    await call.message.answer(_extra_text, parse_mode="HTML")
                except Exception as _e:
                    logger.debug(f"[ignore extra sig] {_e}")

    # --- Рынок: Победитель ---
    elif call.data.startswith("mkt_winner_"):
        try:
            match_index = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            await call.answer("⚠️ Некорректные данные.", show_alert=True)
            return
        cached = analysis_cache.get(match_index)
        if not cached:
            await call.answer("Сначала запустите анализ матча.", show_alert=True)
            return

        home_team = cached["home_team"]
        away_team = cached["away_team"]
        gpt_result = cached["gpt_result"]
        llama_result = cached["llama_result"]
        prophet_data = cached["prophet_data"]
        bookmaker_odds = cached["bookmaker_odds"]

        gpt_verdict = translate_outcome(gpt_result.get("recommended_outcome", ""), home_team, away_team)
        gpt_conf = gpt_result.get("final_confidence_percent", 0)
        gpt_odds_val = gpt_result.get("bookmaker_odds", 0)
        gpt_stake = gpt_result.get("recommended_stake_percent", 0)
        gpt_ev = gpt_result.get("expected_value_percent", 0)
        bet_signal = gpt_result.get("bet_signal", "ПРОПУСТИТЬ")
        signal_reason = gpt_result.get("signal_reason", "")

        llama_verdict = translate_outcome(llama_result.get("recommended_outcome", ""), home_team, away_team)
        llama_conf = llama_result.get("final_confidence_percent", 0)

        signal_icon = "🔥 СТАВИТЬ!" if bet_signal == "СТАВИТЬ" else "❌ НЕ СТАВИТЬ"

        report = f"""
🏆 *ПОБЕДИТЕЛЬ МАТЧА*
{home_team} vs {away_team}
━━━━━━━━━━━━━━━━━━━━━━━━━

📊 *Пророк (нейросеть):*
 П1: {(prophet_data[1]*100 if prophet_data else 0):.0f}% | Х: {(prophet_data[0]*100 if prophet_data else 0):.0f}% | П2: {(prophet_data[2]*100 if prophet_data else 0):.0f}%

🐍🦁🐐 *Вердикт Химеры:*
{conf_icon(gpt_conf)} {gpt_verdict} — {gpt_conf}%
🎯 Кэф: {gpt_odds_val} | Ставка: {gpt_stake:.1f}% | EV: +{gpt_ev:.1f}%

🌀 *Вердикт Тени:*
{conf_icon(llama_conf)} {llama_verdict} — {llama_conf}%

━━━━━━━━━━━━━━━━━━━━━━━━━
*{signal_icon}*
_{signal_reason}_
""".strip()

        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))

    # --- Рынок: Голы ---
    elif call.data.startswith("mkt_goals_"):
        try:
            match_index = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            await call.answer("⚠️ Некорректные данные.", show_alert=True)
            return
        cached = analysis_cache.get(match_index)
        if not cached:
            await call.answer("Сначала запустите анализ матча.", show_alert=True)
            return

        await call.message.edit_text("⏳ *Анализирую рынок голов...*", parse_mode="Markdown")

        goals_result = run_goals_market_agent(
            cached["home_team"], cached["away_team"],
            cached.get("news_summary", ""), cached["bookmaker_odds"]
        )
        report = format_goals_report(cached["home_team"], cached["away_team"], goals_result, cached["bookmaker_odds"], cached.get("poisson_probs"))
        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))


    # --- Рынок: Гандикапы ---
    elif call.data.startswith("mkt_handicap_"):
        try:
            match_index = int(call.data.split("_")[2])
        except (IndexError, ValueError):
            await call.answer("⚠️ Некорректные данные.", show_alert=True)
            return
        cached = analysis_cache.get(match_index)
        if not cached:
            await call.answer("Сначала запустите анализ матча.", show_alert=True)
            return

        await call.message.edit_text("⏳ *Анализирую гандикапы...*", parse_mode="Markdown")

        handicap_result = run_handicap_market_agent(
            cached["home_team"], cached["away_team"],
            cached["prophet_data"], cached["bookmaker_odds"],
            cached["gpt_result"], cached["llama_result"]
        )
        report = format_handicap_report(cached["home_team"], cached["away_team"], handicap_result)
        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))

    # --- CS2: рынки под матчем ---
    elif call.data.startswith("cs2_mkt_"):
        parts = call.data.split("_")
        mkt_type = parts[2]   # winner, maps, rounds
        match_idx = int(parts[3])
        m = cs2_matches_cache[match_idx] if match_idx < len(cs2_matches_cache) else None
        if not m:
            await call.answer("Матч не найден", show_alert=True)
            return
        home = m.get("home", "")
        away = m.get("away", "")
        from sports.cs2 import calculate_cs2_win_prob as _cs2_prob
        _loop = asyncio.get_running_loop()
        analysis = await _loop.run_in_executor(None, _cs2_prob, home, away)
        h_prob = analysis.get("home_prob", 0.5)
        a_prob = analysis.get("away_prob", 0.5)
        h_odds = round(1 / h_prob, 2) if h_prob > 0.01 else 1.9
        a_odds = round(1 / a_prob, 2) if a_prob > 0.01 else 1.9
        h_pct = round(h_prob * 100, 1)
        a_pct = round(a_prob * 100, 1)

        if mkt_type == "winner":
            text = (
                f"🏆 <b>Победитель матча</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎮 <b>{home} vs {away}</b>\n\n"
                f"{'✅' if h_pct > a_pct else '▫️'} <b>{home}</b>\n"
                f"   Вероятность: <b>{h_pct}%</b> | Кэф: <b>{h_odds}</b>\n\n"
                f"{'✅' if a_pct > h_pct else '▫️'} <b>{away}</b>\n"
                f"   Вероятность: <b>{a_pct}%</b> | Кэф: <b>{a_odds}</b>\n\n"
                f"<i>💡 Ставь на {'<b>' + home + '</b>' if h_pct > a_pct else '<b>' + away + '</b>'} "
                f"если кэф у букмекера ≥ {min(h_odds, a_odds):.2f}</i>"
            )
        elif mkt_type == "maps":
            balance = 1 - abs(h_prob - a_prob)
            h_map1 = round(min(max(h_pct + 2, 30), 70), 1)
            a_map1 = round(100 - h_map1, 1)
            score_2_0 = round(balance * 20 + max(h_pct, a_pct) * 0.2, 1)
            score_2_1 = round(100 - score_2_0, 1)
            winner = home if h_pct > a_pct else away
            text = (
                f"🗺️ <b>По картам</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎮 <b>{home} vs {away}</b>\n\n"
                f"<b>Победа на карте 1:</b>\n"
                f"  {'✅' if h_map1 > a_map1 else '▫️'} {home}: <b>{h_map1}%</b>\n"
                f"  {'✅' if a_map1 > h_map1 else '▫️'} {away}: <b>{a_map1}%</b>\n\n"
                f"<b>Счёт серии:</b>\n"
                f"  📊 {winner} 2:0 → <b>{score_2_0:.0f}%</b>\n"
                f"  📊 {winner} 2:1 → <b>{score_2_1:.0f}%</b>\n\n"
                f"<i>💡 Лучший вариант: <b>{winner}</b> выигрывает серию</i>"
            )
        elif mkt_type == "rounds":
            balance = 1 - abs(h_prob - a_prob)
            expected = round(24.5 + balance * 5, 1)
            over = expected > 26.5
            text = (
                f"🎯 <b>Тотал раундов (Карта 1)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎮 <b>{home} vs {away}</b>\n\n"
                f"📊 Прогноз раундов: <b>{expected}</b>\n\n"
                f"{'✅' if over else '▫️'} <b>Больше 26.5</b>\n"
                f"{'✅' if not over else '▫️'} <b>Меньше 26.5</b>\n\n"
                f"<i>{'⚖️ Равный матч — много раундов' if balance > 0.6 else '💪 Один доминирует — короткие карты'}</i>"
            )
        else:
            text = "⚠️ Неизвестный рынок"

        back_kb = InlineKeyboardBuilder()
        back_kb.button(text="🏆 Победитель" if mkt_type != "winner" else "🗺️ По картам",
                       callback_data=f"cs2_mkt_{'winner' if mkt_type != 'winner' else 'maps'}_{match_idx}")
        back_kb.button(text="🎯 Тотал раундов" if mkt_type != "rounds" else "🏆 Победитель",
                       callback_data=f"cs2_mkt_{'rounds' if mkt_type != 'rounds' else 'winner'}_{match_idx}")
        back_kb.button(text="↩️ К анализу", callback_data=f"back_to_report_cs2_{match_idx}")
        back_kb.button(text="🏠 Меню", callback_data="back_to_main")
        back_kb.adjust(2)
        await call.answer()
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb.as_markup())


    # --- Баскетбол: рынки под матчем ---
    elif call.data.startswith("bball_mkt_"):
        parts = call.data.split("_")
        mkt_type = parts[2]  # winner, total, spread
        match_idx = int(parts[-1])
        league_key = "_".join(parts[3:-1])
        _loop = asyncio.get_running_loop()
        from sports.basketball import get_basketball_matches as _get_bball
        matches = await _loop.run_in_executor(None, _get_bball, league_key)
        if not matches or match_idx >= len(matches):
            await call.answer("Матч не найден", show_alert=True)
            return
        m = matches[match_idx]
        home = m.get("home_team", m.get("home", "Команда A"))
        away = m.get("away_team", m.get("away", "Команда B"))
        from sports.basketball.core import get_basketball_odds as _bball_odds
        odds = _bball_odds(m)
        h_odds = float(odds.get("home_win") or 1.9)
        a_odds = float(odds.get("away_win") or 1.9)
        h_pct = round(100 / h_odds, 1)
        a_pct = round(100 / a_odds, 1)
        total_data = odds.get("total_analysis", {}) or {}
        total_line = total_data.get("line") or odds.get("total_over_line") or 220.5
        over_odds = odds.get("total_over_odds") or 1.9
        under_odds = odds.get("total_under_odds") or 1.9
        spread_h = odds.get("spread_home") or -3.5
        spread_a = -spread_h

        if mkt_type == "winner":
            text = (
                f"🏀 <b>Победитель матча</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>{home} vs {away}</b>\n\n"
                f"{'✅' if h_pct > a_pct else '▫️'} <b>{home}</b>\n"
                f"   Кэф: <b>{h_odds}</b> | Вероятность: <b>{h_pct}%</b>\n\n"
                f"{'✅' if a_pct > h_pct else '▫️'} <b>{away}</b>\n"
                f"   Кэф: <b>{a_odds}</b> | Вероятность: <b>{a_pct}%</b>\n\n"
                f"<i>💡 Рекомендация: {'<b>' + home + '</b>' if h_pct > a_pct else '<b>' + away + '</b>'}</i>"
            )
        elif mkt_type == "total":
            text = (
                f"📊 <b>Тотал очков</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>{home} vs {away}</b>\n\n"
                f"📏 Линия: <b>{total_line}</b> очков\n\n"
                f"📈 <b>Больше {total_line}</b>  Кэф: <b>{over_odds}</b>\n"
                f"📉 <b>Меньше {total_line}</b>  Кэф: <b>{under_odds}</b>\n\n"
                f"<i>💡 Равные команды → больше очков. Защитный стиль → меньше.</i>"
            )
        elif mkt_type == "spread":
            text = (
                f"⚖️ <b>Фора (Гандикап)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>{home} vs {away}</b>\n\n"
                f"🏠 <b>{home}</b> фора: <b>{spread_h:+.1f}</b>\n"
                f"✈️ <b>{away}</b> фора: <b>{spread_a:+.1f}</b>\n\n"
                f"<i>💡 {'Хозяева фавориты — фора выравнивает шансы' if spread_h < 0 else 'Гости фавориты — дерзкая ставка на хозяев с форой'}</i>"
            )
        else:
            text = "⚠️ Неизвестный рынок"

        back_kb = InlineKeyboardBuilder()
        back_kb.button(text="🏀 Победитель" if mkt_type != "winner" else "📊 Тотал",
                       callback_data=f"bball_mkt_{'winner' if mkt_type != 'winner' else 'total'}_{league_key}_{match_idx}")
        back_kb.button(text="⚖️ Фора" if mkt_type != "spread" else "📊 Тотал",
                       callback_data=f"bball_mkt_{'spread' if mkt_type != 'spread' else 'total'}_{league_key}_{match_idx}")
        back_kb.button(text="⬅️ Назад к матчу", callback_data=f"bball_match_{league_key}_{match_idx}")
        back_kb.button(text="↩️ К анализу", callback_data=f"back_to_report_bball_{league_key}_{match_idx}")
        back_kb.button(text="🏠 Меню", callback_data="back_to_main")
        back_kb.adjust(2)
        await call.answer()
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb.as_markup())

# --- 9. Проверка результатов ---







# _make_loss_explanation импортирована из formatters.py

async def check_results_task(bot: Bot):
    """Периодически проверяет результаты сыгранных матчей по всем лигам."""
    while True:
        try:
            # Все виды спорта — проверяем независимо
            pending_football = get_pending_predictions("football")
            pending_cs2      = get_pending_predictions("cs2")
            pending_tennis   = get_pending_predictions("tennis")
            pending_bball    = get_pending_predictions("basketball")
            pending_hockey   = get_pending_predictions("hockey")
            pending_any      = pending_football or pending_cs2 or pending_tennis or pending_bball or pending_hockey

            if not pending_any:
                await asyncio.sleep(3600)
                continue

            print(f"[Результаты] Всего ожидает: ⚽{len(pending_football)} 🎮{len(pending_cs2)} 🎾{len(pending_tennis)} 🏀{len(pending_bball)} 🏒{len(pending_hockey)}")

            # ── CS2: отдельный трекер через PandaScore / Esports API ──────
            try:
                from sports.cs2.results_tracker import check_and_update_cs2_results
                cs2_updated = check_and_update_cs2_results()
                if cs2_updated:
                    print(f"[Результаты CS2] Обновлено прогнозов: {cs2_updated}")
            except Exception as cs2_track_err:
                print(f"[Результаты CS2] Ошибка трекера: {cs2_track_err}")

            # ── Теннис: трекер через api-tennis.com ──────────────────────
            try:
                from sports.tennis.results_tracker import check_and_update_tennis_results
                tennis_updated = check_and_update_tennis_results()
                if tennis_updated:
                    print(f"[Результаты Tennis] Обновлено прогнозов: {tennis_updated}")
            except Exception as tennis_track_err:
                print(f"[Результаты Tennis] Ошибка трекера: {tennis_track_err}")

            # ── Баскетбол: трекер через The Odds API /scores/ ────────────
            try:
                from sports.basketball.results_tracker import check_and_update_basketball_results
                bball_updated = check_and_update_basketball_results()
                if bball_updated:
                    print(f"[Результаты Basketball] Обновлено прогнозов: {bball_updated}")
            except Exception as bball_track_err:
                print(f"[Результаты Basketball] Ошибка трекера: {bball_track_err}")

            # ── Хоккей: трекер через The Odds API /scores/ ───────────────
            try:
                from sports.hockey.results_tracker import check_and_update_hockey_results
                hockey_updated = check_and_update_hockey_results()
                if hockey_updated:
                    print(f"[Результаты Hockey] Обновлено прогнозов: {hockey_updated}")
            except Exception as hockey_track_err:
                print(f"[Результаты Hockey] Ошибка трекера: {hockey_track_err}")

            # ── Футбол: отдельный трекер ─────────────────────────────────
            if pending_football:
                try:
                    from sports.football.results_tracker import check_and_update_football_results
                    _fb_updated = check_and_update_football_results(on_elo_update=update_elo_after_match)
                    print(f"[Результаты ⚽] Обновлено: {_fb_updated}")
                except Exception as _fb_e:
                    print(f"[Результаты ⚽] Ошибка трекера: {_fb_e}")

            # ── Авто-закрытие застарелых прогнозов (>7 дней без результата) ──
            try:
                from database import expire_stale_predictions
                _expired = expire_stale_predictions(days=7)
                if _expired:
                    print(f"[DB] Закрыто застарелых прогнозов: {_expired}")
            except Exception as _exp_e:
                print(f"[DB] Ошибка expire_stale: {_exp_e}")

            # ── Авто-обучение MetaLearner ──────────────────────────────────
            try:
                from meta_learner import MetaLearner
                _ml = MetaLearner(signal_engine_path="signal_engine.py")
                # Стрик поражений → форсируем обучение раньше
                _streak = get_recent_signal_streak()
                _force_ml = _streak <= -5
                if _force_ml:
                    print(f"[MetaLearner] Серия {abs(_streak)} поражений — форсирую обновление порогов")
                for _sport in ["football", "cs2", "tennis", "basketball"]:
                    _perf = _ml.analyze_performance(_sport)
                    if _perf.get("total", 0) >= 10 or _force_ml:
                        _updates = _ml.suggest_updates(_sport, _perf)
                        if _updates:
                            _ml.apply_updates(_sport, _updates)
                            print(f"[MetaLearner] {_sport} авто-обновление: {_updates}")
                        else:
                            print(f"[MetaLearner] {_sport}: ROI={_perf.get('roi',0):.1f}%, точность={_perf.get('accuracy',0):.1f}%")
                _bb_weights = _ml.analyze_basketball_weights()
                if _bb_weights:
                    _ml.apply_updates("basketball", _bb_weights)
                    print(f"[MetaLearner] Basketball веса обновлены: {_bb_weights}")
                _hk_weights = _ml.analyze_hockey_weights()
                if _hk_weights:
                    _ml.apply_updates("hockey", _hk_weights)
                    print(f"[MetaLearner] Hockey веса обновлены: {_hk_weights}")
            except Exception as _ml_e:
                print(f"[MetaLearner] Ошибка: {_ml_e}")

            # ── Уведомления пользователям — перенесены в background_tasks.py ──

        except Exception as e:
            print(f"[Результаты] Общая ошибка: {e}")
        await asyncio.sleep(3600)  # Проверяем каждый час

# --- 10. Авто-перекалибровка ELO каждую неделю ---
async def auto_elo_recalibration_task():
    """
    Автоматически пересчитывает ELO рейтинги по результатам сезона 2024/25.
    Запускается каждый понедельник в 3:00 ночи.
    """
    import importlib
    from datetime import datetime, timedelta
    global _elo_ratings, _team_form

    # Ждём до следующего понедельника 03:00
    while True:
        now = datetime.now()
        # Следующий понедельник
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= 3:
            days_until_monday = 7  # Уже был сегодня, ждём следующий
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
        wait_seconds = (next_run - now).total_seconds()
        print(f"[ELO-Авто] Следующая перекалибровка: {next_run.strftime('%d.%m.%Y %H:%M')} (через {wait_seconds/3600:.1f} ч)")
        await asyncio.sleep(wait_seconds)

        # Запускаем перекалибровку
        try:
            print("[ELO-Авто] Начинаю еженедельную перекалибровку ELO...")
            import elo_calibrate as ec
            # Загружаем все результаты
            all_matches = []
            for league_key, info in ec.LEAGUE_SOURCES.items():
                matches = ec.fetch_league_results(info["url"])
                for m in matches:
                    ft = m.get("score", {}).get("ft", [])
                    if len(ft) == 2:
                        all_matches.append({
                            "date": m.get("date", ""),
                            "home": ec.normalize_name(m.get("team1", "")),
                            "away": ec.normalize_name(m.get("team2", "")),
                            "home_goals": ft[0],
                            "away_goals": ft[1],
                        })
            all_matches.sort(key=lambda x: x["date"])

            # Пересчитываем ELO
            new_ratings = {}
            for m in all_matches:
                new_ratings = ec.update_elo_single(new_ratings, m["home"], m["away"], m["home_goals"], m["away_goals"])

            # Строим форму
            new_form = ec.build_form_tracker(all_matches)

            # Сохраняем
            ec.save_calibrated_elo(new_ratings, new_form)

            # Обновляем глобальные переменные в памяти
            _elo_ratings = new_ratings
            _team_form = new_form
            print(f"[ELO-Авто] ✅ Перекалибровка завершена: {len(new_ratings)} команд, {len(all_matches)} матчей")
        except Exception as e:
            print(f"[ELO-Авто] Ошибка перекалибровки: {e}")

        # Рекалибровка ELO баскетбола
        try:
            print("[ELO-Баскетбол] Начинаю рекалибровку ELO баскетбола...")
            import elo_basketball_calibrate as ebc
            total = ebc.calibrate()
            print(f"[ELO-Баскетбол] ✅ Готово. Обработано матчей: {total}")
        except Exception as e:
            print(f"[ELO-Баскетбол] Ошибка рекалибровки: {e}")

        # Meta Learner — анализ весов баскетбольной модели
        try:
            from meta_learner import MetaLearner
            ml = MetaLearner()
            bball_weights = ml.analyze_basketball_weights()
            if bball_weights:
                ml.apply_updates('basketball', bball_weights)
                print(f"[Meta-Баскетбол] ✅ Веса обновлены: {bball_weights}")
            else:
                print("[Meta-Баскетбол] Недостаточно данных для корректировки весов")
        except Exception as e:
            print(f"[Meta-Баскетбол] Ошибка: {e}")

        # XGBoost — инкрементальное переобучение на живых матчах
        try:
            print("[XGBoost-Авто] Проверка новых матчей для переобучения...")
            loop = asyncio.get_running_loop()
            import functools as _func
            from ml.train_model import retrain_incremental
            _result = await loop.run_in_executor(None, _func.partial(retrain_incremental, min_new_rows=30))
            if _result["status"] == "ok":
                print(f"[XGBoost-Авто] ✅ Переобучено! +{_result['new_rows']} матчей | "
                      f"Sport {_result['acc_sport']}% | Market {_result['acc_market']}%")
                # Перезагружаем предиктор
                try:
                    import importlib, ml.predictor as _pred
                    importlib.reload(_pred)
                    print("[XGBoost-Авто] Предиктор перезагружен")
                except Exception as _e:
                    logger.debug(f"[ignore] {_e}")
            elif _result["status"] == "skip":
                print(f"[XGBoost-Авто] Пропуск: {_result['reason']}")
            else:
                print(f"[XGBoost-Авто] Ошибка: {_result.get('reason')}")
        except Exception as _xe:
            print(f"[XGBoost-Авто] Ошибка переобучения: {_xe}")


async def auto_refresh_matches_task():
    """Автоматически обновляет список матчей каждые 6 часов."""
    while True:
        await asyncio.sleep(21600)  # 6 часов
        try:
            _loop_ref = asyncio.get_running_loop()
            matches = await _loop_ref.run_in_executor(None, lambda: get_matches(force=True))
            league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "")
            print(f"[Авто] Список матчей обновлён: {league_name} — {len(matches)} матчей")
        except Exception as e:
            print(f"[Авто] Ошибка обновления матчей: {e}")




def _format_chimera_page(candidates: list, idx: int, bankroll: float = None) -> str:
    """Форматирует одну страницу карусели — полный формат как в format_chimera_signals."""
    import html as _html
    from chimera_signal import _format_match_time, score_label, _format_totals_block
    c = candidates[idx]
    total = len(candidates)
    sp = c.get("sport", "football")
    sp_emoji = {"cs2": "🎮", "tennis": "🎾", "basketball": "🏀", "hockey": "🏒"}.get(sp, "⚽")

    t_str, t_live = _format_match_time(c.get("commence_time", ""))
    live_tag = "🟢 LIVE" if t_live else (f"🕐 {t_str}" if t_str else "")
    time_line = f"\n{live_tag}" if live_tag else ""

    score = c.get("chimera_score", 0)
    label = score_label(score)

    if idx == 0:
        header = f"🎯 <b>CHIMERA SIGNAL — ЛУЧШАЯ СТАВКА ДНЯ</b>"
    else:
        header = f"📋 <b>ВАРИАНТ {idx + 1} из {total}</b>"

    matchup = f"<b>{c.get('home','')} vs {c.get('away','')}</b>"
    bet_line = f"📌 Ставка: <b>{c.get('team','')} ({c.get('outcome','')})</b>"

    lines = [
        header, "",
        f"<b>{label} [{score:.0f}/100]</b>{time_line}", "",
        f"{sp_emoji} | {matchup}",
        bet_line,
        f"💰 Кэф: <b>{c.get('odds','?')}</b> | Наша вероятность: <b>{c.get('prob',0)}%</b>",
        f"📈 EV: <b>{c.get('ev',0):+.1f}%</b> | Ставь: <b>{c.get('kelly',0):.1f}%</b> банка",
    ]

    # AI блок
    if c.get("ai_confirmed") is True:
        llama_agrees = c.get("llama_agrees")
        ai_header = "🐉 Химера единогласна (Змея + Лев + Козёл + Тень)" if llama_agrees else "🐍🦁🐐 Химера подтверждает"
        ai_reason   = _html.escape(str(c.get("ai_reason", "") or ""))
        llama_logic = _html.escape(str(c.get("llama_logic", "") or ""))
        llama_warn  = _html.escape(str(c.get("llama_warning", "") or ""))
        lines += ["", f"<b>{ai_header} ({c.get('ai_confidence',0)}% уверенности):</b>",
                  f"<i>🐍🦁🐐 Химера: «{ai_reason}»</i>"]
        if llama_logic:
            lines.append(f"<i>🌀 Тень: «{llama_logic}»</i>")
        if llama_warn:
            lines.append(f"⚠️ Риск: {llama_warn}")
    elif c.get("ai_confirmed") is False:
        lines.append("\n⚠️ AI сомневается в этой ставке")
    elif c.get("ai_confirmed") is None:
        if c.get("ai_reason"):
            lines.append(f"\n🤖 <i>AI: «{_html.escape(str(c['ai_reason']))}»</i>")
        else:
            lines.append("\n🤖 <i>AI не выбрал этот вариант как лучший</i>")

    # Детали CHIMERA Score
    score_lines = [
        "", "📊 <b>Детали CHIMERA Score:</b>",
        f"├ ELO преимущество: {c.get('elo_pts',0):+.0f} pts" +
            (f" (разрыв: {c['elo_gap']} очков)" if c.get('elo_gap') else ""),
        f"├ Форма команды: {c.get('form_pts',0):+.0f} pts" +
            (f" ({c['form']})" if c.get('form') else ""),
        f"├ Ценность кэфа: {c.get('value_pts',0):+.0f} pts" +
            f" ({c.get('prob',0)}% vs бук {c.get('implied_prob',0)}%)",
        f"├ Сила прогноза: {c.get('prob_pts',0):+.0f} pts",
    ]
    if c.get("xg_pts", 0):
        score_lines.append(f"├ xG качество: {c['xg_pts']:+.0f} pts")
    if c.get("line_pts", 0):
        icon = "📉" if c["line_pts"] > 0 else "⚠️"
        score_lines.append(f"├ {icon} Движение линии: {c['line_pts']:+.0f} pts")
    if c.get("h2h_pts", 0):
        score_lines.append(f"├ ⚔️ H2H история: {c['h2h_pts']:+.0f} pts")
    score_lines[-1] = score_lines[-1].replace("├", "└")
    lines += score_lines

    totals_block = _format_totals_block(c)
    if totals_block:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━━", totals_block]

    result = "\n".join(lines)
    if len(result) > 4000:
        result = result[:3990] + "\n…"
    return result

# _format_chimera_page, _build_chimera_carousel_kb, _build_chimera_kb импортированы из formatters.py

# --- 10c. Команда /signals — CHIMERA SIGNAL ENGINE v2 ---
_signals_scan_in_progress: bool = False  # защита от двойного нажатия

@dp.message(Command("signals"))
async def cmd_signals(message: types.Message):
    """Кнопка 'Сигналы дня'."""
    global _signals_scan_in_progress
    if message.from_user:
        log_action(message.from_user.id, "signals")
        # Проверка доступа — сигналы только для подписчиков
        from access import check_access
        reason = await check_access(message.from_user.id, message.bot,
                                    require_full=True, count_analysis=False)
        if reason != "ok":
            await _send_access_denied(message, reason)
            return
    import time as _time_mod
    from chimera_signal import compute_chimera_score, run_ai_verification, format_chimera_signals

    # ── Кеш: если скан свежий (<45 мин) — отдаём моментально ────────────────
    _cached = _signals_scan_cache.get("last")
    # Сбрасываем кеш если в кандидатах нет _pred_id (старый формат до обновления)
    if _cached and _cached.get("candidates") and "_pred_id" not in _cached["candidates"][0]:
        _cached = None
        _signals_scan_cache.clear()
    if _cached and (_time_mod.time() - _cached["ts"]) < SIGNALS_SCAN_TTL:
        top_candidates   = _cached["candidates"]
        _chimera_top_pred_id = _cached.get("top_pred_id")
        _chimera_top_sport   = _cached.get("top_sport", "football")
        _chimera_top_odds    = _cached.get("top_odds", 0)
        _cache_age_min = int((_time_mod.time() - _cached["ts"]) / 60)
        print(f"[CHIMERA] Кеш сигналов использован (возраст {_cache_age_min} мин)")
        try:
            _broll_sig = get_user_bankroll(message.from_user.id) or 0
            result_text = _format_chimera_page(top_candidates, 0, bankroll=_broll_sig)
            result_text += f"\n\n<i>🕐 Обновлено {_cache_age_min} мин назад</i>"
            _chimera_kb = _build_chimera_kb(
                top_candidates, _chimera_top_pred_id, _chimera_top_sport,
                _chimera_top_odds, message.from_user.id
            )
            await message.answer(result_text, parse_mode="HTML", reply_markup=_chimera_kb)
        except Exception as _ce:
            logger.error(f"[CHIMERA Cache] Ошибка форматирования: {_ce}")
            await message.answer("⚠️ Ошибка загрузки кеша. Перезапускаю скан...", parse_mode="HTML")
            _signals_scan_cache.clear()
            await cmd_signals(message)
        return

    if _signals_scan_in_progress:
        await message.answer(
            "⏳ <b>Сканирование уже идёт...</b>\n"
            "<i>Подожди — результаты появятся через 30–90 секунд.</i>",
            parse_mode="HTML"
        )
        return

    _signals_scan_in_progress = True
    status_msg = await message.answer(
        "🔍 <b>CHIMERA SIGNAL запущен...</b>\n\n"
        "⏳ <i>Это займёт 30–90 секунд — Химера сканирует рынок.</i>\n\n"
        "⚙️ Шаг 1/3: Загрузка матчей (Футбол + CS2 + Теннис + Баскетбол)...",
        parse_mode="HTML"
    )

    # Получаем AI клиенты
    try:
        from agents import client as _gpt_client, groq_client as _groq_client
    except ImportError:
        _gpt_client = None
        _groq_client = None

    # Инициализируем модули движения линий и H2H
    try:
        from line_movement import make_match_key, record_odds, get_movement
        _line_movement_ok = True
    except ImportError:
        _line_movement_ok = False

    # historical_movement.prefetch_snapshots убран — line_tracker.py покрывает
    # движение линий Pinnacle без дополнительных API кредитов.

    try:
        from api_football import get_h2h
        _h2h_ok = True
    except ImportError:
        _h2h_ok = False

    all_candidates = []
    _scan_errors = []  # собираем ошибки для финального сообщения

    def _run_math_scan():
        """Весь блокирующий скан — запускается в thread executor."""
        import concurrent.futures as _cf
        from datetime import datetime, timezone as _tz, timedelta as _td
        import requests as _req
        from odds_cache import get_odds as _get_odds

        _now = datetime.now(_tz.utc)
        # Максимум — конец завтрашнего дня UTC (сегодня + завтра)
        _tomorrow_end = (_now + _td(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
        _cutoff_future = _tomorrow_end.isoformat()[:19]
        _cutoff_past   = (_now - _td(hours=3)).isoformat()[:19]

        # ── Параллельная загрузка всех лиг (с кешем 30 мин) ─────────────
        def _fetch_league(lkey):
            # Все регионы + spreads для полного набора букмекеров (Pinnacle, Betfair, etc.)
            raw = _get_odds(lkey, markets="h2h,totals,spreads")
            if raw is None:
                return "quota", []
            if isinstance(raw, list):
                filtered = [m for m in raw
                            if _cutoff_past < m.get("commence_time", "") <= _cutoff_future]
                return lkey, filtered
            return lkey, []

        def _fetch_bball_league(lkey):
            raw = _get_odds(lkey, markets="h2h,totals,spreads")
            if raw and isinstance(raw, list):
                now2 = datetime.now(_tz.utc)
                cutoff2 = (now2 - _td(hours=2)).isoformat()[:19]
                return lkey, [m for m in raw if m.get("commence_time", "") > cutoff2][:25]
            return lkey, []

        def _scan_football(matches):
            cands = []
            try:
                from historical_movement import get_line_movement as _get_hist_mov
                _hist_mov_ok = True
            except ImportError:
                _hist_mov_ok = False

            for m in matches[:30]:
                try:
                    home = m.get("home_team", "")
                    away = m.get("away_team", "")
                    if not home or not away:
                        continue
                    odds = get_bookmaker_odds(m)
                    if not odds.get("home_win"):
                        continue
                    elo_h = _elo_ratings.get(home, 1500)
                    elo_a = _elo_ratings.get(away, 1500)
                    form_h = get_form_string(home, _team_form)
                    form_a = get_form_string(away, _team_form)
                    elo_p = elo_win_probabilities(home, away, _elo_ratings, _team_form)
                    _movement = {}
                    if _line_movement_ok and odds:
                        _mkey = make_match_key(home, away, m.get("commence_time", ""))
                        record_odds(_mkey, odds)
                        _movement = get_movement(_mkey, odds)
                    c_list = compute_chimera_score(
                        home_team=home, away_team=away,
                        home_prob=elo_p["home"], away_prob=elo_p["away"], draw_prob=elo_p["draw"],
                        bookmaker_odds=odds, home_form=form_h, away_form=form_a,
                        elo_home=elo_h, elo_away=elo_a,
                        league=m.get("sport_key", ""), line_movement=_movement,
                    )
                    _ct = m.get("commence_time", "")
                    _mid = m.get("id", "")
                    _sport_key = m.get("sport_key", "")
                    for c in c_list:
                        c["commence_time"] = _ct
                        # ── Исторический сдвиг линии Pinnacle ─────────────
                        if _hist_mov_ok and odds.get("pinnacle_home"):
                            try:
                                hist_mov = _get_hist_mov(
                                    sport_key=_sport_key,
                                    match_id=_mid,
                                    home_team=home, away_team=away,
                                    current_pinnacle_home=odds.get("pinnacle_home", 0),
                                    current_pinnacle_away=odds.get("pinnacle_away", 0),
                                    current_pinnacle_draw=odds.get("pinnacle_draw", 0),
                                )
                                if hist_mov.get("score_boost"):
                                    c["chimera_score"] = c.get("chimera_score", 0) + hist_mov["score_boost"]
                                    c["hist_movement"] = hist_mov
                            except Exception as _e:
                                logger.debug(f"[ignore] {_e}")
                    cands.extend(c_list)
                except Exception as _ce:
                    print(f"[CHIMERA] Ошибка {m.get('home_team','')} vs {m.get('away_team','')}: {_ce}")
            return cands

        def _scan_cs2():
            cands = []
            try:
                from sports.cs2 import calculate_cs2_win_prob
                from signal_engine import predict_cs2_totals as _ps_totals

                # Если кэш пустой (пользователь не открывал раздел CS2) — фетчим сами
                _cs2_source = cs2_matches_cache
                if not _cs2_source:
                    try:
                        from sports.cs2.pandascore import get_cs2_matches_pandascore
                        _fetched = get_cs2_matches_pandascore()
                        if _fetched:
                            cs2_matches_cache.clear()
                            cs2_matches_cache.extend(_fetched)
                            _cs2_source = _fetched
                            print(f"[CHIMERA CS2] Загружено {len(_fetched)} матчей из PandaScore")
                    except Exception as _fe:
                        print(f"[CHIMERA CS2] Ошибка фетча матчей: {_fe}")

                for m in _cs2_source[:25]:
                    try:
                        home = m.get("home", "")
                        away = m.get("away", "")
                        if not home or not away:
                            continue
                        # Tier-фильтр ДО дорогого API-вызова — экономит время на Tier-3 матчах
                        _ct = m.get("commence_time", "") or m.get("time", "")
                        _cs2_tier = m.get("tier", "B")
                        _league_low = (m.get("league", "") + " " + m.get("tournament", "")).lower()
                        _is_t3 = any(kw in _league_low for kw in CS2_TIER3_KEYWORDS) or _cs2_tier not in ("S", "A")
                        if _is_t3:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: Tier-3/regional")
                            continue
                        analysis = calculate_cs2_win_prob(home, away)
                        h_prob = analysis.get("home_prob", 0)
                        a_prob = analysis.get("away_prob", 0)
                        if not h_prob:
                            continue
                        # Пропускаем матчи без реальных данных (обе команды неизвестны)
                        data_conf = analysis.get("data_confidence", 0)
                        if data_conf < 0.45:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: нет данных (conf={data_conf:.2f})")
                            continue
                        # Требуем явный ELO-разрыв (> 100 пунктов) для надёжного прогноза
                        elo_h_val = analysis.get("elo_home", 0)
                        elo_a_val = analysis.get("elo_away", 0)
                        if elo_h_val > 0 and elo_a_val > 0 and abs(elo_h_val - elo_a_val) < 100:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: ELO разрыв мал ({abs(elo_h_val - elo_a_val)})")
                            continue
                        raw_odds = m.get("odds", {})
                        h_odds = raw_odds.get("home_win") or (round(1.0 / h_prob, 2) if h_prob > 0 else 1.85)
                        a_odds = raw_odds.get("away_win") or (round(1.0 / a_prob, 2) if a_prob > 0 else 1.85)
                        h_stats = analysis.get("home_stats", {})
                        a_stats = analysis.get("away_stats", {})
                        c_list = compute_chimera_score(
                            home_team=home, away_team=away,
                            home_prob=h_prob, away_prob=a_prob, draw_prob=0,
                            bookmaker_odds={"home_win": h_odds, "away_win": a_odds, "draw": 0},
                            home_form=h_stats.get("form", ""), away_form=a_stats.get("form", ""),
                            elo_home=analysis.get("elo_home", 1450), elo_away=analysis.get("elo_away", 1450),
                            league="CS2",
                            apply_calibration=False,
                        )
                        try:
                            _cs2_totals = _ps_totals(
                                home_prob=h_prob, away_prob=a_prob,
                                home_map_stats={mp: hp * 100 for mp, hp, _ in analysis.get("maps", [])},
                                away_map_stats={mp: ap * 100 for mp, _, ap in analysis.get("maps", [])},
                                predicted_maps=[mp for mp, _, _ in analysis.get("maps", [])],
                            )
                        except Exception:
                            _cs2_totals = None
                        for c in c_list:
                            c["sport"] = "cs2"
                            c["commence_time"] = _ct
                            c["cs2_tier"] = _cs2_tier
                            c["tier_label"] = m.get("tier_label", "🎮")
                            c["totals_data"] = _cs2_totals
                            if _is_t3:
                                c["cs2_tier3"] = True
                        cands.extend(c_list)
                    except Exception as _ce:
                        print(f"[CHIMERA CS2] Ошибка {m.get('home','')} vs {m.get('away','')}: {_ce}")
            except Exception as e:
                print(f"[CHIMERA] CS2 ошибка: {e}")
            return cands

        def _scan_tennis():
            try:
                from sports.tennis import scan_tennis_signals
                from sports.tennis.matches import get_tennis_matches, get_active_tennis_sports
                # Диагностика: сначала проверяем что вообще есть турниры
                sport_keys = get_active_tennis_sports()
                print(f"[CHIMERA] Теннис: активных турниров = {len(sport_keys)}: {sport_keys[:5]}")
                if not sport_keys:
                    print("[CHIMERA] Теннис: нет активных турниров в The Odds API")
                    return []
                raw_matches = get_tennis_matches()
                print(f"[CHIMERA] Теннис: матчей с коэффициентами = {len(raw_matches)}")
                if not raw_matches:
                    return []
                cands = scan_tennis_signals()
                # Минимальный порог уверенности 55% для теннисных кандидатов
                cands = [c for c in cands if c.get("prob", 0) >= 55]
                print(f"[CHIMERA] Теннис: кандидатов после скана = {len(cands)}")
                return cands
            except Exception as e:
                import traceback
                print(f"[CHIMERA] Теннис ошибка: {e}")
                traceback.print_exc()
                return []

        def _scan_hockey():
            cands = []
            try:
                from sports.hockey import get_hockey_matches
                from sports.hockey.core import get_hockey_odds, calculate_hockey_win_prob
                for league_key, league_name in [
                    ("icehockey_nhl",                  "🏒 NHL"),
                    ("icehockey_sweden_hockey_league", "🇸🇪 SHL"),
                    ("icehockey_ahl",                  "🇺🇸 AHL"),
                    ("icehockey_liiga",                "🇫🇮 Finnish Liiga"),
                    ("icehockey_sweden_allsvenskan",   "🇸🇪 Allsvenskan"),
                ]:
                    try:
                        matches = get_hockey_matches(league_key)
                        for hm in matches[:15]:
                            try:
                                home = hm.get("home_team", "")
                                away = hm.get("away_team", "")
                                if not home or not away:
                                    continue
                                _ct = hm.get("commence_time", "")
                                # Фильтр: только сегодня/завтра
                                if _ct and _ct > _cutoff_future:
                                    continue
                                hodds = get_hockey_odds(hm)
                                if not hodds.get("home_win"):
                                    continue
                                hres = calculate_hockey_win_prob(
                                    home, away, hodds, league_key,
                                    no_vig_home=hodds.get("no_vig_home", 0.0),
                                    no_vig_away=hodds.get("no_vig_away", 0.0),
                                )
                                hp = hres.get("home_prob", 0)
                                ap = hres.get("away_prob", 0)
                                if not hp:
                                    continue
                                # Пропускаем команды без реального ELO (AHL/неизвестные)
                                if hres.get("no_elo_data"):
                                    logger.debug(f"[CHIMERA HOCKEY] Пропуск {home} vs {away}: нет ELO данных")
                                    continue
                                # Пропускаем если модель говорит НЕ СТАВИТЬ
                                if hres.get("bet_signal", "") == "НЕ СТАВИТЬ":
                                    continue
                                hcands = compute_chimera_score(
                                    home_team=home, away_team=away,
                                    home_prob=hp, away_prob=ap, draw_prob=0,
                                    bookmaker_odds={"home_win": hodds.get("home_win", 0),
                                                   "away_win": hodds.get("away_win", 0), "draw": 0},
                                    home_form=hres.get("home_form", ""), away_form=hres.get("away_form", ""),
                                    elo_home=hres.get("elo_home", 1550), elo_away=hres.get("elo_away", 1550),
                                    league=league_key,
                                    apply_calibration=False,
                                )
                                for hc in hcands:
                                    hc["sport"] = "hockey"
                                    hc["league_name"] = league_name
                                    hc["commence_time"] = _ct
                                cands.extend(hcands)
                            except Exception as _he:
                                logger.debug(f"[CHIMERA HOCKEY] {home} vs {away}: {_he}")
                    except Exception as _le:
                        logger.debug(f"[CHIMERA HOCKEY] {league_key}: {_le}")
                print(f"[CHIMERA] Хоккей: {len(cands)} кандидатов")
            except Exception as e:
                print(f"[CHIMERA] Хоккей ошибка: {e}")
            return cands

        def _scan_basketball(bball_data):
            cands = []
            try:
                from sports.basketball import calculate_basketball_win_prob
                from sports.basketball.core import get_basketball_odds
                total = 0
                for bkey, bname, bmatches in bball_data:
                    for bm in bmatches:
                        try:
                            bh = bm.get("home_team", "")
                            ba = bm.get("away_team", "")
                            if not bh or not ba:
                                continue
                            bodds = get_basketball_odds(bm)
                            if not bodds.get("home_win"):
                                continue
                            bres = calculate_basketball_win_prob(
                                bh, ba, bodds, bkey,
                                no_vig_home=bodds.get("no_vig_home", 0.0),
                                no_vig_away=bodds.get("no_vig_away", 0.0),
                            )
                            hp = bres.get("home_prob", 0)
                            ap = bres.get("away_prob", 0)
                            if not hp:
                                continue
                            bcands = compute_chimera_score(
                                home_team=bh, away_team=ba,
                                home_prob=hp, away_prob=ap, draw_prob=0,
                                bookmaker_odds={"home_win": bodds.get("home_win", 0),
                                               "away_win": bodds.get("away_win", 0), "draw": 0},
                                home_form=bres.get("home_form", ""), away_form=bres.get("away_form", ""),
                                elo_home=bres.get("elo_home", 1550), elo_away=bres.get("elo_away", 1550),
                                league=bkey,
                                apply_calibration=False,
                            )
                            # Фильтр: аутсайдеры с кэфом > 2.8 имеют плохой трек-рекорд
                            # Также требуем разрыв модель/бук не более 2x (защита от ошибок ELO)
                            bcands = [
                                c for c in bcands
                                if (c.get("odds", 0) <= 2.8)
                                and (c.get("prob", 0) >= 55)
                            ]
                            bct = bm.get("commence_time", "")
                            for bc in bcands:
                                bc["sport"] = "basketball"
                                bc["league_name"] = bname
                                bc["commence_time"] = bct
                            cands.extend(bcands)
                            total += len(bcands)
                        except Exception as bce:
                            print(f"[CHIMERA BBALL] Ошибка {bm.get('home_team','')} vs {bm.get('away_team','')}: {bce}")
                print(f"[CHIMERA] Баскетбол: {total} кандидатов")
            except Exception as e:
                print(f"[CHIMERA] Баскетбол ошибка: {e}")
            return cands

        # ── Шаг 1: параллельная загрузка данных по сети ──────────────────
        from sports.basketball.core import BASKETBALL_LEAGUES as _BBALL_LEAGUES
        all_league_keys = [lk for lk, _ in FOOTBALL_LEAGUES] + [bk for bk, _ in _BBALL_LEAGUES]

        football_matches = []
        bball_raw = {bk: [] for bk, _ in _BBALL_LEAGUES}

        with _cf.ThreadPoolExecutor(max_workers=12) as pool:
            fball_futures = {pool.submit(_fetch_league, lk): lk for lk, _ in FOOTBALL_LEAGUES}
            bball_futures = {pool.submit(_fetch_bball_league, bk): bk for bk, _ in _BBALL_LEAGUES}

            for fut in _cf.as_completed(fball_futures):
                lkey, matches = fut.result()
                if lkey == "quota":
                    _scan_errors.append("quota")
                else:
                    football_matches.extend(matches)

            for fut in _cf.as_completed(bball_futures):
                bkey, matches = fut.result()
                bball_raw[bkey] = matches

        print(f"[CHIMERA] Всего матчей для скана: {len(football_matches)}")
        bball_data = [(bk, bn, bball_raw.get(bk, [])) for bk, bn in _BBALL_LEAGUES]

        # ── Шаг 2: параллельный скан всех видов спорта ───────────────────
        with _cf.ThreadPoolExecutor(max_workers=5) as pool:
            f_football   = pool.submit(_scan_football, football_matches)
            f_cs2        = pool.submit(_scan_cs2)
            f_tennis     = pool.submit(_scan_tennis)
            f_basketball = pool.submit(_scan_basketball, bball_data)
            f_hockey     = pool.submit(_scan_hockey)

            _sport_names = ["football", "cs2", "tennis", "basketball", "hockey"]
            candidates = []
            for _sname, fut in zip(_sport_names, [f_football, f_cs2, f_tennis, f_basketball, f_hockey]):
                try:
                    candidates.extend(fut.result(timeout=120))
                except Exception as e:
                    import traceback
                    print(f"[CHIMERA] Скан ошибка [{_sname}]: {type(e).__name__}: {e}")
                    traceback.print_exc()

        return candidates

    import functools
    loop = asyncio.get_running_loop()
    all_candidates = await loop.run_in_executor(None, _run_math_scan)

    # ── Сортируем, берём топ-3 для AI ────────────────────────────────────
    # Фильтр: EV > 5% и кэф >= 1.40 и не аномальный EV (> 80% = баг данных)
    # + минимальный CHIMERA Score (для футбола выше: есть xG+H2H; для остальных ниже)
    from config_thresholds import MIN_CHIMERA_SCORE as _MIN_CS
    _MIN_CS_OTHER = 38  # баскетбол/хоккей/теннис — нет xG и H2H → потолок на 18 очков ниже
    all_candidates = [
        c for c in all_candidates
        if c.get("ev", 0) > 5
        and c.get("odds", 0) >= 1.40
        and c.get("ev", 0) <= 80
        and c.get("chimera_score", 0) >= (
            _MIN_CS if c.get("sport") == "football" else _MIN_CS_OTHER
        )
    ]
    all_candidates.sort(key=lambda x: x["chimera_score"], reverse=True)
    top_candidates = all_candidates[:3]
    print(f"[CHIMERA] Кандидатов найдено: {len(all_candidates)}, топ-3 scores: {[round(c['chimera_score'],1) for c in top_candidates]}")

    if not top_candidates:
        _signals_scan_in_progress = False
        if "quota" in _scan_errors:
            await status_msg.edit_text(
                "⚠️ <b>CHIMERA SIGNAL</b>\n\n"
                "Футбольные матчи временно недоступны.\n\n"
                "<i>Попробуй позже или воспользуйся разделами CS2 и Теннис.</i>",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(
                "📊 <b>CHIMERA SIGNAL</b>\n\nСегодня матчей с ценностью не найдено.\nПопробуйте позже.",
                parse_mode="HTML"
            )
        return

    # ── Шаг 2/3: Новости + AI верификация ────────────────────────────────
    await status_msg.edit_text(
        "🔍 <b>CHIMERA SIGNAL</b>\n\n"
        "✅ Шаг 1/3: Матчи загружены\n"
        f"📰 Шаг 2/3: Собираю новости и запускаю AI для топ-{len(top_candidates)}...\n"
        "<i>⏳ Ещё 20–50 секунд...</i>",
        parse_mode="HTML"
    )

    # Параллельно тянем новости для каждого кандидата
    def _fetch_news_for_candidates():
        import concurrent.futures as _cf_news
        from oracle_ai import oracle_analyze
        def _get_news(c):
            try:
                res = oracle_analyze(c.get("home", ""), c.get("away", ""))
                summaries = []
                for team, data in res.items():
                    headlines = [a.get("title", "") for a in data.get("articles", [])[:2]]
                    if headlines:
                        summaries.append(f"{team}: {'; '.join(headlines)}")
                c["news_context"] = " | ".join(summaries)[:400] if summaries else ""
            except Exception:
                c["news_context"] = ""
        with _cf_news.ThreadPoolExecutor(max_workers=3) as _pool:
            list(_pool.map(_get_news, top_candidates))

    try:
        await loop.run_in_executor(None, _fetch_news_for_candidates)
    except Exception as _ne:
        print(f"[CHIMERA News] Ошибка: {_ne}")

    try:
        top_candidates = await loop.run_in_executor(
            None,
            functools.partial(
                run_ai_verification,
                top_candidates,
                gpt_client=_gpt_client,
                groq_client=_groq_client,
            )
        )
    except Exception as e:
        print(f"[CHIMERA AI] Ошибка верификации: {e}")

    # ── Итоговый вывод ────────────────────────────────────────────────────
    # Сохраняем топ-кандидатов в БД для трекинга результатов
    _chimera_top_pred_id = None
    _chimera_top_sport   = "football"
    _chimera_top_odds = 0
    for _ci, _cand in enumerate(top_candidates):
        try:
            _c_sport = _cand.get("sport", "football")
            _c_home  = _cand.get("home", "")
            _c_away  = _cand.get("away", "")
            _c_team  = _cand.get("team", "")
            _c_odds  = _cand.get("odds", 0)
            _c_time  = _cand.get("commence_time", "")
            _c_rec   = "home_win" if _c_team == _c_home else "away_win"
            _c_odds_h = _c_odds if _c_rec == "home_win" else 0
            _c_odds_a = _c_odds if _c_rec == "away_win" else 0
            _mid = f"chimera_{_c_home}_{_c_away}_{_c_time[:10]}"
            _saved_id = save_prediction(
                sport=_c_sport,
                match_id=_mid,
                match_date=_c_time,
                home_team=_c_home,
                away_team=_c_away,
                league=_cand.get("league_name", _c_sport),
                recommended_outcome=_c_rec,
                bet_signal="СТАВИТЬ",
                bookmaker_odds_home=_c_odds_h if _c_odds_h > 1 else None,
                bookmaker_odds_away=_c_odds_a if _c_odds_a > 1 else None,
                ensemble_home=round(_cand.get("prob", 50) / 100, 3),
                ensemble_away=round(1 - _cand.get("prob", 50) / 100, 3),
                ensemble_best_outcome=_c_rec,
            )
            # Если запись уже есть (UNIQUE конфликт) — берём существующий ID
            if not _saved_id:
                from database import _get_db_connection
                _tbl = {"football": "football_predictions", "cs2": "cs2_predictions",
                        "tennis": "tennis_predictions", "basketball": "basketball_predictions"}.get(_c_sport, "football_predictions")
                with _get_db_connection() as _conn:
                    _row = _conn.execute(f"SELECT id FROM {_tbl} WHERE match_id=?", (_mid,)).fetchone()
                    if _row:
                        _saved_id = _row[0]
            _cand["_pred_id"] = _saved_id  # сохраняем для кнопок альтернатив
            if _ci == 0:  # запоминаем только топ-1 для кнопки
                _chimera_top_pred_id = _saved_id
                _chimera_top_sport = _c_sport
                _chimera_top_odds = _c_odds
        except Exception as _cs_err:
            print(f"[CHIMERA Save] {_cs_err}")

    # ── Сохраняем в кеш на 45 минут ──────────────────────────────────────
    import time as _time_mod2
    _signals_scan_cache["last"] = {
        "ts":         _time_mod2.time(),
        "candidates": top_candidates,
        "top_pred_id": _chimera_top_pred_id,
        "top_sport":   _chimera_top_sport,
        "top_odds":    _chimera_top_odds,
    }
    print(f"[CHIMERA] Результаты скана закешированы на {SIGNALS_SCAN_TTL // 60} мин")
    _signals_scan_in_progress = False  # снять блокировку

    try:
        _broll_new = get_user_bankroll(message.from_user.id) or 0
        result_text = _format_chimera_page(top_candidates, 0, bankroll=_broll_new)
        _chimera_kb = _build_chimera_kb(
            top_candidates, _chimera_top_pred_id, _chimera_top_sport,
            _chimera_top_odds, message.from_user.id
        )
        await status_msg.edit_text(result_text, parse_mode="HTML", reply_markup=_chimera_kb)
    except Exception as _fmt_e:
        logger.error(f"[CHIMERA] Ошибка отправки: {_fmt_e}")
        # Fallback — без AI-блока, только числа
        best = top_candidates[0] if top_candidates else {}
        fallback = (
            f"🎯 <b>CHIMERA SIGNAL</b>\n\n"
            f"<b>{best.get('home','')} vs {best.get('away','')}</b>\n"
            f"📌 {best.get('team','')} ({best.get('outcome','')})\n"
            f"💰 Кэф: <b>{best.get('odds','?')}</b> | "
            f"Вероятность: <b>{best.get('prob','?')}%</b>\n"
            f"📈 Score: <b>{best.get('chimera_score',0):.0f}/100</b>"
        ) if best else "📊 Сигналов нет"
        await status_msg.edit_text(fallback, parse_mode="HTML")

# --- 11. Запуск бота ---

def _check_api_keys() -> list:
    """Проверяет наличие всех API ключей. Возвращает список предупреждений."""
    from config import TELEGRAM_TOKEN as _tok, THE_ODDS_API_KEY as _odds
    try:
        from config import OPENAI_API_KEY as _oai, GROQ_API_KEY as _groq
    except ImportError:
        _oai, _groq = "", ""
    warnings_list = []
    if not _tok:
        warnings_list.append("❌ TELEGRAM_TOKEN не задан")
    if not _odds:
        warnings_list.append("❌ THE_ODDS_API_KEY не задан — матчи не загрузятся")
    if not _oai:
        warnings_list.append("⚠️ OPENAI_API_KEY не задан — GPT агенты недоступны")
    if not _groq:
        warnings_list.append("⚠️ GROQ_API_KEY не задан — Llama недоступна")
    return warnings_list


def _send_crash_alert(error_text: str):
    """Синхронная отправка алерта о падении бота через HTTP (без asyncio)."""
    try:
        import requests as _req
        msg = f"🔴 <b>Chimera AI УПАЛ!</b>\n\n<code>{error_text[:500]}</code>"
        for uid in ADMIN_IDS:
            try:
                _req.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": uid, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
            except Exception:
                pass
    except Exception:
        pass


async def _notify_admins(bot, text: str):
    """Отправляет сообщение всем администраторам."""
    for uid in ADMIN_IDS:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
        except Exception:
            pass


async def main():
    import signal as _signal

    # Fallback роутер подключается последним — handle_text и handle_callback
    # должны быть уже задекорированы к этому моменту
    dp.include_router(_fallback_router)

    bot = Bot(token=TELEGRAM_TOKEN)

    # Проверка API ключей при старте
    key_warnings = _check_api_keys()
    if key_warnings:
        for w in key_warnings:
            logger.warning(f"[Startup] {w}")
        print("\n".join(["[!] " + w for w in key_warnings]))

    # Инициализируем breakers для Odds API
    get_breaker("odds_api", max_failures=5, recovery_timeout=600)

    # Graceful shutdown на Linux/Mac серверах
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        async def _graceful_shutdown(sig_name: str):
            logger.info(f"[Shutdown] Получен {sig_name}, завершаю работу...")
            await _notify_admins(bot, f"🟡 <b>Chimera AI</b> остановлен (сигнал {sig_name})")
            await dp.stop_polling()
        for _sig in (_signal.SIGTERM, _signal.SIGINT):
            loop.add_signal_handler(
                _sig,
                lambda s=_sig: asyncio.create_task(_graceful_shutdown(s.name))
            )

    asyncio.create_task(run_hltv_update_task())
    asyncio.create_task(check_results_task(bot))
    asyncio.create_task(auto_elo_recalibration_task())
    asyncio.create_task(auto_refresh_matches_task())
    asyncio.create_task(run_tennis_form_prefetch_task())
    asyncio.create_task(run_calibration_task())

    # Уведомляем о запуске
    startup_msg = "🟢 <b>Chimera AI запущен</b>"
    if key_warnings:
        startup_msg += "\n\n" + "\n".join(key_warnings)
    await _notify_admins(bot, startup_msg)

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"[CRASH] Бот упал: {e}", exc_info=True)
        _send_crash_alert(str(e))
        raise
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
