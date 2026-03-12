# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import requests
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импортируем наши модули
from config import TELEGRAM_TOKEN, THE_ODDS_API_KEY, OPENAI_API_KEY
from oracle_ai import oracle_analyze
from agents import run_statistician_agent, run_scout_agent, run_arbitrator_agent

# --- 1. Настройка ---
logging.basicConfig(level=logging.INFO)
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 2. Загрузка моделей и данных ---
PROPHET_MODEL_PATH = "prophet_model.keras"
DATA_PATH = "featured_football_data.csv"
prophet_model, featured_data, scaler, features_to_scale = None, None, None, []

try:
    prophet_model = tf.keras.models.load_model(PROPHET_MODEL_PATH)
    print("[Загрузчик] Модель ИИ #1 'Пророк' загружена.")
    featured_data = pd.read_csv(DATA_PATH)
    features_to_scale = [col for col in featured_data.columns if col.startswith(("H_", "A_"))]
    scaler = StandardScaler()
    scaler.fit(featured_data[features_to_scale])
    print("[Загрузчик] Датасет и скалер готовы.")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] {e}")

# --- 3. Кэш матчей ---
matches_cache = []

# --- 4. Функции ---
def get_prophet_prediction(home_team, away_team):
    if prophet_model is None or featured_data is None:
        return [0.33, 0.33, 0.33]
    try:
        last_10_games = featured_data.tail(10)
        scaled = scaler.transform(last_10_games[features_to_scale])
        seq = np.reshape(scaled, (1, 10, len(features_to_scale)))
        pred = prophet_model.predict(seq, verbose=0)[0]
        return [float(pred[0]), float(pred[1]), float(pred[2])]
    except Exception as e:
        print(f"[Пророк] Ошибка: {e}")
        return [0.33, 0.33, 0.33]

def fetch_matches():
    global matches_cache
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
        params = {"apiKey": THE_ODDS_API_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        matches_cache = response.json()[:10]
        print(f"[API] Получено {len(matches_cache)} матчей.")
        return matches_cache
    except Exception as e:
        print(f"[API Ошибка] {e}")
        return matches_cache

def get_bookmaker_odds(match_data):
    """Извлекает коэффициенты из данных матча."""
    try:
        for bookmaker in match_data.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
                    home = outcomes.get(match_data["home_team"], 0)
                    away = outcomes.get(match_data["away_team"], 0)
                    draw = outcomes.get("Draw", 0)
                    return {"home_win": home, "draw": draw, "away_win": away}
    except Exception:
        pass
    return {"home_win": 0, "draw": 0, "away_win": 0}

def build_main_keyboard():
    kb = [
        [types.KeyboardButton(text="⚽ Выбрать матч для анализа")],
        [types.KeyboardButton(text="🔄 Обновить матчи")],
        [types.KeyboardButton(text="💎 VIP-доступ"), types.KeyboardButton(text="📊 Статистика")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def build_matches_keyboard(matches):
    builder = InlineKeyboardBuilder()
    for i, match in enumerate(matches):
        builder.button(text=f"⚽ {match['home_team']} vs {match['away_team']}", callback_data=f"m_{i}")
    builder.button(text="🔄 Обновить список", callback_data="refresh_matches")
    builder.adjust(1)
    return builder.as_markup()

# Словарь перевода исходов с английского на русский
OUTCOME_TRANSLATE = {
    "Home Win": "Победа хозяев",
    "home win": "Победа хозяев",
    "home_win": "Победа хозяев",
    "Away Win": "Победа гостей",
    "away win": "Победа гостей",
    "away_win": "Победа гостей",
    "Draw": "Ничья",
    "draw": "Ничья",
}

def translate_outcome(text):
    """Переводит исход с английского на русский."""
    if not text:
        return "Нет данных"
    # Прямое совпадение
    if text in OUTCOME_TRANSLATE:
        return OUTCOME_TRANSLATE[text]
    # Частичное совпадение
    text_lower = text.lower()
    if "home" in text_lower and "win" in text_lower:
        return "Победа хозяев"
    if "away" in text_lower and "win" in text_lower:
        return "Победа гостей"
    if "draw" in text_lower or "ничья" in text_lower:
        return "Ничья"
    return text

def format_final_report(home_team, away_team, stats_result, scout_result, arbitrator_result):
    """Форматирует финальный отчёт для Telegram."""
    verdict_raw = arbitrator_result.get("recommended_outcome", "Нет данных")
    verdict = translate_outcome(verdict_raw)
    confidence = arbitrator_result.get("final_confidence_percent", 0)
    stake = arbitrator_result.get("recommended_stake_percent", 0)
    odds = arbitrator_result.get("bookmaker_odds", 0)
    ev = arbitrator_result.get("expected_value_percent", 0)
    summary = arbitrator_result.get("final_verdict_summary", "")

    # Иконка уверенности
    if confidence >= 70:
        conf_icon = "🟢"
    elif confidence >= 55:
        conf_icon = "🟡"
    else:
        conf_icon = "🔴"

    # Рекомендация по ставке
    if stake > 0:
        stake_text = f"💰 *Рекомендуемая ставка:* {stake:.1f}% от депозита"
        ev_text = f"📈 *Ожидаемая прибыль:* +{ev:.1f}% от ставки"
    else:
        stake_text = "💰 *Ставка:* Нет выгодного входа (нет Value Bet)"
        ev_text = ""

    report = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *ФИНАЛЬНЫЙ АНАЛИЗ CHIMERA AI*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ *{home_team}* vs *{away_team}*\n\n"
        f"📊 *СТАТИСТИКА (Пророк):*\n"
        f"  П1: {stats_result.get('home_win_prob', 0):.0%} | Х: {stats_result.get('draw_prob', 0):.0%} | П2: {stats_result.get('away_win_prob', 0):.0%}\n\n"
        f"📰 *НОВОСТНОЙ ФОН (Оракул):*\n"
        f"  {home_team}: {'🟢 Позитивный' if scout_result.get('home_team_sentiment', 0) > 0.1 else '🔴 Негативный' if scout_result.get('home_team_sentiment', 0) < -0.1 else '⚪ Нейтральный'}\n"
        f"  {away_team}: {'🟢 Позитивный' if scout_result.get('away_team_sentiment', 0) > 0.1 else '🔴 Негативный' if scout_result.get('away_team_sentiment', 0) < -0.1 else '⚪ Нейтральный'}\n\n"
        f"🧠 *АНАЛИЗ:*\n_{summary}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ *ВЕРДИКТ МАЭСТРО:*\n\n"
        f"{conf_icon} *Исход:* {verdict}\n"
        f"{conf_icon} *Уверенность ИИ:* {confidence}%\n"
        f"🎯 *Коэффициент:* {odds}\n"
        f"{stake_text}\n"
    )
    if ev_text:
        report += f"{ev_text}\n"
    report += "━━━━━━━━━━━━━━━━━━━━━━"
    return report

# --- 5. Обработчики ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🤖 *Добро пожаловать в Chimera AI!*\n\n"
        "Профессиональная система анализа матчей:\n\n"
        "🔮 *Пророк* — нейросеть на 30 годах истории\n"
        "📰 *Оракул* — новости, травмы, настроения\n"
        "⚖️ *Маэстро* — финальный вердикт + % от депозита\n\n"
        "Нажмите кнопку ниже, чтобы начать."
    )
    await message.answer(welcome_text, reply_markup=build_main_keyboard(), parse_mode="Markdown")

@dp.message(F.text.in_(["⚽ Выбрать матч для анализа", "🔄 Обновить матчи"]))
async def show_matches(message: types.Message):
    await message.answer("⏳ *Загружаю ближайшие матчи...*", parse_mode="Markdown")
    matches = fetch_matches()
    if not matches:
        await message.answer("😔 Не удалось получить матчи. Проверьте API-ключ или попробуйте позже.", reply_markup=build_main_keyboard())
        return
    await message.answer(
        f"📋 *Ближайшие матчи АПЛ ({len(matches)} шт.):*\n\nВыберите матч для анализа:",
        reply_markup=build_matches_keyboard(matches),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "refresh_matches")
async def refresh_matches_callback(callback: types.CallbackQuery):
    await callback.answer("🔄 Обновляю...")
    matches = fetch_matches()
    if not matches:
        await callback.message.edit_text("😔 Не удалось обновить матчи.")
        return
    await callback.message.edit_text(
        f"📋 *Ближайшие матчи АПЛ ({len(matches)} шт.):*\n\nВыберите матч для анализа:",
        reply_markup=build_matches_keyboard(matches),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("m_"))
async def analyze_match_callback(callback: types.CallbackQuery):
    idx = int(callback.data.split("_")[1])
    if idx >= len(matches_cache):
        await callback.answer("Матч не найден. Обновите список.", show_alert=True)
        return

    match = matches_cache[idx]
    home_team = match["home_team"]
    away_team = match["away_team"]
    bookmaker_odds = get_bookmaker_odds(match)

    await callback.message.edit_text(f"🔍 *Анализирую: {home_team} vs {away_team}*\n\n⏳ Это займёт ~30 секунд...", parse_mode="Markdown")
    await callback.answer()

    # --- ЭТАП 1: ПРОРОК (нейросеть) ---
    await callback.message.answer("🔮 *Пророк* анализирует историю...", parse_mode="Markdown")
    prophet_probs = get_prophet_prediction(home_team, away_team)

    # --- ЭТАП 2: ОРАКУЛ (новости) ---
    await callback.message.answer("📰 *Оракул* сканирует новости...", parse_mode="Markdown")
    oracle_results = oracle_analyze(home_team, away_team)
    home_sentiment = oracle_results.get(home_team, {}).get('sentiment_score', 0.0)
    away_sentiment = oracle_results.get(away_team, {}).get('sentiment_score', 0.0)
    home_verdict = oracle_results.get(home_team, {}).get('verdict', 'нейтральный')
    away_verdict = oracle_results.get(away_team, {}).get('verdict', 'нейтральный')
    news_summary = (
        f"{home_team}: sentiment={home_sentiment:.2f} ({home_verdict}). "
        f"{away_team}: sentiment={away_sentiment:.2f} ({away_verdict})."
    )

    # --- ЭТАП 3: GPT-АГЕНТЫ ---
    await callback.message.answer("🧠 *GPT-агенты* обрабатывают данные...", parse_mode="Markdown")
    stats_result = run_statistician_agent(prophet_probs)
    scout_result = run_scout_agent(home_team, away_team, news_summary)

    # --- ЭТАП 4: МАЭСТРО (финальный вердикт + Келли) ---
    await callback.message.answer("⚖️ *Маэстро* выносит вердикт...", parse_mode="Markdown")
    arbitrator_result = run_arbitrator_agent(stats_result, scout_result, bookmaker_odds)

    # --- ФИНАЛЬНЫЙ ОТЧЁТ ---
    # Передаём данные оракула в scout_result если GPT вернул пустые данные
    if scout_result.get('home_team_sentiment') is None:
        scout_result['home_team_sentiment'] = home_sentiment
    if scout_result.get('away_team_sentiment') is None:
        scout_result['away_team_sentiment'] = away_sentiment
    final_report = format_final_report(home_team, away_team, stats_result, scout_result, arbitrator_result)
    await callback.message.answer(final_report, parse_mode="Markdown")

    # Кнопка назад
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Выбрать другой матч", callback_data="back_to_matches")
    await callback.message.answer("Хотите проанализировать другой матч?", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_to_matches")
async def back_to_matches(callback: types.CallbackQuery):
    await callback.answer()
    matches = matches_cache if matches_cache else fetch_matches()
    if not matches:
        await callback.message.answer("😔 Матчи недоступны.")
        return
    await callback.message.answer(
        f"📋 *Ближайшие матчи ({len(matches)} шт.):*",
        reply_markup=build_matches_keyboard(matches),
        parse_mode="Markdown"
    )

@dp.message(F.text == "💎 VIP-доступ")
async def vip_access(message: types.Message):
    await message.answer("💎 *VIP-доступ*\n\nСкоро здесь появится информация о тарифах.", parse_mode="Markdown")

@dp.message(F.text == "📊 Статистика")
async def stats(message: types.Message):
    await message.answer("📊 *Статистика*\n\nРаздел в разработке.", parse_mode="Markdown")

# --- 6. Запуск ---
async def main():
    print("🚀 Chimera AI v2.0: Бот запущен!")
    fetch_matches()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
