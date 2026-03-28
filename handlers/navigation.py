# -*- coding: utf-8 -*-
"""handlers/navigation.py — общие навигационные callbacks: back_to_main, back_to_report_"""
import logging
import time

from aiogram import Router, types

from database import get_user_language
from keyboards import build_main_keyboard
from state import _report_cache, _REPORT_CACHE_TTL

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(call: types.CallbackQuery):
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


@router.callback_query(lambda c: c.data and c.data.startswith("back_to_report_"))
async def back_to_report(call: types.CallbackQuery):
    suffix = call.data[len("back_to_report_"):]
    cached_report = _report_cache.get(suffix)
    if cached_report and time.time() - cached_report.get("ts", 0) < _REPORT_CACHE_TTL:
        await call.answer()
        await call.message.edit_text(
            cached_report["text"],
            parse_mode=cached_report["parse_mode"],
            reply_markup=cached_report["kb"],
        )
    else:
        await call.answer("⏰ Анализ устарел (>45 мин). Открой матч заново.", show_alert=True)
