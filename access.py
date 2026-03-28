# -*- coding: utf-8 -*-
"""
access.py — Система доступа CHIMERA AI
=======================================

Три тарифа:
  free    — подписан на канал: 2 анализа в НЕДЕЛЮ, без сигналов/экспресс/охоты
  trial   — 3 дня: 4 анализа в ДЕНЬ (спорт+сигналы+экспресс), охота/статистика/кабинет бесплатно
  full    — 30 дней: всё без ограничений

Что НЕ считается ни у кого:
  - Статистика
  - Кабинет
  - Химера (чат)
  - Охота Химеры (trial и full)
"""

import logging
from aiogram import Bot

logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "chimera_bet_community"

FREE_WEEKLY_LIMIT  = 2   # анализов в неделю для бесплатного
TRIAL_DAILY_LIMIT  = 4   # анализов в день для пробного

# ─── Тексты ───────────────────────────────────────────────────────────────────

MSG_NOT_IN_CHANNEL = (
    "🔒 <b>Доступ закрыт</b>\n\n"
    "Для использования CHIMERA AI подпишись на наш канал:\n\n"
    "👉 <a href='https://t.me/chimera_bet_community'>@chimera_bet_community</a>\n\n"
    "<i>После подписки попробуй снова.</i>"
)

MSG_FREE_LIMIT = (
    "⏳ <b>Лимит исчерпан</b>\n\n"
    "На бесплатном тарифе — <b>2 анализа в неделю</b>.\n"
    "Твой лимит использован.\n\n"
    "💎 <b>Хочешь больше?</b>\n"
    "Нажми кнопку <b>💎 Подписка Химера</b> в меню — "
    "дадим <b>3 дня пробного доступа</b> бесплатно.\n\n"
    "<i>Бесплатный лимит сбрасывается каждый понедельник.</i>"
)

MSG_TRIAL_LIMIT = (
    "⏳ <b>Дневной лимит исчерпан</b>\n\n"
    "На пробном тарифе — <b>4 анализа в день</b>.\n"
    "Завтра лимит сбросится.\n\n"
    "💎 Хочешь без ограничений? Нажми <b>💎 Подписка Химера</b> в меню."
)

MSG_SUB_REQUIRED = (
    "🔒 <b>Только для подписчиков</b>\n\n"
    "Сигналы дня, Экспресс и Охота доступны с подпиской.\n\n"
    "💎 <b>Хочешь попробовать бесплатно?</b>\n"
    "Нажми кнопку <b>💎 Подписка Химера</b> в меню — "
    "дадим <b>3 дня пробного доступа</b> прямо сейчас."
)


# ─── Проверка канала ──────────────────────────────────────────────────────────

async def is_channel_member(user_id: int, bot: Bot) -> bool:
    try:
        member = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception as e:
        logger.warning(f"[access] channel check failed for {user_id}: {e}")
        return True  # при ошибке API — пропускаем


# ─── Главная проверка ─────────────────────────────────────────────────────────

async def check_access(
    user_id: int,
    bot: Bot,
    require_full: bool = False,   # True = нужна full/trial подписка (сигналы, экспресс)
    count_analysis: bool = False, # True = списать один анализ если доступ разрешён
) -> str:
    """
    Возвращает:
      "ok"           — доступ разрешён
      "no_channel"   — не подписан на канал
      "sub_required" — нужна подписка (free не может)
      "free_limit"   — исчерпал 2/неделю (free)
      "trial_limit"  — исчерпал 4/день (trial)
    """
    from state import ADMIN_IDS
    from database import (
        get_subscription_status,
        increment_weekly_analysis,
        increment_daily_analysis,
    )

    if user_id in ADMIN_IDS:
        return "ok"

    # Шаг 1: подписан на канал?
    if not await is_channel_member(user_id, bot):
        return "no_channel"

    status = get_subscription_status(user_id)
    sub_type = status["sub_type"]  # "free" | "trial" | "full"

    # ── full — без ограничений ─────────────────────────────────────────────
    if sub_type == "full":
        return "ok"

    # ── trial — 4 анализа в день (кроме охоты/статистики/кабинета) ────────
    if sub_type == "trial":
        if count_analysis:
            if status["daily_left"] <= 0:
                return "trial_limit"
            increment_daily_analysis(user_id)
        return "ok"

    # ── free — подписка нужна для сигналов/экспресса ──────────────────────
    if require_full:
        return "sub_required"

    if count_analysis:
        if status["weekly_left"] <= 0:
            return "free_limit"
        increment_weekly_analysis(user_id)

    return "ok"


def get_access_denied_text(reason: str) -> str:
    return {
        "no_channel":   MSG_NOT_IN_CHANNEL,
        "sub_required": MSG_SUB_REQUIRED,
        "free_limit":   MSG_FREE_LIMIT,
        "trial_limit":  MSG_TRIAL_LIMIT,
    }.get(reason, "🔒 Доступ закрыт.")
