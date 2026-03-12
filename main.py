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
    run_corners_market_agent, run_cards_market_agent, run_handicap_market_agent
)
from api_football import get_match_stats
from database import init_db, save_prediction, get_statistics, get_pending_predictions, update_result, get_recent_predictions

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
    "Sheffield Utd": "Sheffield United",
    "Brighton and Hove Albion": "Brighton",
    "Brighton & Hove Albion": "Brighton",
    "Tottenham Hotspur": "Tottenham",
    "Leicester City": "Leicester",
    "Aston Villa FC": "Aston Villa",
    "Ipswich Town": "Ipswich",
    "AFC Bournemouth": "Bournemouth",
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

def get_matches():
    """Получает список ближайших матчей через The Odds API."""
    global matches_cache
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
        params = {
            "apiKey": THE_ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        matches_cache = response.json()[:10]
        print(f"[API] Получено {len(matches_cache)} матчей.")
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
    """Строит главную клавиатуру."""
    kb = [
        [types.KeyboardButton(text="⚽ Выбрать матч для анализа")],
        [types.KeyboardButton(text="🔄 Обновить матчи")],
        [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="💎 VIP-доступ")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def build_matches_keyboard(matches):
    """Строит клавиатуру со списком матчей."""
    builder = InlineKeyboardBuilder()
    for i, match in enumerate(matches):
        builder.button(text=f"⚽ {match['home_team']} vs {match['away_team']}", callback_data=f"m_{i}")
    builder.button(text="🔄 Обновить список", callback_data="refresh_matches")
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

def format_main_report(home_team, away_team, prophet_data, oracle_results, gpt_result, llama_result):
    """Форматирует главный отчёт анализа матча."""

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

    models_agree = (gpt_verdict_raw.lower() in llama_verdict_raw.lower() or
                    llama_verdict_raw.lower() in gpt_verdict_raw.lower())
    agreement_text = "✅ Обе модели согласны!" if models_agree else "⚠️ Модели расходятся во мнениях"

    signal_icon = "🔥 СИГНАЛ: СТАВИТЬ!" if bet_signal == "СТАВИТЬ" else "⏸ СИГНАЛ: ПРОПУСТИТЬ"

    report = f"""
🏆 *CHIMERA AI v4.0 — АНАЛИЗ МАТЧА*
━━━━━━━━━━━━━━━━━━━━━━━━━

⚽ *{home_team} vs {away_team}*

📊 *ПРОРОК (нейросеть):*
 П1: {home_prob:.0f}% | Х: {draw_prob:.0f}% | П2: {away_prob:.0f}%

🗞 *ОРАКУЛ (новостной фон):*
 {home_team}: {home_sentiment_label}
 {away_team}: {away_sentiment_label}

━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *GPT-4o (Маэстро):*
_{gpt_summary}_

🤖 *Llama 3.3 70B:*
_{llama_summary}_

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

━━━━━━━━━━━━━━━━━━━━━━━━━
{agreement_text}
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
    await message.answer(
        "🔮 *Chimera AI v4.0* — профессиональный анализ футбольных матчей\n\n"
        "Используются 4 независимых ИИ:\n"
        "🔮 Пророк — нейросеть (66,000+ матчей)\n"
        "📰 Оракул — анализ новостей\n"
        "🧠 GPT-4o — стратегический анализ\n"
        "🤖 Llama 3.3 70B — второе независимое мнение\n\n"
        "После анализа выбирай рынок:\n"
        "🏆 Победитель | ⚽ Голы | 🚩 Угловые | 🟨 Карточки | ⚖️ Гандикапы",
        parse_mode="Markdown",
        reply_markup=build_main_keyboard()
    )

@dp.message()
async def handle_text(message: types.Message):
    text = message.text

    if text == "⚽ Выбрать матч для анализа":
        matches = get_matches()
        if not matches:
            await message.answer("❌ Не удалось загрузить матчи. Попробуйте позже.")
            return
        await message.answer("Выберите матч для анализа:", reply_markup=build_matches_keyboard(matches))

    elif text == "🔄 Обновить матчи":
        matches = get_matches()
        if not matches:
            await message.answer("❌ Не удалось обновить матчи.")
            return
        await message.answer(f"✅ Список обновлён! Найдено {len(matches)} матчей.", reply_markup=build_matches_keyboard(matches))

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
            "Расширенные функции в разработке.\n"
            "Скоро здесь появятся:\n"
            "• Анализ Ла Лиги, Бундеслиги, Серии А\n"
            "• Утренние авто-сигналы лучших матчей\n"
            "• Детальная статистика ROI",
            parse_mode="Markdown"
        )

@dp.callback_query()
async def handle_callback(call: types.CallbackQuery):

    # --- Возврат к списку матчей ---
    if call.data == "back_to_matches":
        if not matches_cache:
            get_matches()
        await call.message.edit_text("Выберите матч для анализа:", reply_markup=build_matches_keyboard(matches_cache))

    # --- Обновление матчей ---
    elif call.data == "refresh_matches":
        matches = get_matches()
        if not matches:
            await call.answer("❌ Не удалось обновить матчи.", show_alert=True)
            return
        await call.message.edit_text(f"✅ Список обновлён! Найдено {len(matches)} матчей.", reply_markup=build_matches_keyboard(matches))

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
                cached["gpt_result"], cached["llama_result"]
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
            f"📰 Оракул (поиск новостей)...",
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
            f"📰 Оракул... ✅\n"
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

        stats_result = run_statistician_agent(prophet_data, team_stats_text)
        scout_result = run_scout_agent(home_team, away_team, news_summary)
        gpt_result = run_arbitrator_agent(stats_result, scout_result, bookmaker_odds)

        await call.message.edit_text(
            f"⏳ *Запускаю анализ матча...*\n\n"
            f"⚽ {home_team} vs {away_team}\n\n"
            f"🔮 Пророк... ✅\n"
            f"📰 Оракул... ✅\n"
            f"🧠 GPT-4o... ✅\n"
            f"🤖 Llama 3.3 70B анализирует...",
            parse_mode="Markdown"
        )

        llama_result = run_llama_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds, team_stats_text)

        # Сохраняем в кэш для повторного использования при выборе рынков
        analysis_cache[match_index] = {
            "prophet_data": prophet_data,
            "oracle_results": oracle_results,
            "news_summary": news_summary,
            "bookmaker_odds": bookmaker_odds,
            "gpt_result": gpt_result,
            "llama_result": llama_result,
            "home_team": home_team,
            "away_team": away_team,
            "match": match,
            "team_stats_text": team_stats_text
        }

        # Сохранение в базу данных
        prediction_data = {
            "gpt_verdict": gpt_result.get("recommended_outcome", ""),
            "llama_verdict": llama_result.get("recommended_outcome", ""),
            "gpt_confidence": gpt_result.get("final_confidence_percent", 0),
            "llama_confidence": llama_result.get("final_confidence_percent", 0),
            "bet_signal": gpt_result.get("bet_signal", ""),
            "total_goals": llama_result.get("total_goals_prediction", ""),
            "btts": llama_result.get("both_teams_to_score_prediction", ""),
            "odds_home": bookmaker_odds.get("home_win", 0),
            "odds_draw": bookmaker_odds.get("draw", 0),
            "odds_away": bookmaker_odds.get("away_win", 0),
            "odds_over25": bookmaker_odds.get("over_2_5", 0),
            "odds_under25": bookmaker_odds.get("under_2_5", 0),
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
            gpt_result, llama_result
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

async def check_results_task(bot: Bot):
    """Периодически проверяет результаты сыгранных матчей через The Odds API."""
    while True:
        try:
            pending = get_pending_predictions()
            if pending:
                print(f"[Результаты] Проверяю {len(pending)} матчей без результата...")
                for pred in pending:
                    match_id = pred['match_id']
                    home = pred['home_team']
                    away = pred['away_team']
                    # Пробуем получить результат через scores endpoint
                    try:
                        url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/scores/"
                        params = {"apiKey": THE_ODDS_API_KEY, "daysFrom": 3, "dateFormat": "iso"}
                        r = requests.get(url, params=params, timeout=10)
                        if r.status_code == 200:
                            scores = r.json()
                            for s in scores:
                                if s.get('id') == match_id and s.get('completed'):
                                    sc = s.get('scores', [])
                                    home_score = None
                                    away_score = None
                                    for sc_item in sc:
                                        if sc_item['name'] == home:
                                            home_score = int(sc_item['score'])
                                        elif sc_item['name'] == away:
                                            away_score = int(sc_item['score'])
                                    if home_score is not None and away_score is not None:
                                        result = update_result(match_id, home_score, away_score)
                                        if result:
                                            icon = "✅" if result['is_correct'] else "❌"
                                            print(f"[Результаты] {icon} {home} {home_score}:{away_score} {away} — прогноз: {result['predicted']}")
                    except Exception as e:
                        print(f"[Результаты] Ошибка для {home} vs {away}: {e}")
        except Exception as e:
            print(f"[Результаты] Общая ошибка: {e}")
        await asyncio.sleep(3600)  # Проверяем каждый час

@dp.message(Command("results"))
async def cmd_results(message: types.Message):
    """Команда /results — показывает последние проверенные результаты."""
    stats = get_statistics()
    recent = stats['recent']
    pending = stats['pending']
    checked = stats['checked']
    winner_acc = stats['winner_accuracy']

    if not recent and checked == 0:
        await message.answer(
            "📋 *Результаты прогнозов*\n\n"
            "Пока нет проверенных матчей.\n"
            "Результаты проверяются автоматически каждый час после окончания матча.",
            parse_mode="Markdown"
        )
        return

    acc_icon = "🟢" if winner_acc >= 60 else ("🟡" if winner_acc >= 50 else "🔴")
    text = (
        f"📋 *Результаты прогнозов Chimera AI*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{acc_icon} Точность: *{winner_acc:.1f}%* ({stats['correct']}/{checked} угадано)\n"
        f"⏳ Ожидают результата: *{pending}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Последние матчи:*\n"
    )
    for r in recent[:8]:
        h, a, hs, as_, pred, ok, date = r
        if hs is not None:
            icon = "✅" if ok == 1 else "❌"
            text += f"{icon} {h} *{hs}:{as_}* {a}\n"
            if pred:
                text += f"   _Прогноз: {pred}_\n"
        else:
            text += f"⏳ {h} vs {a} — ждём результата\n"

    await message.answer(text, parse_mode="Markdown")

# --- 10. Запуск бота ---
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    print("🚀 Chimera AI v4.0: Бот запущен!")
    asyncio.create_task(check_results_task(bot))
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
