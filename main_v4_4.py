# -*- coding: utf-8 -*-
import asyncio
import logging
import requests
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
from agents import (
    run_statistician_agent, run_scout_agent, run_arbitrator_agent,
    run_llama_agent, run_goals_market_agent,
    run_corners_market_agent, run_cards_market_agent, run_handicap_market_agent,
    run_mixtral_agent, build_math_ensemble, calculate_value_bets
)
from math_model import (
    load_elo_ratings, save_elo_ratings, update_elo, elo_win_probabilities,
    load_team_form, get_form_string, get_form_bonus,
    poisson_match_probabilities, calculate_expected_goals, format_math_report
)
# Загружаем ELO рейтинги и форму при старте
_elo_ratings = load_elo_ratings()
_team_form = load_team_form()
print(f"[ELO] Загружено {len(_elo_ratings)} команд | Форма: {len(_team_form)} команд")

def update_elo_after_match(home_team: str, away_team: str, home_score: int, away_score: int):
    """Обновляет ELO рейтинги после матча и сохраняет на диск."""
    global _elo_ratings
    old_home = _elo_ratings.get(home_team, 1500)
    old_away = _elo_ratings.get(away_team, 1500)
    _elo_ratings = update_elo(home_team, away_team, home_score, away_score, _elo_ratings)
    save_elo_ratings(_elo_ratings)
    new_home = _elo_ratings.get(home_team, 1500)
    new_away = _elo_ratings.get(away_team, 1500)
    print(f"[ELO] {home_team}: {old_home} → {new_home} | {away_team}: {old_away} → {new_away}")

from api_football import get_match_stats
try:
    from understat_stats import format_xg_stats, get_team_xg_stats
    UNDERSTAT_AVAILABLE = True
except ImportError:
    UNDERSTAT_AVAILABLE = False
    def format_xg_stats(h, a, s='2024'): return ""
    def get_team_xg_stats(t, s='2024'): return None
from database import init_db, save_prediction, get_statistics, get_pending_predictions, update_result, get_recent_predictions
try:
    from injuries import get_match_injuries, get_match_injuries_async
    INJURIES_AVAILABLE = True
except ImportError:
    INJURIES_AVAILABLE = False
    def get_match_injuries(h, a): return {}, {}, ""
    async def get_match_injuries_async(h, a): return {}, {}, ""

# --- 1. Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')

# --- 2. Загрузка модели Пророка ---
try:
    prophet_model = tf.keras.models.load_model("prophet_model.keras")
    print("[Загрузчик] Модель ИИ #1 'Пророк' загружена.")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось загрузить модель: {e}")
    prophet_model = None

try:
    import json
    data = pd.read_csv("all_matches_featured.csv", index_col=0)
    feature_cols = [c for c in data.columns if c not in ('FTR','label','HomeTeam','AwayTeam')]
    scaler = MinMaxScaler()
    scaler.fit(data[feature_cols])
    with open('team_encoder.json', 'r', encoding='utf-8') as _f:
        team_encoder = json.load(_f)
    print(f"[Загрузчик] Датасет и скалер готовы. Команд в энкодере: {len(team_encoder)}")
except Exception as e:
    print(f"[Загрузчик] Датасет не найден (не критично): {e}")
    data = None
    scaler = None
    team_encoder = {}

# --- 3. Инициализация базы данных ---
init_db()

# --- 4. Глобальный кэш матчей и анализов ---
matches_cache = []
analysis_cache = {}  # Хранит результаты анализа по match_id

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
            print(f"[Пророк] Команды не найдены: '{home_team}'→'{home_norm}', '{away_team}'→'{away_norm}'")
            print(f"[Пророк] Доступные: {list(team_encoder.keys())}")
            return [0.33, 0.33, 0.34]
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

# Список лиг для загрузки матчей
FOOTBALL_LEAGUES = [
    ("soccer_epl",                    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ"),
    ("soccer_spain_la_liga",           "🇪🇸 Ла Лига"),
    ("soccer_germany_bundesliga",      "🇩🇪 Бундеслига"),
    ("soccer_italy_serie_a",           "🇮🇹 Серия А"),
    ("soccer_france_ligue_one",        "🇫🇷 Лига 1"),
    ("soccer_uefa_champs_league",      "🏆 Лига Чемпионов"),
    ("soccer_uefa_europa_league",      "🥈 Лига Европы"),
    ("soccer_netherlands_eredivisie",  "🇳🇱 Эредивизи"),
    ("soccer_portugal_primeira_liga",  "🇵🇹 Примейра"),
    ("soccer_turkey_super_league",     "🇹🇷 Суперлига"),
]

# Текущая выбранная лига
_current_league = "soccer_epl"
_last_matches_refresh = 0  # timestamp последнего обновления

def get_matches(league: str = None, force: bool = False):
    """Получает список ближайших матчей через The Odds API для выбранной лиги."""
    global matches_cache, _last_matches_refresh, _current_league
    import time
    if league:
        _current_league = league
    # Автообновление каждые 6 часов
    if not force and matches_cache and (time.time() - _last_matches_refresh) < 21600:
        return matches_cache
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{_current_league}/odds/"
        params = {
            "apiKey": THE_ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Фильтруем только будущие матчи
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        future = [m for m in data if m.get('commence_time', '') > now.isoformat()[:19]]
        matches_cache = future[:15]
        _last_matches_refresh = time.time()
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, _current_league)
        print(f"[API] {league_name}: получено {len(matches_cache)} матчей.")
        return matches_cache
    except Exception as e:
        print(f"[API Ошибка] {e}")
        return matches_cache

def get_bookmaker_odds(match_data):
    """Извлекает коэффициенты П1/Х/П2 и тотал голов из данных матча."""
    result = {"home_win": 0, "draw": 0, "away_win": 0,
              "over_2_5": 0, "under_2_5": 0,
              "over_1_5": 0, "under_1_5": 0}
    try:
        for bookmaker in match_data.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h" and result["home_win"] == 0:
                    outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
                    result["home_win"] = outcomes.get(match_data["home_team"], 0)
                    result["away_win"] = outcomes.get(match_data["away_team"], 0)
                    result["draw"] = outcomes.get("Draw", 0)
                elif market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        point = outcome.get("point", 0)
                        name = outcome.get("name", "")
                        price = outcome.get("price", 0)
                        if point == 2.5 and name == "Over" and result["over_2_5"] == 0:
                            result["over_2_5"] = price
                        elif point == 2.5 and name == "Under" and result["under_2_5"] == 0:
                            result["under_2_5"] = price
                        elif point == 1.5 and name == "Over" and result["over_1_5"] == 0:
                            result["over_1_5"] = price
                        elif point == 1.5 and name == "Under" and result["under_1_5"] == 0:
                            result["under_1_5"] = price
    except Exception as e:
        print(f"[API Ошибка коэффициентов] {e}")
    return result

def translate_outcome(text, home_team="Хозяева", away_team="Гости"):
    """Переводит исход с английского на русский с названиями команд."""
    if not text:
        return "Нет данных"
    text_lower = text.lower()
    if "home" in text_lower and "win" in text_lower:
        return f"{home_team} (хозяева)"
    if "away" in text_lower and "win" in text_lower:
        return f"{away_team} (гости)"
    if "draw" in text_lower or "ничья" in text_lower:
        return "Ничья"
    if "хозяев" in text_lower or "хозяева" in text_lower:
        return f"{home_team} (хозяева)"
    if "гостей" in text_lower or "гость" in text_lower or "гости" in text_lower:
        return f"{away_team} (гости)"
    if "победа хозяев" in text_lower:
        return f"{home_team} (хозяева)"
    if "победа гостей" in text_lower:
        return f"{away_team} (гости)"
    return text

def conf_icon(c):
    """Иконка уверенности."""
    if c >= 70: return "🟢"
    elif c >= 55: return "🟡"
    return "🔴"

# --- 6. Клавиатуры ---

def build_main_keyboard():
    """Строит главную клавиатуру с секциями спорта."""
    kb = [
        [types.KeyboardButton(text="⚽ Футбол")],
        [types.KeyboardButton(text="🎾 Теннис"), types.KeyboardButton(text="🎮 Киберспорт CS2")],
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="💎 VIP-доступ")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def build_football_keyboard():
    """Клавиатура футбольного меню с выбором лиги."""
    builder = InlineKeyboardBuilder()
    for league_key, league_name in FOOTBALL_LEAGUES:
        builder.button(text=league_name, callback_data=f"league_{league_key}")
    builder.button(text="⬅️ Назад", callback_data="back_to_main")
    builder.adjust(2)
    return builder.as_markup()

def build_matches_keyboard(matches):
    """Строит клавиатуру со списком матчей с датой и временем."""
    from datetime import datetime, timezone, timedelta
    builder = InlineKeyboardBuilder()
    for i, match in enumerate(matches):
        # Форматируем дату
        time_str = ""
        ct = match.get('commence_time', '')
        if ct:
            try:
                dt = datetime.fromisoformat(ct.replace('Z', '+00:00'))
                moscow_tz = timezone(timedelta(hours=3))
                dt_m = dt.astimezone(moscow_tz)
                time_str = f" [{dt_m.strftime('%d.%m %H:%M')}]"
            except Exception:
                pass
        builder.button(
            text=f"⚽ {match['home_team']} vs {match['away_team']}{time_str}",
            callback_data=f"m_{i}"
        )
    builder.button(text="🔄 Обновить список", callback_data="refresh_matches")
    builder.button(text="🏆 Сменить лигу", callback_data="change_league")
    builder.adjust(1)
    return builder.as_markup()

def build_markets_keyboard(match_index):
    """Строит клавиатуру выбора рынка ставок."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Победитель матча", callback_data=f"mkt_winner_{match_index}")
    builder.button(text="⚽ Голы (тотал 2.5 / обе забьют)", callback_data=f"mkt_goals_{match_index}")
    builder.button(text="⚖️ Гандикапы / Двойной шанс", callback_data=f"mkt_handicap_{match_index}")
    builder.button(text="⬅️ Выбрать другой матч", callback_data="back_to_matches")
    builder.adjust(1)
    return builder.as_markup()

def build_back_to_markets_keyboard(match_index):
    """Кнопка возврата к выбору рынка."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Другой рынок", callback_data=f"show_markets_{match_index}")
    builder.button(text="⬅️ Выбрать другой матч", callback_data="back_to_matches")
    builder.adjust(1)
    return builder.as_markup()

# --- 7. Форматирование отчётов ---

def format_main_report(home_team, away_team, prophet_data, oracle_results, gpt_result, llama_result,
                       mixtral_result=None, poisson_probs=None, elo_probs=None, ensemble_probs=None,
                       home_xg_stats=None, away_xg_stats=None, value_bets=None, injuries_block=None,
                       match_time=None):
    """Форматирует главный отчёт анализа матча с полным математическим анализом."""

    home_prob = prophet_data[1] * 100
    draw_prob = prophet_data[0] * 100
    away_prob = prophet_data[2] * 100

    home_sentiment_score = oracle_results.get(home_team, {}).get('sentiment', 0)
    away_sentiment_score = oracle_results.get(away_team, {}).get('sentiment', 0)
    home_sentiment_label = "🟢 Позитивный" if home_sentiment_score > 0.1 else ("🔴 Негативный" if home_sentiment_score < -0.1 else "⚪ Нейтральный")
    away_sentiment_label = "🟢 Позитивный" if away_sentiment_score > 0.1 else ("🔴 Негативный" if away_sentiment_score < -0.1 else "⚪ Нейтральный")

    gpt_verdict_raw = gpt_result.get("recommended_outcome", "Нет данных")
    gpt_verdict = translate_outcome(gpt_verdict_raw, home_team, away_team)
    gpt_confidence = gpt_result.get("final_confidence_percent", 0)
    gpt_summary = gpt_result.get("final_verdict_summary", "")
    gpt_odds = gpt_result.get("bookmaker_odds", 0)
    gpt_stake = gpt_result.get("recommended_stake_percent", 0)
    gpt_ev = gpt_result.get("expected_value_percent", 0)
    bet_signal = gpt_result.get("bet_signal", "ПРОПУСТИТЬ")
    signal_reason = gpt_result.get("signal_reason", "")

    llama_verdict_raw = llama_result.get("recommended_outcome", "Нет данных")
    llama_verdict = translate_outcome(llama_verdict_raw, home_team, away_team)
    llama_confidence = llama_result.get("final_confidence_percent", gpt_confidence)
    llama_summary = llama_result.get("analysis_summary", "")
    llama_total = llama_result.get("total_goals_prediction", "—")
    llama_total_reason = llama_result.get("total_goals_reasoning", "")
    llama_btts = llama_result.get("both_teams_to_score_prediction", "—")

    # Mixtral агент
    mixtral_verdict_raw = ""
    mixtral_verdict = ""
    mixtral_confidence = 0
    mixtral_summary = ""
    if mixtral_result and not mixtral_result.get('error'):
        mixtral_verdict_raw = mixtral_result.get("recommended_outcome", "")
        mixtral_verdict = translate_outcome(mixtral_verdict_raw, home_team, away_team)
        mixtral_confidence = mixtral_result.get("final_confidence_percent", 0)
        mixtral_summary = mixtral_result.get("analysis_summary", "")

    # Консенсус всех агентов
    all_verdicts = [v for v in [gpt_verdict_raw, llama_verdict_raw, mixtral_verdict_raw] if v]
    def _outcome_key(v):
        v = v.lower()
        if 'хозяев' in v or 'home' in v: return 'home'
        if 'гостей' in v or 'away' in v: return 'away'
        return 'draw'
    outcome_counts = {}
    for v in all_verdicts:
        k = _outcome_key(v)
        outcome_counts[k] = outcome_counts.get(k, 0) + 1
    max_count = max(outcome_counts.values()) if outcome_counts else 0
    if max_count >= 2:
        agreement_text = f"✅ {max_count}/{len(all_verdicts)} агентов согласны!"
    else:
        agreement_text = "⚠️ Агенты расходятся во мнениях"

    # Проверяем конфликт между ансамблем и GPT
    conflict_warning = ""
    ensemble_best_key = None  # будет установлен ниже в блоке ансамбля
    if ensemble_probs:
        _probs_tmp = {k: ensemble_probs.get(k, 0) for k in ['home', 'draw', 'away']}
        ensemble_best_key = max(_probs_tmp, key=_probs_tmp.get)
    if ensemble_best_key:
        gpt_key = _outcome_key(gpt_verdict_raw)
        if gpt_key != ensemble_best_key:
            ens_label = {'home': f'П1 ({home_team})', 'draw': 'Ничья', 'away': f'П2 ({away_team})'}[ensemble_best_key]
            conflict_warning = f"⚠️ КОНФЛИКТ: GPT рекомендует {gpt_verdict}, а математика указывает на {ens_label}"

    if bet_signal == "СТАВИТЬ":
        signal_icon = "🔥 СИГНАЛ: СТАВИТЬ!"
    elif value_bets:
        # Главный исход не рекомендован, но есть value ставки
        best_vb = value_bets[0]
        signal_icon = f"💰 СИГНАЛ: VALUE СТАВКА! {best_vb['outcome']} @ {best_vb['odds']} (EV: +{best_vb['ev']}%)"
    else:
        signal_icon = "⏸ СИГНАЛ: ПРОПУСТИТЬ"

    # xG блок
    xg_block = ""
    if home_xg_stats or away_xg_stats:
        xg_lines = ["📊 *xG СТАТИСТИКА (Understat):*"]
        if home_xg_stats:
            xg_lines.append(
                f"🏠 {home_team}: xG={home_xg_stats.get('avg_xg_last5','?')} | "
                f"xGA={home_xg_stats.get('avg_xga_last5','?')} | "
                f"Форма: {home_xg_stats.get('form_last5','?')}"
            )
        if away_xg_stats:
            xg_lines.append(
                f"✈️ {away_team}: xG={away_xg_stats.get('avg_xg_last5','?')} | "
                f"xGA={away_xg_stats.get('avg_xga_last5','?')} | "
                f"Форма: {away_xg_stats.get('form_last5','?')}"
            )
        xg_block = "\n".join(xg_lines)

    # Пуассон блок
    poisson_block = ""
    if poisson_probs:
        # Индикатор источника данных
        src = poisson_probs.get('data_source', 'fallback')
        if src == 'understat':
            src_icon = "🟢"  # зелёный = реальные данные
            src_label = "Understat ✅"
        elif src == 'partial':
            src_icon = "🟡"  # жёлтый = частичные данные
            src_label = "частичные данные ⚠️"
        else:
            src_icon = "🔴"  # красный = резервные значения
            src_label = "среднелиговые ❌"
        home_exp = poisson_probs.get('home_exp', '?')
        away_exp = poisson_probs.get('away_exp', '?')
        poisson_block = (
            f"🎯 *ПУАССОН (xG-модель):* {src_icon} _{src_label}_\n"
            f" Хозяев xG: {home_exp} | Гости xG: {away_exp}\n"
            f" П1: {round(poisson_probs['home_win']*100)}% | Х: {round(poisson_probs['draw']*100)}% | П2: {round(poisson_probs['away_win']*100)}%\n"
            f" Тотал >2.5: {round(poisson_probs['over_25']*100)}% | Обе забьют: {round(poisson_probs['btts']*100)}%\n"
            f" Счёт: {poisson_probs['most_likely_score']} ({round(poisson_probs['most_likely_score_prob']*100)}%)"
        )

    # ELO блок
    elo_block = ""
    if elo_probs:
        h_form = elo_probs.get('home_form', '')
        a_form = elo_probs.get('away_form', '')
        h_bonus = elo_probs.get('home_form_bonus', 0)
        a_bonus = elo_probs.get('away_form_bonus', 0)
        h_bonus_str = f" ({h_bonus:+.0f})" if h_bonus != 0 else ""
        a_bonus_str = f" ({a_bonus:+.0f})" if a_bonus != 0 else ""
        form_line = ""
        if h_form and h_form != '?????':
            form_line = f"\n Форма: {home_team}: {h_form}{h_bonus_str} | {away_team}: {a_form}{a_bonus_str}"
        elo_block = (
            f"⚡ *ELO РЕЙТИНГ + ФОРМА:*\n"
            f" {home_team}: {elo_probs.get('home_elo',1500)} | {away_team}: {elo_probs.get('away_elo',1500)}{form_line}\n"
            f" ELO П1: {round(elo_probs.get('home',0)*100)}% | Х: {round(elo_probs.get('draw',0)*100)}% | П2: {round(elo_probs.get('away',0)*100)}%"
        )

    # Ансамбль блок
    ensemble_block = ""
    ensemble_best_key = None
    if ensemble_probs:
        probs = {k: ensemble_probs.get(k, 0) for k in ['home', 'draw', 'away']}
        sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)
        best_key, best_val = sorted_probs[0]
        second_val = sorted_probs[1][1]
        gap = best_val - second_val

        best_outcome_map = {'home': f'П1 ({home_team})', 'draw': 'Ничья', 'away': f'П2 ({away_team})'}
        best_outcome_label = best_outcome_map[best_key]
        best_prob = round(best_val * 100)
        ensemble_best_key = best_key

        # Индикатор уверенности преимущества
        if gap >= 0.10:
            conf_label = "🟢 чёткое преимущество"
        elif gap >= 0.05:
            conf_label = "🟡 небольшое преимущество"
        else:
            conf_label = "🔴 равный матч"

        weights = ensemble_probs.get('weights', {})
        w_str = f"Пуассон {round(weights.get('poisson',0)*100)}%+ELO {round(weights.get('elo',0)*100)}%+AI {round(weights.get('ai',0)*100)}%+Бук {round(weights.get('bookmaker',0)*100)}%+Пр {round(weights.get('prophet',0)*100)}%" if weights else ""
        ensemble_block = (
            f"🔢 *АНСАМБЛЬ (взвешенный):*\n"
            f" П1: {round(probs['home']*100)}% | Х: {round(probs['draw']*100)}% | П2: {round(probs['away']*100)}%\n"
            f" {conf_label}: *{best_outcome_label}* ({best_prob}%)\n"
            f" _Веса: {w_str}_"
        )

    # Value bets блок
    value_block = ""
    if value_bets:
        vlines = ["💰 *VALUE СТАВКИ (ансамбль):*"]
        for vb in value_bets[:3]:  # Показываем топ-3
            vlines.append(
                f" ✅ *{vb['outcome']}* @ {vb['odds']} — наша вероятность: {vb['our_prob']}% vs бук: {vb['book_prob']}%"
            )
            vlines.append(
                f"   EV: +{vb['ev']}% | Келли: {vb['kelly']}% от банка"
            )
        value_block = "\n".join(vlines)

    # Mixtral блок
    mixtral_block = ""
    if mixtral_result and not mixtral_result.get('error') and mixtral_summary:
        mixtral_block = f"🔮 *Mixtral 8x7B:*\n_{mixtral_summary}_\n\n⚔️ Вердикт: {mixtral_verdict} ({mixtral_confidence}%)"

    # Собираем блоки
    math_section = ""
    math_parts = [p for p in [xg_block, poisson_block, elo_block, ensemble_block] if p]
    if math_parts:
        math_section = "\n\n".join(math_parts)

    # Форматируем дату матча
    match_time_str = ""
    if match_time:
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromisoformat(match_time.replace('Z', '+00:00'))
            # Переводим в Московское время (UTC+3)
            moscow_tz = timezone(timedelta(hours=3))
            dt_moscow = dt.astimezone(moscow_tz)
            match_time_str = dt_moscow.strftime('%d.%m.%Y %H:%M МСК')
        except Exception:
            match_time_str = str(match_time)[:16]

    report = f"""
🏆 *CHIMERA AI v4.3 — АНАЛИЗ МАТЧА*
━━━━━━━━━━━━━━━━━━━━━━━━━

⚽ *{home_team} vs {away_team}*
{(f'📅 *{match_time_str}*') if match_time_str else ''}

📊 *ПРОРОК (нейросеть):*
 П1: {home_prob:.0f}% | Х: {draw_prob:.0f}% | П2: {away_prob:.0f}%

🗣 *ОРАКУЛ (новостной фон):*
 {home_team}: {home_sentiment_label}
 {away_team}: {away_sentiment_label}
{(chr(10) + injuries_block) if injuries_block else ""}
{(chr(10) + math_section) if math_section else ""}
━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *GPT-4o (Маэстро):*
_{gpt_summary}_

🤖 *Llama 3.3 70B:*
_{llama_summary}_
{(chr(10) + mixtral_block) if mixtral_block else ""}
━━━━━━━━━━━━━━━━━━━━━━━━━
⚖️ *ВЕРДИКТ МАЭСТРО:*
{conf_icon(gpt_confidence)} Исход: {gpt_verdict}
{conf_icon(gpt_confidence)} Уверенность: {gpt_confidence}%
🎯 Коэффициент: {gpt_odds}
💰 Ставка (Келли): {gpt_stake:.1f}% от депозита
📈 Ожидаемая ценность: +{gpt_ev:.1f}%

🤖 *ВЕРДИКТ Llama 3.3 70B:*
{conf_icon(llama_confidence)} Исход: {llama_verdict}
{conf_icon(llama_confidence)} Уверенность: {llama_confidence}%
⚽ Тотал: {llama_total} _{llama_total_reason}_
🥅 Обе забьют: {llama_btts}
{(chr(10) + value_block) if value_block else ""}
━━━━━━━━━━━━━━━━━━━━━━━━━
{agreement_text}
{(chr(10) + conflict_warning) if conflict_warning else ""}
*{signal_icon}*
_{signal_reason}_

"""
    return report.strip()

def format_goals_report(home_team, away_team, goals_result, bookmaker_odds=None):
    """Форматирует отчёт по рынку голов."""
    if bookmaker_odds is None:
        bookmaker_odds = {}
    summary = goals_result.get("summary", "")
    over_2_5 = goals_result.get("total_over_2_5", "—")
    over_2_5_conf = goals_result.get("total_over_2_5_confidence", 0)
    over_2_5_reason = goals_result.get("total_over_2_5_reason", "")
    over_1_5 = goals_result.get("total_over_1_5", "—")
    over_1_5_conf = goals_result.get("total_over_1_5_confidence", 0)
    btts = goals_result.get("btts", "—")
    btts_conf = goals_result.get("btts_confidence", 0)
    btts_reason = goals_result.get("btts_reason", "")
    first_goal = goals_result.get("first_goal", "—")
    best_bet = goals_result.get("best_goals_bet", "")

    # Реальные коэффициенты из API
    real_over_2_5 = bookmaker_odds.get("over_2_5", 0)
    real_under_2_5 = bookmaker_odds.get("under_2_5", 0)
    real_over_1_5 = bookmaker_odds.get("over_1_5", 0)

    # Формируем строку с коэффициентами если они есть
    odds_2_5_str = f" | КФ: Больше={real_over_2_5} / Меньше={real_under_2_5}" if real_over_2_5 else ""
    odds_1_5_str = f" | КФ: {real_over_1_5}" if real_over_1_5 else ""

    return f"""
⚽ *АНАЛИЗ ГОЛОВ — {home_team} vs {away_team}*
━━━━━━━━━━━━━━━━━━━━━━━━━

_{summary}_

📊 *ТОТАЛ ГОЛОВ:*
{conf_icon(over_2_5_conf)} Тотал 2.5: *{over_2_5}* ({over_2_5_conf}%){odds_2_5_str}
_{over_2_5_reason}_

{conf_icon(over_1_5_conf)} Тотал 1.5: *{over_1_5}* ({over_1_5_conf}%){odds_1_5_str}

🥅 *ОБЕ ЗАБЬЮТ:*
{conf_icon(btts_conf)} Обе забьют: *{btts}* ({btts_conf}%)
_{btts_reason}_

🎯 *КТО ЗАБЬЁТ ПЕРВЫМ:* {first_goal}

━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 *ЛУЧШАЯ СТАВКА НА ГОЛЫ:*
_{best_bet}_
""".strip()

def format_corners_report(home_team, away_team, corners_result):
    """Форматирует отчёт по рынку угловых."""
    summary = corners_result.get("summary", "")
    total = corners_result.get("total_corners_over_9_5", "—")
    total_conf = corners_result.get("total_corners_confidence", 0)
    total_reason = corners_result.get("total_corners_reason", "")
    home_c = corners_result.get("home_corners_over_4_5", "—")
    away_c = corners_result.get("away_corners_over_4_5", "—")
    winner = corners_result.get("corners_winner", "—")
    best_bet = corners_result.get("best_corners_bet", "")

    return f"""
🚩 *АНАЛИЗ УГЛОВЫХ — {home_team} vs {away_team}*
━━━━━━━━━━━━━━━━━━━━━━━━━

_{summary}_

📊 *ТОТАЛ УГЛОВЫХ:*
{conf_icon(total_conf)} Тотал 9.5: *{total}* ({total_conf}%)
_{total_reason}_

🏠 {home_team}: *{home_c}* угловых
✈️ {away_team}: *{away_c}* угловых
🏆 Больше угловых: *{winner}*

━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 *ЛУЧШАЯ СТАВКА НА УГЛОВЫЕ:*
_{best_bet}_
""".strip()

def format_cards_report(home_team, away_team, cards_result):
    """Форматирует отчёт по рынку карточек."""
    summary = cards_result.get("summary", "")
    total = cards_result.get("total_cards_over_3_5", "—")
    total_conf = cards_result.get("total_cards_confidence", 0)
    total_reason = cards_result.get("total_cards_reason", "")
    red = cards_result.get("red_card", "—")
    red_conf = cards_result.get("red_card_confidence", 0)
    more_cards = cards_result.get("more_cards_team", "—")
    best_bet = cards_result.get("best_cards_bet", "")

    return f"""
🟨 *АНАЛИЗ КАРТОЧЕК — {home_team} vs {away_team}*
━━━━━━━━━━━━━━━━━━━━━━━━━

_{summary}_

📊 *ТОТАЛ КАРТОЧЕК:*
{conf_icon(total_conf)} Тотал 3.5: *{total}* ({total_conf}%)
_{total_reason}_

🟥 Красная карточка: *{red}* ({red_conf}%)
🟨 Больше карточек: *{more_cards}*

━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 *ЛУЧШАЯ СТАВКА НА КАРТОЧКИ:*
_{best_bet}_
""".strip()

def format_handicap_report(home_team, away_team, handicap_result):
    """Форматирует отчёт по рынку гандикапов."""
    summary = handicap_result.get("summary", "")
    ah_home = handicap_result.get("asian_handicap_home", "—")
    ah_home_conf = handicap_result.get("asian_handicap_home_confidence", 0)
    ah_away = handicap_result.get("asian_handicap_away", "—")
    ah_away_conf = handicap_result.get("asian_handicap_away_confidence", 0)
    dc = handicap_result.get("double_chance", "—")
    dc_reason = handicap_result.get("double_chance_reason", "")
    best_bet = handicap_result.get("best_handicap_bet", "")

    return f"""
⚖️ *ГАНДИКАПЫ — {home_team} vs {away_team}*
━━━━━━━━━━━━━━━━━━━━━━━━━

_{summary}_

📊 *АЗИАТСКИЙ ГАНДИКАП:*
{conf_icon(ah_home_conf)} {home_team} -0.5: *{ah_home}* ({ah_home_conf}%)
{conf_icon(ah_away_conf)} {away_team} +0.5: *{ah_away}* ({ah_away_conf}%)

🎯 *ДВОЙНОЙ ШАНС:*
Рекомендация: *{dc}*
_{dc_reason}_

━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 *ЛУЧШАЯ СТАВКА НА ГАНДИКАП:*
_{best_bet}_
""".strip()

# --- 8. Хендлеры Telegram ---
dp = Dispatcher()

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    get_matches()
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"🔮 *CHIMERA AI v4.3* — Искусственный Интеллект для ставок\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Привет, *{name}*! 👋\n\n"
        f"🧠 *5 независимых моделей анализа:*\n"
        f"🔮 Пророк — нейросеть (66 000+ матчей)\n"
        f"📰 Оракул — анализ новостей и травм\n"
        f"🧠 GPT-4o — стратегический анализ\n"
        f"🤖 Llama 3.3 70B — тактический анализ\n"
        f"📊 Пуассон + ELO — математическая модель\n\n"
        f"🏆 *10 лиг футбола:* АПЛ, Ла Лига, Бундеслига, Серия А, Лига 1, ЛЧ и др.\n\n"
        f"⬇️ Выбери спорт:",
        parse_mode="Markdown",
        reply_markup=build_main_keyboard()
    )

@dp.message()
async def handle_text(message: types.Message):
    text = message.text

    if text == "⚽ Футбол":
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "АПЛ")
        await message.answer(
            f"⚽ *Футбол* — выбери лигу:\n"
            f"Текущая: *{league_name}*",
            parse_mode="Markdown",
            reply_markup=build_football_keyboard()
        )

    elif text == "🎾 Теннис":
        await message.answer(
            "🎾 *Теннис*\n\n"
            "⏳ Раздел в разработке...\n\n"
            "Скоро здесь появится анализ матчей ATP, WTA и др.",
            parse_mode="Markdown"
        )

    elif text == "🎮 Киберспорт CS2":
        await message.answer(
            "🎮 *Киберспорт CS2*\n\n"
            "⏳ Раздел в разработке...\n\n"
            "Скоро здесь появится анализ матчей Major, ESL и др.",
            parse_mode="Markdown"
        )

    elif text == "📊 Статистика":
        stats = get_statistics()
        total = stats['total']
        checked = stats['checked']
        pending = stats['pending']
        correct = stats['correct']
        winner_acc = stats['winner_accuracy']
        goals_acc = stats['goals_accuracy']
        btts_acc = stats['btts_accuracy']
        goals_checked = stats['goals_checked']
        btts_checked = stats['btts_checked']
        recent = stats['recent']
        monthly = stats['monthly']

        if total == 0:
            stats_text = (
                "📊 *Статистика Chimera AI*\n\n"
                "Пока нет сохранённых прогнозов.\n"
                "Сделайте первый анализ матча!"
            )
        else:
            acc_icon = "🟢" if winner_acc >= 60 else ("🟡" if winner_acc >= 50 else "🔴")
            stats_text = (
                f"📊 *Статистика прогнозов Chimera AI*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 Всего прогнозов: *{total}*\n"
                f"✅ Проверено: *{checked}* | ⏳ Ожидают: *{pending}*\n\n"
                f"🏆 *Победитель матча:*\n"
                f"{acc_icon} Угадано: *{correct}/{checked}* — *{winner_acc:.1f}%*\n\n"
            )
            if goals_checked > 0:
                g_icon = "🟢" if goals_acc >= 60 else ("🟡" if goals_acc >= 50 else "🔴")
                stats_text += f"⚽ *Тотал голов:* {g_icon} *{goals_acc:.1f}%* ({goals_checked} проверено)\n"
            if btts_checked > 0:
                b_icon = "🟢" if btts_acc >= 60 else ("🟡" if btts_acc >= 50 else "🔴")
                stats_text += f"🥅 *Обе забьют:* {b_icon} *{btts_acc:.1f}%* ({btts_checked} проверено)\n"

            # Последние результаты
            if recent:
                stats_text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━\n📋 *Последние результаты:*\n"
                for r in recent[:5]:
                    h, a, hs, as_, pred, ok, _ = r
                    if hs is not None:
                        icon = "✅" if ok == 1 else "❌"
                        stats_text += f"{icon} {h} {hs}:{as_} {a}\n"
                    else:
                        stats_text += f"⏳ {h} vs {a} — ожидает результата\n"

            # По месяцам
            if monthly:
                stats_text += "\n📅 *По месяцам:*\n"
                for month, m_total, m_correct in monthly:
                    if m_total > 0:
                        m_acc = (m_correct / m_total * 100)
                        m_icon = "🟢" if m_acc >= 60 else ("🟡" if m_acc >= 50 else "🔴")
                        stats_text += f"{m_icon} {month}: {m_correct}/{m_total} ({m_acc:.0f}%)\n"

        await message.answer(stats_text, parse_mode="Markdown")

    elif text == "💎 VIP-доступ":
        await message.answer(
            "💎 *VIP-доступ*\n\n"
            "Уже доступно бесплатно:\n"
            "✅ 10 лиг футбола\n"
            "✅ 5 моделей анализа\n"
            "✅ Травмы и дисквалификации\n"
            "✅ Value ставки с EV\n\n"
            "В разработке:\n"
            "⏳ Утренние авто-сигналы\n"
            "⏳ Теннис и CS2\n"
            "⏳ Личная статистика ROI",
            parse_mode="Markdown"
        )

@dp.callback_query()
async def handle_callback(call: types.CallbackQuery):

    # --- Выбор лиги ---
    if call.data.startswith("league_"):
        league_key = call.data[7:]
        league_name = dict(FOOTBALL_LEAGUES).get(league_key, league_key)
        matches = get_matches(league=league_key, force=True)
        if not matches:
            await call.answer(f"❌ Нет матчей для {league_name}. Попробуйте позже.", show_alert=True)
            return
        await call.message.edit_text(
            f"⚽ *{league_name}* — ближайшие матчи:\nВыберите матч для анализа:",
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

    # --- Возврат к списку матчей ---
    elif call.data == "back_to_matches":
        if not matches_cache:
            get_matches()
        await call.message.edit_text("Выберите матч для анализа:", reply_markup=build_matches_keyboard(matches_cache))

    # --- Обновление матчей ---
    elif call.data == "refresh_matches":
        matches = get_matches(force=True)
        if not matches:
            await call.answer("❌ Не удалось обновить матчи.", show_alert=True)
            return
        league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "")
        await call.message.edit_text(
            f"✅ Список обновлён! {league_name}: {len(matches)} матчей.",
            reply_markup=build_matches_keyboard(matches)
        )

    # --- Показать меню рынков ---
    elif call.data.startswith("show_markets_"):
        match_index = int(call.data.split("_")[2])
        if match_index >= len(matches_cache):
            await call.answer("Матч не найден.", show_alert=True)
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
            )
            await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_markets_keyboard(match_index))

    # --- Выбор матча для анализа ---
    elif call.data.startswith("m_"):
        match_index = int(call.data.split("_")[1])
        if match_index >= len(matches_cache):
            await call.answer("Матч не найден. Обновите список.", show_alert=True)
            return

        match = matches_cache[match_index]
        home_team = match["home_team"]
        away_team = match["away_team"]

        await call.message.edit_text(
            f"⏳ *Запускаю анализ матча...*\n\n"
            f"⚽ {home_team} vs {away_team}\n\n"
            f"🔮 Пророк... ✅\n"
            f"📰 Оракул (поиск новостей)...\n"
            f"📊 xG + Пуассон + ELO...",
            parse_mode="Markdown"
        )

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

        await call.message.edit_text(
            f"⏳ *Запускаю анализ матча...*\n\n"
            f"⚽ {home_team} vs {away_team}\n\n"
            f"🔮 Пророк... ✅\n"
            f"📰 Оракл... ✅\n"
            f"📊 xG + Пуассон + ELO... ✅\n"
            f"🧠 GPT-4o анализирует...",
            parse_mode="Markdown"
        )

        bookmaker_odds = get_bookmaker_odds(match)

        # Получаем реальную статистику команд из API-Football
        team_stats_text = get_match_stats(home_team, away_team)
        if team_stats_text:
            print(f"[API-Football] Статистика получена для {home_team} vs {away_team}")
        else:
            print(f"[API-Football] Статистика недоступна для {home_team} vs {away_team}")

        # Получаем xG статистику из Understat (если доступна)
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

        stats_result = run_statistician_agent(prophet_data, team_stats_text)
        scout_result = run_scout_agent(home_team, away_team, news_summary)
        gpt_result = run_arbitrator_agent(stats_result, scout_result, bookmaker_odds)

        await call.message.edit_text(
            f"⏳ *Запускаю анализ матча...*\n\n"
            f"⚽ {home_team} vs {away_team}\n\n"
            f"🔮 Пророк... ✅\n"
            f"📰 Оракл... ✅\n"
            f"📊 xG + Пуассон + ELO... ✅\n"
            f"🧠 GPT-4o... ✅\n"
            f"🤖 Llama 3.3 70B анализирует...\n"
            f"🔮 Mixtral 8x7B анализирует...",
            parse_mode="Markdown"
        )

        llama_result = run_llama_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds, team_stats_text)

        # Третий агент: Mixtral 8x7B
        mixtral_result = run_mixtral_agent(
            home_team, away_team, prophet_data, news_summary, bookmaker_odds,
            team_stats_text, poisson_probs, elo_probs
        )

        # Взвешенный ансамбль всех моделей
        ensemble_probs = None
        value_bets = []
        try:
            ensemble_probs = build_math_ensemble(
                prophet_data, poisson_probs, elo_probs,
                gpt_result, llama_result, mixtral_result,
                bookmaker_odds
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
        # Определяем лучший исход ансамбля для сохранения
        ens_best_key = max(['home', 'draw', 'away'], key=lambda k: (ensemble_probs or {}).get(k, 0)) if ensemble_probs else ""
        ens_best_map = {'home': home_team, 'draw': 'Ничья', 'away': away_team}
        ens_best_label = ens_best_map.get(ens_best_key, "") if ens_best_key else ""

        prediction_data = {
            "gpt_verdict": gpt_result.get("recommended_outcome", ""),
            "llama_verdict": llama_result.get("recommended_outcome", ""),
            "mixtral_verdict": (mixtral_result or {}).get("recommended_outcome", ""),
            "gpt_confidence": gpt_result.get("final_confidence_percent", 0),
            "llama_confidence": llama_result.get("final_confidence_percent", 0),
            "mixtral_confidence": (mixtral_result or {}).get("final_confidence_percent", 0),
            "bet_signal": gpt_result.get("bet_signal", ""),
            "total_goals": llama_result.get("total_goals_prediction", ""),
            "btts": llama_result.get("both_teams_to_score_prediction", ""),
            "odds_home": bookmaker_odds.get("home_win", 0),
            "odds_draw": bookmaker_odds.get("draw", 0),
            "odds_away": bookmaker_odds.get("away_win", 0),
            "odds_over25": bookmaker_odds.get("over_2_5", 0),
            "odds_under25": bookmaker_odds.get("under_2_5", 0),
            # Математические модели
            "poisson_probs": poisson_probs,
            "elo_probs": elo_probs,
            "ensemble_probs": ensemble_probs,
            "ensemble_best_outcome": ens_best_label,
            "value_bets": value_bets,
            "league": match.get('sport_key', 'soccer_epl'),
        }
        save_prediction(
            match['id'],
            match.get('commence_time', ''),
            home_team, away_team,
            prediction_data
        )

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
        )

        await call.message.edit_text(
            final_report,
            parse_mode="Markdown",
            reply_markup=build_markets_keyboard(match_index)
        )

    # --- Рынок: Победитель ---
    elif call.data.startswith("mkt_winner_"):
        match_index = int(call.data.split("_")[2])
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

        signal_icon = "🔥 СТАВИТЬ!" if bet_signal == "СТАВИТЬ" else "⏸ ПРОПУСТИТЬ"

        report = f"""
🏆 *ПОБЕДИТЕЛЬ МАТЧА*
{home_team} vs {away_team}
━━━━━━━━━━━━━━━━━━━━━━━━━

📊 *Пророк (нейросеть):*
 П1: {prophet_data[1]*100:.0f}% | Х: {prophet_data[0]*100:.0f}% | П2: {prophet_data[2]*100:.0f}%

⚖️ *Вердикт GPT-4o:*
{conf_icon(gpt_conf)} {gpt_verdict} — {gpt_conf}%
🎯 Коэф: {gpt_odds_val} | Ставка: {gpt_stake:.1f}% | EV: +{gpt_ev:.1f}%

🤖 *Вердикт Llama 3.3 70B:*
{conf_icon(llama_conf)} {llama_verdict} — {llama_conf}%

━━━━━━━━━━━━━━━━━━━━━━━━━
*{signal_icon}*
_{signal_reason}_
""".strip()

        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))

    # --- Рынок: Голы ---
    elif call.data.startswith("mkt_goals_"):
        match_index = int(call.data.split("_")[2])
        cached = analysis_cache.get(match_index)
        if not cached:
            await call.answer("Сначала запустите анализ матча.", show_alert=True)
            return

        await call.message.edit_text("⏳ *Анализирую рынок голов...*", parse_mode="Markdown")

        goals_result = run_goals_market_agent(
            cached["home_team"], cached["away_team"],
            cached["prophet_data"], cached["news_summary"],
            cached["bookmaker_odds"], cached["gpt_result"], cached["llama_result"]
        )
        report = format_goals_report(cached["home_team"], cached["away_team"], goals_result, cached["bookmaker_odds"])
        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))


    # --- Рынок: Гандикапы ---
    elif call.data.startswith("mkt_handicap_"):
        match_index = int(call.data.split("_")[2])
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

# --- 9. Проверка результатов ---

# Список лиг для проверки результатов
SCORES_LEAGUES = [
    "soccer_epl",           # АПЛ
    "soccer_spain_la_liga", # Ла Лига
    "soccer_germany_bundesliga",  # Бундеслига
    "soccer_italy_serie_a",       # Серия А
    "soccer_france_ligue_one",    # Лига 1
    "soccer_uefa_champs_league",  # Лига Чемпионов
]

async def fetch_scores_for_league(league: str) -> dict:
    """Получает результаты матчей для одной лиги. Возвращает dict {match_id: (home_score, away_score)}."""
    results = {}
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/scores/"
        params = {"apiKey": THE_ODDS_API_KEY, "daysFrom": 4, "dateFormat": "iso"}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            for s in r.json():
                if s.get('completed'):
                    sc = s.get('scores', [])
                    home_score = away_score = None
                    teams = s.get('home_team', ''), s.get('away_team', '')
                    for sc_item in sc:
                        if sc_item['name'] == teams[0]:
                            home_score = int(sc_item['score'])
                        elif sc_item['name'] == teams[1]:
                            away_score = int(sc_item['score'])
                    if home_score is not None and away_score is not None:
                        results[s['id']] = (home_score, away_score)
        elif r.status_code == 422:
            pass  # Лига недоступна в текущем плане API
    except Exception as e:
        print(f"[Результаты] Ошибка лиги {league}: {e}")
    return results


async def check_results_task(bot: Bot):
    """Периодически проверяет результаты сыгранных матчей по всем лигам."""
    while True:
        try:
            pending = get_pending_predictions()
            if pending:
                print(f"[Результаты] Проверяю {len(pending)} матчей без результата...")

                # Собираем результаты по всем лигам
                all_scores = {}
                # Группируем pending по лигам
                leagues_needed = set(p.get('league', 'soccer_epl') for p in pending)
                # Всегда проверяем все лиги из списка
                for league in SCORES_LEAGUES:
                    scores = await fetch_scores_for_league(league)
                    all_scores.update(scores)
                    await asyncio.sleep(0.5)  # Не спамим API

                print(f"[Результаты] Получено {len(all_scores)} завершённых матчей из API")

                for pred in pending:
                    match_id = pred['match_id']
                    home = pred['home_team']
                    away = pred['away_team']

                    if match_id in all_scores:
                        home_score, away_score = all_scores[match_id]
                        try:
                            result = update_result(match_id, home_score, away_score)
                            if result:
                                icon = "✅" if result['is_correct'] else "❌"
                                ens_icon = ""
                                if result.get('is_ensemble_correct') is not None:
                                    ens_icon = " [Анс: ✅]" if result['is_ensemble_correct'] else " [Анс: ❌]"
                                vb_icon = ""
                                if result.get('vb_correct') is not None:
                                    vb_icon = " [VB: ✅]" if result['vb_correct'] else " [VB: ❌]"
                                print(f"[Результаты] {icon} {home} {home_score}:{away_score} {away}{ens_icon}{vb_icon}")

                                # Авто-обновление ELO рейтинга после матча
                                try:
                                    update_elo_after_match(home, away, home_score, away_score)
                                except Exception as _elo_e:
                                    print(f"[ELO] Ошибка обновления: {_elo_e}")
                        except Exception as e:
                            print(f"[Результаты] Ошибка обновления {home} vs {away}: {e}")
                    else:
                        print(f"[Результаты] Нет данных для {home} vs {away} (id={match_id})")

        except Exception as e:
            print(f"[Результаты] Общая ошибка: {e}")
        await asyncio.sleep(3600)  # Проверяем каждый час

@dp.message(Command("results"))
async def cmd_results(message: types.Message):
    """Команда /results — полная статистика с ROI и точностью по моделям."""
    stats = get_statistics()
    recent = stats['recent']
    pending = stats['pending']
    checked = stats['checked']
    winner_acc = stats['winner_accuracy']

    if not recent and checked == 0:
        await message.answer(
            "📋 *Трекер результатов*\n\n"
            "Пока нет проверенных матчей.\n"
            "Результаты проверяются автоматически каждый час после окончания матча.",
            parse_mode="Markdown"
        )
        return

    def acc_icon(acc):
        return "🟢" if acc >= 60 else ("🟡" if acc >= 50 else "🔴")

    def roi_icon(roi):
        return "🟢" if roi > 0 else "🔴"

    # Точность по моделям
    ens_acc = stats.get('ens_accuracy', 0)
    ens_checked = stats.get('ens_checked', 0)
    vb_acc = stats.get('vb_accuracy', 0)
    vb_checked = stats.get('vb_checked', 0)
    goals_acc = stats.get('goals_accuracy', 0)
    goals_checked = stats.get('goals_checked', 0)
    btts_acc = stats.get('btts_accuracy', 0)
    btts_checked = stats.get('btts_checked', 0)
    roi_vb = stats.get('roi_value_bets', 0)
    roi_main = stats.get('roi_main', 0)

    text = (
        f"📊 *CHIMERA AI — Трекер результатов*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 *Точность по моделям:*\n"
        f"{acc_icon(winner_acc)} Исход (GPT): *{winner_acc:.1f}%* ({stats['correct']}/{checked})\n"
    )
    if ens_checked > 0:
        text += f"{acc_icon(ens_acc)} Ансамбль: *{ens_acc:.1f}%* ({round(ens_acc/100*ens_checked)}/{ens_checked})\n"
    if goals_checked > 0:
        text += f"{acc_icon(goals_acc)} Тотал голов: *{goals_acc:.1f}%* ({round(goals_acc/100*goals_checked)}/{goals_checked})\n"
    if btts_checked > 0:
        text += f"{acc_icon(btts_acc)} Обе забьют: *{btts_acc:.1f}%* ({round(btts_acc/100*btts_checked)}/{btts_checked})\n"
    if vb_checked > 0:
        text += f"{acc_icon(vb_acc)} Value ставки: *{vb_acc:.1f}%* ({round(vb_acc/100*vb_checked)}/{vb_checked})\n"

    text += f"\n💰 *ROI (прибыль/убыток):*\n"
    if roi_main != 0:
        text += f"{roi_icon(roi_main)} Основные ставки: *{roi_main:+.1f}* ед. банка\n"
    if roi_vb != 0:
        text += f"{roi_icon(roi_vb)} Value ставки: *{roi_vb:+.1f}* ед. банка\n"

    text += f"\n⏳ Ожидают результата: *{pending}*\n"

    # По месяцам
    monthly = stats.get('monthly', [])
    if monthly:
        text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━\n*По месяцам:*\n"
        for m in monthly[:4]:
            month, total, corr, ens_c, vb_c, roi_m = m
            m_acc = (corr / total * 100) if total > 0 else 0
            text += f"{acc_icon(m_acc)} {month}: {corr}/{total} ({m_acc:.0f}%)"
            if roi_m:
                text += f" | ROI VB: {roi_m:+.1f}"
            text += "\n"

    text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━\n*Последние матчи:*\n"
    for r in recent[:6]:
        h, a, hs, as_, pred, ok, date, ens_ok, vb_out, vb_ok, vb_odds = r
        if hs is not None:
            icon = "✅" if ok == 1 else "❌"
            ens_str = " [Анс:✅]" if ens_ok == 1 else (" [Анс:❌]" if ens_ok == 0 else "")
            vb_str = f" [VB {vb_out}@{vb_odds}:✅]" if vb_ok == 1 else (f" [VB:❌]" if vb_ok == 0 and vb_out else "")
            text += f"{icon} {h} *{hs}:{as_}* {a}{ens_str}{vb_str}\n"
            if pred:
                text += f"   _Прогноз: {pred}_\n"
        else:
            text += f"⏳ {h} vs {a} — ждём результата\n"

    await message.answer(text, parse_mode="Markdown")

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


async def auto_refresh_matches_task():
    """Автоматически обновляет список матчей каждые 6 часов."""
    while True:
        await asyncio.sleep(21600)  # 6 часов
        try:
            matches = get_matches(force=True)
            league_name = dict(FOOTBALL_LEAGUES).get(_current_league, "")
            print(f"[Авто] Список матчей обновлён: {league_name} — {len(matches)} матчей")
        except Exception as e:
            print(f"[Авто] Ошибка обновления матчей: {e}")

# --- 11. Запуск бота ---
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    print("🚀 Chimera AI v4.4: Бот запущен! (10 лиг + Автообновление + Секции спорта)")
    asyncio.create_task(check_results_task(bot))
    asyncio.create_task(auto_elo_recalibration_task())
    asyncio.create_task(auto_refresh_matches_task())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
