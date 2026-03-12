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
from oracle_ai import oracle_analyze
from agents import run_statistician_agent, run_scout_agent, run_arbitrator_agent, run_gemini_agent
from database import init_db, save_prediction, get_statistics

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
    data = pd.read_csv("all_matches_featured.csv", index_col=0)
    feature_cols = [c for c in data.columns if c != 'FTR']
    scaler = MinMaxScaler()
    scaler.fit(data[feature_cols])
    print("[Загрузчик] Датасет и скалер готовы.")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось загрузить датасет: {e}")
    data = None
    scaler = None

# --- 3. Инициализация базы данных ---
init_db()

# --- 4. Глобальный кэш матчей ---
matches_cache = []

# --- 5. Вспомогательные функции ---

def get_prophet_prediction(home_team, away_team):
    """Получает предсказание от нейросети Пророк."""
    if not prophet_model or data is None or scaler is None:
        return [0.33, 0.33, 0.34]
    try:
        home_data = data[data['HomeTeam_encoded'] == hash(home_team) % 50].tail(5)
        away_data = data[data['AwayTeam_encoded'] == hash(away_team) % 50].tail(5)
        if len(home_data) < 5 or len(away_data) < 5:
            sample = data.tail(10)
        else:
            sample = pd.concat([home_data, away_data])
        sample = sample[feature_cols].tail(10)
        scaled = scaler.transform(sample)
        sequence = np.array([scaled])
        prediction = prophet_model.predict(sequence, verbose=0)[0]
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
    """Извлекает коэффициенты П1/Х/П2 из данных матча."""
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

def get_totals_odds(match_data):
    """Извлекает коэффициенты на тотал голов."""
    try:
        for bookmaker in match_data.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        if outcome.get("point") == 2.5:
                            if outcome["name"] == "Over":
                                return {"over_2_5": outcome["price"]}
    except Exception:
        pass
    return {"over_2_5": 0}

def translate_outcome(text, home_team="Хозяева", away_team="Гости"):
    """Переводит исход с английского на русский с названиями команд."""
    if not text:
        return "Нет данных"
    text_lower = text.lower()
    if "home" in text_lower and "win" in text_lower:
        return f"{home_team} (хозяева)"
    if "away" in text_lower and "win" in text_lower:
        return f"{away_team} (гость)"
    if "draw" in text_lower or "ничья" in text_lower:
        return "Ничья"
    if "хозяев" in text_lower or "хозяева" in text_lower:
        return f"{home_team} (хозяева)"
    if "гостей" in text_lower or "гость" in text_lower:
        return f"{away_team} (гость)"
    if "победа хозяев" in text_lower:
        return f"{home_team} (хозяева)"
    if "победа гостей" in text_lower:
        return f"{away_team} (гость)"
    return text

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

def build_back_keyboard():
    """Строит кнопку возврата к списку матчей."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Выбрать другой матч", callback_data="back_to_matches")
    return builder.as_markup()

def format_final_report(home_team, away_team, prophet_data, oracle_results, gpt_result, gemini_result):
    """Форматирует финальный отчёт объединяя GPT и Gemini."""

    # --- Пророк ---
    home_prob = prophet_data[1] * 100
    draw_prob = prophet_data[0] * 100
    away_prob = prophet_data[2] * 100

    # --- Оракул ---
    home_sentiment_score = oracle_results.get(home_team, {}).get('sentiment', 0)
    away_sentiment_score = oracle_results.get(away_team, {}).get('sentiment', 0)
    home_sentiment_label = "🟢 Позитивный" if home_sentiment_score > 0.1 else ("🔴 Негативный" if home_sentiment_score < -0.1 else "⚪ Нейтральный")
    away_sentiment_label = "🟢 Позитивный" if away_sentiment_score > 0.1 else ("🔴 Негативный" if away_sentiment_score < -0.1 else "⚪ Нейтральный")

    # --- GPT Вердикт ---
    gpt_verdict_raw = gpt_result.get("recommended_outcome", "Нет данных")
    gpt_verdict = translate_outcome(gpt_verdict_raw, home_team, away_team)
    gpt_confidence = gpt_result.get("final_confidence_percent", 0)
    gpt_summary = gpt_result.get("final_verdict_summary", "")
    gpt_odds = gpt_result.get("bookmaker_odds", 0)
    gpt_stake = gpt_result.get("recommended_stake_percent", 0)
    gpt_ev = gpt_result.get("expected_value_percent", 0)

    # --- Gemini Вердикт ---
    gemini_verdict_raw = gemini_result.get("recommended_outcome", "Нет данных")
    gemini_verdict = translate_outcome(gemini_verdict_raw, home_team, away_team)
    gemini_confidence = gemini_result.get("final_confidence_percent", gpt_confidence)
    gemini_summary = gemini_result.get("analysis_summary", "")
    gemini_total = gemini_result.get("total_goals_prediction", "—")
    gemini_btts = gemini_result.get("both_teams_to_score_prediction", "—")

    # --- Иконки ---
    def conf_icon(c):
        if c >= 70: return "🟢"
        elif c >= 55: return "🟡"
        return "🔴"

    # --- Согласие моделей ---
    models_agree = gpt_verdict_raw.lower() in gemini_verdict_raw.lower() or gemini_verdict_raw.lower() in gpt_verdict_raw.lower()
    agreement_text = "✅ Обе модели согласны!" if models_agree else "⚠️ Модели расходятся во мнениях"

    report = f"""
🏆 *ФИНАЛЬНЫЙ АНАЛИЗ CHIMERA AI v3.0*
━━━━━━━━━━━━━━━━━━━━━━━━━

⚽ *{home_team} vs {away_team}*

📊 *СТАТИСТИКА (Пророк):*
 П1: {home_prob:.0f}% | Х: {draw_prob:.0f}% | П2: {away_prob:.0f}%

🗞 *НОВОСТНОЙ ФОН (Оракул):*
 {home_team}: {home_sentiment_label}
 {away_team}: {away_sentiment_label}

━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *АНАЛИЗ GPT-4o-mini:*
_{gpt_summary}_

🤖 *АНАЛИЗ GEMINI 2.5 Flash:*
_{gemini_summary}_

━━━━━━━━━━━━━━━━━━━━━━━━━
⚖️ *ВЕРДИКТ МАЭСТРО (GPT):*

{conf_icon(gpt_confidence)} Исход: {gpt_verdict}
{conf_icon(gpt_confidence)} Уверенность ИИ: {gpt_confidence}%
🎯 Коэффициент: {gpt_odds}
💰 Рекомендуемая ставка: {gpt_stake:.1f}% от депозита
📈 Ожидаемая прибыль: +{gpt_ev:.1f}% от ставки

━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 *ВЕРДИКТ GEMINI:*

{conf_icon(gemini_confidence)} Исход: {gemini_verdict}
{conf_icon(gemini_confidence)} Уверенность ИИ: {gemini_confidence}%
⚽ Тотал голов: {gemini_total}
🥅 Обе забьют: {gemini_btts}

━━━━━━━━━━━━━━━━━━━━━━━━━
{agreement_text}
"""
    return report.strip()

# --- 6. Хендлеры Telegram ---
dp = Dispatcher()

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    get_matches()
    await message.answer(
        "🔮 *Chimera AI v3.0* — профессиональный анализ футбольных матчей\n\n"
        "Используются 4 независимых ИИ:\n"
        "🔮 Пророк — нейросеть (30 лет статистики)\n"
        "📰 Оракул — анализ новостей\n"
        "🧠 GPT-4o-mini — стратегический анализ\n"
        "🤖 Gemini 2.5 Flash — второе независимое мнение",
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
        total = stats['total_predictions']
        correct = stats['correct_predictions']
        accuracy = stats['accuracy_percent']

        if total == 0:
            stats_text = (
                "📊 *Статистика прогнозов Chimera AI*\n\n"
                "Пока нет сохранённых прогнозов.\n"
                "Сделайте первый анализ матча!"
            )
        else:
            acc_icon = "🟢" if accuracy >= 60 else ("🟡" if accuracy >= 50 else "🔴")
            stats_text = (
                f"📊 *Статистика прогнозов Chimera AI*\n\n"
                f"📋 Всего прогнозов: *{total}*\n"
                f"✅ Угадано: *{correct}*\n"
                f"{acc_icon} Точность: *{accuracy:.1f}%*\n\n"
                f"_Статистика обновляется по мере проверки результатов матчей._"
            )
        await message.answer(stats_text, parse_mode="Markdown")

    elif text == "💎 VIP-доступ":
        await message.answer(
            "💎 *VIP-доступ*\n\n"
            "Расширенные функции в разработке.\n"
            "Скоро здесь появятся:\n"
            "• Анализ Ла Лиги, Бундеслиги, Серии А\n"
            "• Уведомления о выгодных ставках\n"
            "• Детальная статистика ROI",
            parse_mode="Markdown"
        )

@dp.callback_query()
async def handle_callback(call: types.CallbackQuery):
    if call.data == "back_to_matches":
        if not matches_cache:
            get_matches()
        await call.message.edit_text("Выберите матч для анализа:", reply_markup=build_matches_keyboard(matches_cache))

    elif call.data == "refresh_matches":
        matches = get_matches()
        if not matches:
            await call.answer("❌ Не удалось обновить матчи.", show_alert=True)
            return
        await call.message.edit_text(f"✅ Список обновлён! Найдено {len(matches)} матчей.", reply_markup=build_matches_keyboard(matches))

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

        # Шаг 1: Пророк
        prophet_data = get_prophet_prediction(home_team, away_team)

        # Шаг 2: Оракул
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
            f"🧠 GPT-4o-mini анализирует...",
            parse_mode="Markdown"
        )

        # Шаг 3: GPT Агенты
        bookmaker_odds = get_bookmaker_odds(match)
        stats_result = run_statistician_agent(prophet_data)
        scout_result = run_scout_agent(home_team, away_team, news_summary)
        arbitrator_result = run_arbitrator_agent(stats_result, scout_result, bookmaker_odds)

        await call.message.edit_text(
            f"⏳ *Запускаю анализ матча...*\n\n"
            f"⚽ {home_team} vs {away_team}\n\n"
            f"🔮 Пророк... ✅\n"
            f"📰 Оракул... ✅\n"
            f"🧠 GPT-4o-mini... ✅\n"
            f"🤖 Gemini 2.5 Flash анализирует...",
            parse_mode="Markdown"
        )

        # Шаг 4: Gemini Агент
        gemini_result = run_gemini_agent(home_team, away_team, prophet_data, news_summary, bookmaker_odds)

        # Шаг 5: Финальный отчёт
        final_report = format_final_report(
            home_team, away_team,
            prophet_data, oracle_results,
            arbitrator_result, gemini_result
        )

        # Шаг 6: Сохранение в базу данных
        prediction_data = {
            "gpt_verdict": arbitrator_result.get("recommended_outcome", ""),
            "gemini_verdict": gemini_result.get("recommended_outcome", ""),
            "gpt_confidence": arbitrator_result.get("final_confidence_percent", 0),
            "gemini_confidence": gemini_result.get("final_confidence_percent", 0),
            "total_goals": gemini_result.get("total_goals_prediction", ""),
            "btts": gemini_result.get("both_teams_to_score_prediction", ""),
        }
        save_prediction(
            match['id'],
            match.get('commence_time', ''),
            home_team, away_team,
            prediction_data
        )

        await call.message.edit_text(final_report, parse_mode="Markdown", reply_markup=build_back_keyboard())

# --- 7. Запуск бота ---
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    print("🚀 Chimera AI v3.0: Бот запущен!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
