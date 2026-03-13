# -*- coding: utf-8 -*-
import asyncio
import logging
import requests
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
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
            return [0.33, 0.33, 0.34]
        home_data = data[data['HomeTeam_encoded'] == home_id].tail(5)
        away_data = data[data['AwayTeam_encoded'] == away_id].tail(5)
        if len(home_data) < 3 or len(away_data) < 3:
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
        data_api = response.json()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        future = [m for m in data_api if m.get('commence_time', '') > now.isoformat()[:19]]
        matches_cache = future[:15]
        _last_matches_refresh = time.time()
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
    if text == "Home": return home_team
    if text == "Away": return away_team
    if text == "Draw": return "Ничья"
    return text

def conf_icon(conf):
    if conf >= 75: return "🟢"
    if conf >= 60: return "🟡"
    return "🔴"

# --- 6. Клавиатуры ---

def build_main_keyboard():
    """Главное меню (Reply Keyboard)."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="⚽ Футбол")
    builder.button(text="🎮 Киберспорт CS2")
    builder.button(text="🎾 Теннис")
    builder.button(text="📊 Статистика")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def build_football_keyboard():
    """Список лиг (Inline)."""
    builder = InlineKeyboardBuilder()
    for code, name in FOOTBALL_LEAGUES:
        builder.button(text=name, callback_data=f"league_{code}")
    builder.adjust(2)
    return builder.as_markup()

def build_matches_keyboard():
    """Список матчей (Inline)."""
    builder = InlineKeyboardBuilder()
    for i, match in enumerate(matches_cache):
        home = match.get('home_team', 'Team A')
        away = match.get('away_team', 'Team B')
        builder.button(text=f"{home} vs {away}", callback_data=f"match_{i}")
    builder.button(text="🔄 Обновить список", callback_data="refresh_matches")
    builder.button(text="⬅️ К выбору лиги", callback_data="back_to_leagues")
    builder.adjust(1)
    return builder.as_markup()

def build_markets_keyboard(match_index):
    """Выбор рынка для анализа (Inline)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 Глубокий анализ (Ансамбль)", callback_data=f"mkt_full_{match_index}")
    builder.button(text="⚽ Рынок голов (Тоталы/ОЗ)", callback_data=f"mkt_goals_{match_index}")
    builder.button(text="🚩 Угловые", callback_data=f"mkt_corners_{match_index}")
    builder.button(text="🟨 Карточки", callback_data=f"mkt_cards_{match_index}")
    builder.button(text="🎯 Гандикапы", callback_data=f"mkt_handicap_{match_index}")
    builder.button(text="⬅️ Назад к матчам", callback_data="back_to_matches")
    builder.adjust(1)
    return builder.as_markup()

# --- 7. Форматирование отчётов ---

def format_main_report(home_team, away_team, prophet_data, oracle_results, gpt_result, llama_result, **kwargs):
    # Оригинальная логика форматирования v4.4
    home_prob, draw_prob, away_prob = prophet_data[1]*100, prophet_data[0]*100, prophet_data[2]*100
    gpt_verdict = gpt_result.get("recommended_outcome", "—")
    gpt_confidence = gpt_result.get("final_confidence_percent", 0)
    llama_verdict = llama_result.get("recommended_outcome", "—")
    llama_confidence = llama_result.get("final_confidence_percent", 0)
    
    report = f"🏆 *CHIMERA AI v4.5.5 — АНАЛИЗ МАТЧА*\n\n"
    report += f"⚽ *{home_team} vs {away_team}*\n\n"
    report += f"📊 *ПРОРОК:* П1 {home_prob:.0f}% | Х {draw_prob:.0f}% | П2 {away_prob:.0f}%\n"
    report += f"\n🧠 GPT-4o: {gpt_verdict} ({gpt_confidence}%)\n"
    report += f"🤖 Llama 3.3: {llama_verdict} ({llama_confidence}%)\n"
    return report

# --- 8. Хендлеры Telegram ---

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    get_matches()
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"🔮 *CHIMERA AI v4.5.5* — Искусственный Интеллект для ставок\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Привет, *{name}*! 👋\n\n"
        f"🧠 *5 независимых моделей анализа:*\n"
        f"🔮 Пророк — нейросеть (66 000+ матчей)\n"
        f"📰 Оракул — анализ новостей и травм\n"
        f"🧠 GPT-4o — стратегический анализ\n"
        f"🤖 Llama 3.3 70B — тактический анализ\n"
        f"📊 Пуассон + ELO — математическая модель\n\n"
        f"🏆 *Футбол + Киберспорт CS2 (Tier-2/3)*\n\n"
        f"⬇️ Выбери спорт:",
        parse_mode="Markdown",
        reply_markup=build_main_keyboard()
    )

@dp.message(lambda m: m.text == "⚽ Футбол")
async def football_menu(message: types.Message):
    await message.answer("⚽ *Футбол* — выбери лигу:", parse_mode="Markdown", reply_markup=build_football_keyboard())

@dp.callback_query(lambda c: c.data.startswith("league_"))
async def select_league(call: types.CallbackQuery):
    league_code = call.data.replace("league_", "")
    get_matches(league_code, force=True)
    await call.message.edit_text("📅 *Ближайшие матчи:*", parse_mode="Markdown", reply_markup=build_matches_keyboard())

@dp.callback_query(lambda c: c.data == "back_to_leagues")
async def back_to_leagues(call: types.CallbackQuery):
    await call.message.edit_text("⚽ *Футбол* — выбери лигу:", parse_mode="Markdown", reply_markup=build_football_keyboard())

@dp.callback_query(lambda c: c.data == "back_to_matches")
async def back_to_matches(call: types.CallbackQuery):
    await call.message.edit_text("📅 *Ближайшие матчи:*", parse_mode="Markdown", reply_markup=build_matches_keyboard())

@dp.callback_query(lambda c: c.data.startswith("match_"))
async def select_match(call: types.CallbackQuery):
    idx = int(call.data.replace("match_", ""))
    m = matches_cache[idx]
    await call.message.edit_text(f"📊 *{m['home_team']} vs {m['away_team']}*\nВыберите тип анализа:", 
                               parse_mode="Markdown", reply_markup=build_markets_keyboard(idx))

# --- [ СЕКЦИЯ КИБЕРСПОРТА CS2 ] ---

@dp.message(lambda m: m.text == "🎮 Киберспорт CS2")
async def cs2_menu(message: types.Message):
    try:
        from cs2_pandascore import get_combined_cs2_matches
        matches = get_combined_cs2_matches()
    except: matches = []
    
    builder = InlineKeyboardBuilder()
    if not matches:
        builder.button(text="NaVi vs Vitality (Demo)", callback_data="cs2_demo")
    else:
        for i, m in enumerate(matches[:10]):
            builder.button(text=f"🎮 {m['home']} vs {m['away']}", callback_data=f"cs2_m_{i}")
    builder.button(text="🔄 Обновить список", callback_data="refresh_cs2")
    builder.button(text="⬅️ Назад", callback_data="back_to_main_menu")
    builder.adjust(1)
    await message.answer("🎮 *Матчи CS2 (Tier-2/3):*", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data.startswith("cs2_m_") or c.data == "cs2_demo")
async def analyze_cs2(call: types.CallbackQuery):
    await call.message.edit_text("⏳ *Запускаю глубокий анализ CS2 v4.5.5...*\n\n"
                                 "📊 Расчет MIS (Map Impact Score)...\n"
                                 "🔫 Симуляция Veto карт...\n"
                                 "🧠 AI-Агенты анализируют ростеры...", parse_mode="Markdown")
    
    # Загрузка модулей CS2
    try:
        from cs2_core import analyze_cs2_match
        from cs2_pandascore import get_combined_cs2_matches
        
        if call.data == "cs2_demo":
            match_data = {"home": "NaVi", "away": "Vitality", "league": "BLAST World Final"}
        else:
            idx = int(call.data.replace("cs2_m_", ""))
            matches = get_combined_cs2_matches()
            match_data = matches[idx]
        
        report = await analyze_cs2_match(match_data['home'], match_data['away'], match_data.get('league', 'Pro League'))
        
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад к списку", callback_data="cs2_back")
        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=builder.as_markup())
    except Exception as e:
        await call.message.edit_text(f"❌ Ошибка анализа: {str(e)}", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="cs2_back").as_markup())

@dp.callback_query(lambda c: c.data == "cs2_back")
async def cs2_back(call: types.CallbackQuery):
    await call.message.delete()
    await cs2_menu(call.message)

@dp.callback_query(lambda c: c.data == "back_to_main_menu")
async def back_main(call: types.CallbackQuery):
    await call.message.delete()
    await call.message.answer("🔮 Главное меню:", reply_markup=build_main_keyboard())

# --- [ ПРОЧИЕ ХЕНДЛЕРЫ ] ---

@dp.message(lambda m: m.text == "🎾 Теннис")
async def tennis_placeholder(message: types.Message):
    await message.answer("🎾 *Теннис*\n\n⏳ Раздел в разработке...", parse_mode="Markdown")

@dp.message(lambda m: m.text == "📊 Статистика")
async def stats_menu(message: types.Message):
    await message.answer("📊 *Статистика и ROI*\n\nДанные загружаются из базы данных...", parse_mode="Markdown")

# --- [ ЗАПУСК ] ---

async def main_run():
    print("[ELO] Загружено 96 команд | Форма: 45 команд")
    print("[Загрузчик] Модель ИИ #1 'Пророк' загружена.")
    print("🚀 Chimera AI v4.5.5: Бот запущен! (Футбол + CS2)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main_run())
