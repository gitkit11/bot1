# -*- coding: utf-8 -*-
import asyncio
import logging
import requests
import numpy as np
import pandas as pd
import tensorflow as tf
from datetime import datetime, timedelta
from sklearn.preprocessing import StandardScaler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импортируем наши модули ИИ
from config import TELEGRAM_TOKEN, THE_ODDS_API_KEY
from oracle_ai import oracle_analyze, format_oracle_report
from maestro_ai import maestro_analyze, format_maestro_report

# --- 1. Настройка ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- 2. Загрузка моделей и данных ---
PROPHET_MODEL_PATH = "prophet_model.keras"
DATA_PATH = "featured_football_data.csv"
prophet_model, featured_data, scaler = None, None, None

try:
    prophet_model = tf.keras.models.load_model(PROPHET_MODEL_PATH)
    print("[Загрузчик] Модель ИИ #1 \"Пророк\" успешно загружена.")
    featured_data = pd.read_csv(DATA_PATH)
    features_to_scale = [col for col in featured_data.columns if col.startswith(("H_", "A_"))]
    scaler = StandardScaler()
    scaler.fit(featured_data[features_to_scale])
    print("[Загрузчик] Датасет и скалер для \"Пророка\" готовы.")
except Exception as e:
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось загрузить модель или данные: {e}")

# --- 3. Функции для ИИ и API ---
def get_prophet_prediction(home_team, away_team):
    if prophet_model is None or featured_data is None:
        return [0.33, 0.33, 0.33]
    try:
        last_10_games = featured_data.tail(10)
        game_features = last_10_games[features_to_scale]
        scaled_features = scaler.transform(game_features)
        sequence = np.reshape(scaled_features, (1, 10, len(features_to_scale)))
        prediction = prophet_model.predict(sequence, verbose=0)[0]
        return [prediction[0], prediction[1], prediction[2]]
    except Exception as e:
        print(f"[Пророк] Ошибка при предсказании: {e}")
        return [0.33, 0.33, 0.33]

def get_upcoming_matches():
    """Получает список ближайших матчей из The Odds API."""
    API_URL = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
    params = {
        "apiKey": THE_ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    try:
        response = requests.get(API_URL, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"[API Ошибка] Не удалось получить матчи: {e}")
        return []

# --- 4. Обработчики команд и кнопок ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🤖 **Добро пожаловать в Chimera AI!**\n\n"
        "Я — передовая система для анализа футбольных матчей, использующая три независимых искусственных интеллекта.\n\n"
        "Нажмите кнопку ниже, чтобы выбрать матч для анализа."
    )
    kb = [[types.KeyboardButton(text="🎯 Выбрать матч для анализа")],
          [types.KeyboardButton(text="💎 VIP-доступ"), types.KeyboardButton(text="📊 Статистика")]]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

@dp.message(F.text == "🎯 Выбрать матч для анализа")
async def show_matches(message: types.Message):
    await message.answer("⏳ *Ищу ближайшие матчи...*", parse_mode="Markdown")
    matches = get_upcoming_matches()
    if not matches:
        await message.answer("😔 Не удалось найти ближайшие матчи. Попробуйте позже.")
        return

    builder = InlineKeyboardBuilder()
    for match in matches[:10]: # Показываем первые 10 матчей
        home = match["home_team"]
        away = match["away_team"]
        builder.button(
            text=f"⚽️ {home} vs {away}", 
            callback_data=f"analyze_{home}_{away}"
        )
    builder.adjust(1) # По одной кнопке в ряд
    await message.answer(
        "👇 **Выберите матч для анализа:**", 
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("analyze_"))
async def analyze_match_callback(callback: types.CallbackQuery):
    await callback.message.edit_text("🤖 *Активация системы Chimera AI...*", parse_mode="Markdown")
    
    _, home_team, away_team = callback.data.split("_")
    
    await callback.message.answer(f"🔍 *Анализирую матч: {home_team} vs {away_team}*", parse_mode="Markdown")

    # --- ЭТАП 1: ИИ #1 "ПРОРОК" ---
    await callback.message.answer("🔮 *ИИ #1 \"Пророк\" анализирует историю...*", parse_mode="Markdown")
    prophet_probs = get_prophet_prediction(home_team, away_team)
    
    # --- ЭТАП 2: ИИ #2 "ОРАКУЛ" ---
    await callback.message.answer("📰 *ИИ #2 \"Оракул\" сканирует новости...*", parse_mode="Markdown")
    oracle_results = oracle_analyze(home_team, away_team)
    oracle_report = format_oracle_report(home_team, away_team, oracle_results)
    await callback.message.answer(oracle_report)

    # --- ЭТАП 3: ИИ #3 "МАЭСТРО" ---
    await callback.message.answer("⚖️ *ИИ #3 \"Маэстро\" ищет выгодные ставки...*", parse_mode="Markdown")
    maestro_result = maestro_analyze(home_team, away_team, prophet_probs, oracle_results)
    final_report = format_maestro_report(maestro_result)
    
    await callback.message.answer(final_report, parse_mode="Markdown")
    await callback.answer()

@dp.message(F.text == "💎 VIP-доступ")
async def vip_access(message: types.Message):
    await message.answer("💎 **VIP-доступ**\n\nСкоро здесь появится информация о тарифах.")

@dp.message(F.text == "📊 Статистика")
async def stats(message: types.Message):
    await message.answer("📊 **Статистика**\n\nРаздел в разработке.")

# --- 5. Запуск бота ---
async def main():
    print("🚀 Chimera AI: Бот запущен и готов к работе!")
    if prophet_model is None:
        print("[ПРЕДУПРЕЖДЕНИЕ] Модель 'Пророк' не загружена. Исторический анализ будет недоступен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
