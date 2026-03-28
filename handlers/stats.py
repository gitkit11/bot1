# -*- coding: utf-8 -*-
"""handlers/stats.py — /stats, /cs2stats, /footballstats, /results, /learn_and_suggest"""
import asyncio
import logging

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    get_statistics, get_chimera_signal_history, get_stavit_bets, get_all_tier_stats,
    invalidate_stats_cache,
)
from meta_learner import MetaLearner

logger = logging.getLogger(__name__)
router = Router()


def _acc_bar(acc: float) -> str:
    filled = round(acc / 10)
    return "▓" * filled + "░" * (10 - filled)


def _streak_str(recent: list) -> str:
    if not recent:
        return ""
    streak_icon = "✅" if recent[0].get("is_correct") == 1 else "❌"
    count = 0
    for r in recent:
        if (r.get("is_correct") == 1) == (streak_icon == "✅"):
            count += 1
        else:
            break
    return f"{streak_icon} ×{count}" if count > 1 else streak_icon


@router.message(Command("stats"))
async def get_stats_command(message: types.Message):
    loop = asyncio.get_running_loop()
    all_stats = await loop.run_in_executor(None, get_statistics)

    _main_sports = ("football", "tennis", "basketball", "hockey")
    all_total   = sum(all_stats.get(k, {}).get("total", 0)         for k in _main_sports)
    all_checked = sum(all_stats.get(k, {}).get("total_checked", 0) for k in _main_sports)
    all_correct = sum(all_stats.get(k, {}).get("correct", 0)       for k in _main_sports)
    all_pending = sum(all_stats.get(k, {}).get("pending", 0)       for k in _main_sports)
    all_acc     = round(all_correct / all_checked * 100, 1) if all_checked > 0 else 0

    stats_text = "📊 *Статистика Chimera AI*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    if all_checked > 0:
        stats_text += (
            f"🎯 *Общий бот (без CS2):* *{all_correct} из {all_checked}*\n"
            f"`{_acc_bar(all_acc)}` *{all_acc}%*\n"
            f"📋 Всего в базе: *{all_total}* | Ожидают результата: *{all_pending}*\n"
        )
    stats_text += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    has_data = False
    _sports_list = [
        ("football",   "⚽ Футбол"),
        ("tennis",     "🎾 Теннис"),
        ("basketball", "🏀 Баскетбол"),
        ("hockey",     "🏒 Хоккей"),
        ("cs2",        "🎮 CS2 _(бета)_"),
    ]
    _sports_list.sort(key=lambda x: all_stats.get(x[0], {}).get("accuracy", 0), reverse=True)
    for sport_key, sport_label in _sports_list:
        s = all_stats.get(sport_key, {})
        total   = s.get("total", 0)
        checked = s.get("total_checked", 0)
        correct = s.get("correct", 0)
        acc     = s.get("accuracy", 0)
        pending = s.get("pending", total - checked)  # реально ожидают (без expired)

        if total == 0:
            continue
        has_data = True

        recent = s.get("recent", [])
        streak = _streak_str(recent)

        stats_text += f"*{sport_label}*"
        if streak:
            stats_text += f"  {streak}"
        stats_text += "\n"

        if checked > 0:
            stats_text += (
                f"`{_acc_bar(acc)}` *{acc:.0f}%*\n"
                f"🎯 *{correct}/{checked}* угадано"
            )
            if pending > 0:
                stats_text += f"  ·  ⏳ ждём *{pending}*"
            stats_text += "\n"
        elif pending > 0:
            stats_text += f"📋 Прогнозов: *{total}* | ⏳ Ожидают результата: *{pending}*\n"
        else:
            stats_text += f"📋 Прогнозов: *{total}* | ⚠️ Результаты не получены\n"

        sport_icons = [
            "✅" if r.get("is_correct") == 1 else "❌"
            for r in recent if r.get("is_correct") in (0, 1)
        ][:5]
        if sport_icons:
            stats_text += f"Последние: {''.join(sport_icons)}\n"

        monthly = s.get("monthly", [])
        if monthly:
            for row in monthly[:1]:
                mt = row.get("total", 0) if isinstance(row, dict) else row[1]
                mc = row.get("correct", 0) if isinstance(row, dict) else row[2]
                mn = row.get("month", "") if isinstance(row, dict) else row[0]
                if mt > 0:
                    ma = mc / mt * 100
                    stats_text += f"📅 {mn}: *{mc}/{mt}* ({ma:.0f}%)\n"

        if sport_key == "cs2":
            stats_text += "_⚠️ CS2 не входит в общий процент бота_\n"

        stats_text += "\n"

    chimera_history = get_chimera_signal_history(limit=10)
    if chimera_history:
        # is_correct: 1=win, 0=loss, -1=expired (результат не получен), None=pending
        ch_checked = [r for r in chimera_history if r["is_correct"] in (0, 1)]
        ch_wins    = sum(1 for r in ch_checked if r["is_correct"] == 1)
        ch_pending = sum(1 for r in chimera_history if r["is_correct"] is None)
        ch_expired = sum(1 for r in chimera_history if r["is_correct"] == -1)
        ch_acc     = round(ch_wins / len(ch_checked) * 100) if ch_checked else 0
        ch_streak  = _streak_str(
            [{"is_correct": r["is_correct"]} for r in chimera_history if r["is_correct"] in (0, 1)]
        )
        stats_text += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        stats_text += f"*🎯 Сигналы дня*"
        if ch_streak:
            stats_text += f"  {ch_streak}"
        stats_text += "\n"
        if ch_checked:
            stats_text += f"`{_acc_bar(ch_acc)}` *{ch_acc}%*\n"
            stats_text += f"🎯 *{ch_wins}/{len(ch_checked)}* угадано"
            if ch_pending:
                stats_text += f"  ·  ⏳ ждём *{ch_pending}*"
            if ch_expired:
                stats_text += f"  ·  ⚠️ нет результата: *{ch_expired}*"
            stats_text += "\n"
        else:
            stats_text += f"⏳ Ждём результаты: *{ch_pending}*\n"
        done_icons = []
        for r in chimera_history:
            if r["is_correct"] in (0, 1):
                done_icons.append("✅" if r["is_correct"] == 1 else "❌")
                if len(done_icons) >= 5:
                    break
        if done_icons:
            stats_text += f"Последние: {''.join(done_icons)}\n"

    # ── Статистика по тирам ────────────────────────────────────────────────────
    tier_stats = get_all_tier_stats()
    tier_labels = {
        "СТАВИТЬ 🔥🔥🔥": "🔥🔥🔥 Три огня",
        "СТАВИТЬ 🔥🔥":   "🔥🔥 Сильная",
        "СТАВИТЬ 🔥":     "🔥 Слабая",
    }
    has_tier = any(tier_stats.get(k, {}).get("total", 0) > 0 for k in tier_labels)
    if has_tier:
        stats_text += "━━━━━━━━━━━━━━━━━━━━━━━━━\n*📊 По тирам ставок*\n"
        for tier_key, tier_label in tier_labels.items():
            td = tier_stats.get(tier_key, {})
            ttotal   = td.get("total", 0)
            tchecked = td.get("checked", 0)
            twins    = td.get("wins", 0)
            tacc     = td.get("acc")
            if ttotal == 0:
                continue
            if tacc is not None:
                acc_icon = "🟢" if tacc >= 65 else ("🟡" if tacc >= 50 else "🔴")
                stats_text += f"{acc_icon} {tier_label}: *{twins}/{tchecked}* ({tacc}%)"
            else:
                stats_text += f"⏳ {tier_label}: *{ttotal}* ждут"
            pending_tier = ttotal - tchecked
            if pending_tier > 0:
                stats_text += f"  ·  ⏳*{pending_tier}*"
            stats_text += "\n"
        stats_text += "\n"

    if not has_data and not chimera_history:
        stats_text = (
            "📊 *Статистика Chimera AI*\n\n"
            "Пока нет сохранённых прогнозов.\n"
            "Сделайте первый анализ матча!"
        )

    back_kb = InlineKeyboardBuilder()
    back_kb.button(text="🔄 Обновить", callback_data="stats_refresh")
    back_kb.button(text="🏠 Меню", callback_data="back_to_main")
    back_kb.adjust(2)
    await message.answer(stats_text, parse_mode="Markdown", reply_markup=back_kb.as_markup())


@router.message(Command("learn_and_suggest"))
async def learn_and_suggest_command(message: types.Message):
    await message.answer("Запускаю процесс анализа производительности и поиска предложений по оптимизации...")
    learner = MetaLearner(signal_engine_path="signal_engine.py")

    cs2_performance = learner.analyze_performance("cs2")
    cs2_suggestions = learner.suggest_config_updates("cs2", cs2_performance)
    football_performance = learner.analyze_performance("football")
    football_suggestions = learner.suggest_config_updates("football", football_performance)

    response_text = "**Результаты анализа MetaLearner:**\n\n"
    has_suggestions = False

    if cs2_suggestions:
        has_suggestions = True
        response_text += "**🎮 CS2 Предложения:**\n"
        for key, value in cs2_suggestions.items():
            response_text += f"  - Изменить `{key}` на `{value}`\n"
    else:
        response_text += "**🎮 CS2:** Нет предложений по оптимизации.\n"

    if football_suggestions:
        has_suggestions = True
        response_text += "\n**⚽ Футбол Предложения:**\n"
        for key, value in football_suggestions.items():
            response_text += f"  - Изменить `{key}` на `{value}`\n"
    else:
        response_text += "\n**⚽ Футбол:** Нет предложений по оптимизации.\n"

    if has_suggestions:
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(text="✅ Принять все предложения", callback_data="meta_learner_accept"))
        builder.add(types.InlineKeyboardButton(text="❌ Отклонить", callback_data="meta_learner_decline"))
        await message.answer(response_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(
            response_text + "\n\nТекущие настройки оптимальны или недостаточно данных.",
            parse_mode="Markdown"
        )


@router.callback_query(lambda c: c.data and c.data.startswith("meta_learner_"))
async def meta_learner_callback_handler(callback_query: types.CallbackQuery):
    action = callback_query.data.split("_")[2]
    learner = MetaLearner(signal_engine_path="signal_engine.py")

    if action == "accept":
        await callback_query.message.edit_text("Принимаю предложения и применяю изменения...", reply_markup=None)
        loop = asyncio.get_running_loop()
        cs2_perf = await loop.run_in_executor(None, lambda: learner.analyze_performance("cs2"))
        cs2_sugg = learner.suggest_config_updates("cs2", cs2_perf)
        if cs2_sugg:
            await loop.run_in_executor(None, lambda: learner.apply_config_updates("cs2", cs2_sugg))
        fb_perf = await loop.run_in_executor(None, lambda: learner.analyze_performance("football"))
        fb_sugg = learner.suggest_config_updates("football", fb_perf)
        if fb_sugg:
            await loop.run_in_executor(None, lambda: learner.apply_config_updates("football", fb_sugg))
        await callback_query.message.answer(
            "✅ Изменения успешно применены! Файл signal_engine.py обновлен (создана резервная копия).",
            parse_mode="Markdown"
        )
    elif action == "decline":
        await callback_query.message.edit_text("❌ Предложения отклонены. Изменения не применены.", reply_markup=None)
    await callback_query.answer()


@router.message(Command("cs2stats"))
async def cmd_cs2stats(message: types.Message):
    try:
        from sports.cs2.results_tracker import get_cs2_bet_stats
        s = get_cs2_bet_stats()
        if "error" in s:
            await message.answer("😔 Произошёл сбой. Напиши нам в поддержку.")
            return

        acc_icon = lambda a: "🟢" if a >= 60 else ("🟡" if a >= 50 else "🔴")
        roi_icon = lambda r: "🟢" if r > 0 else "🔴"

        text = "🎮 *CHIMERA AI — Статистика CS2*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"📋 Всего прогнозов: *{s['total']}* | Проверено: *{s['checked']}*\n\n"

        if s['checked'] > 0:
            text += f"🏆 *Победитель матча:*\n"
            text += f"{acc_icon(s['accuracy'])} Угадано: *{s['wins']}/{s['checked']}* — *{s['accuracy']}%*\n"
            text += f"{roi_icon(s['roi'])} ROI: *{s['roi']:+.2f}* ед.\n\n"

        if s['total_checked'] > 0:
            text += f"🗺 *Тотал карт:*\n"
            text += f"{acc_icon(s['total_accuracy'])} Угадано: *{s['total_wins']}/{s['total_checked']}* — *{s['total_accuracy']}%*\n\n"

        if s.get("monthly"):
            text += "📅 *По месяцам:*\n"
            for row in s["monthly"]:
                m_total = row["total"]
                m_wins  = row["wins"]
                m_acc   = m_wins / m_total * 100 if m_total else 0
                m_roi   = row["roi"]
                text += f"{acc_icon(m_acc)} {row['month']}: {m_wins}/{m_total} ({m_acc:.0f}%) ROI {m_roi:+.1f}\n"
            text += "\n"

        if s.get("recent"):
            text += "📋 *Последние результаты:*\n"
            for r in s["recent"][:6]:
                icon = "✅" if r["is_correct"] == 1 else "❌"
                h_sc = r.get("real_home_score", "?")
                a_sc = r.get("real_away_score", "?")
                text += f"{icon} {r['home_team']} *{h_sc}:{a_sc}* {r['away_team']}\n"

        back_kb = InlineKeyboardBuilder()
        back_kb.button(text="🏠 Меню", callback_data="back_to_main")
        await message.answer(text, parse_mode="Markdown", reply_markup=back_kb.as_markup())
    except Exception as e:
        logger.error(f"[CS2 статистика] Ошибка: {e}")
        await message.answer("😔 Произошёл сбой. Напиши нам в поддержку.")


@router.message(Command("footballstats"))
async def cmd_footballstats(message: types.Message):
    try:
        stats = get_statistics('football')
        s = stats.get('football', {})

        acc_icon = lambda a: "🟢" if a >= 60 else ("🟡" if a >= 50 else "🔴")
        roi_icon = lambda r: "🟢" if r > 0 else "🔴"

        text = "⚽ *CHIMERA AI — Статистика Футбол*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        total    = s.get('total', 0)
        checked  = s.get('total_checked', 0)
        correct  = s.get('correct', 0)
        accuracy = s.get('accuracy', 0)
        roi      = s.get('roi_main', 0)

        text += f"📋 Всего прогнозов: *{total}* | Проверено: *{checked}*\n\n"
        if checked > 0:
            text += f"🏆 *Победитель матча:*\n"
            text += f"{acc_icon(accuracy)} Угадано: *{correct}/{checked}* — *{accuracy:.1f}%*\n"
            text += f"{roi_icon(roi)} ROI: *{roi:+.2f}* ед.\n\n"

        vb_checked = s.get('vb_checked', 0)
        if vb_checked > 0:
            vb_acc = s.get('vb_accuracy', 0)
            roi_vb = s.get('roi_value_bet', 0)
            text += f"💰 *Value Bets:*\n"
            text += f"{acc_icon(vb_acc)} Угадано: *{s['vb_correct']}/{vb_checked}* — *{vb_acc:.1f}%*\n"
            text += f"{roi_icon(roi_vb)} ROI: *{roi_vb:+.2f}* ед.\n\n"

        monthly = s.get('monthly', [])
        if monthly:
            text += "📅 *По месяцам:*\n"
            for row in monthly:
                m_t   = row.get('total', 0)
                m_c   = row.get('correct', 0)
                m_acc = m_c / m_t * 100 if m_t else 0
                m_roi = row.get('roi_vb', 0)
                text += f"{acc_icon(m_acc)} {row['month']}: {m_c}/{m_t} ({m_acc:.0f}%) ROI {m_roi:+.1f}\n"
            text += "\n"

        recent = s.get('recent', [])
        if recent:
            text += "📋 *Последние результаты:*\n"
            for r in recent[:6]:
                icon = "✅" if r.get('is_correct') == 1 else "❌"
                h_sc = r.get('real_home_score', '?')
                a_sc = r.get('real_away_score', '?')
                text += f"{icon} {r.get('home_team','?')} *{h_sc}:{a_sc}* {r.get('away_team','?')}\n"

        back_kb = InlineKeyboardBuilder()
        back_kb.button(text="🏠 Меню", callback_data="back_to_main")
        await message.answer(text, parse_mode="Markdown", reply_markup=back_kb.as_markup())
    except Exception as e:
        logger.error(f"[Футбол статистика] Ошибка: {e}")
        await message.answer("😔 Произошёл сбой. Напиши нам в поддержку.")


@router.message(Command("results"))
async def cmd_results(message: types.Message):
    stats = get_statistics()

    def acc_icon(acc):
        return "🟢" if acc >= 60 else ("🟡" if acc >= 50 else "🔴")

    def roi_icon(roi):
        return "🟢" if roi > 0 else "🔴"

    text = "📊 *CHIMERA AI — Трекер результатов*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for sport in ['football', 'cs2']:
        s_stats = stats.get(sport)
        if not s_stats or s_stats['total_checked'] == 0:
            continue
        emoji = "⚽️ ФУТБОЛ" if sport == 'football' else "🎮 CS2"
        text += f"*{emoji}:*\n"
        text += f"{acc_icon(s_stats['accuracy'])} Точность: *{s_stats['accuracy']:.1f}%* ({s_stats['correct']}/{s_stats['total_checked']})\n"
        text += f"{acc_icon(s_stats['vb_accuracy'])} Value ставки: *{s_stats['vb_accuracy']:.1f}%* ({s_stats['vb_correct']}/{s_stats['vb_checked']})\n"
        text += f"{roi_icon(s_stats['roi_main'])} ROI Основные: *{s_stats['roi_main']:+.1f}* ед.\n"
        text += f"{roi_icon(s_stats['roi_value_bet'])} ROI Value: *{s_stats['roi_value_bet']:+.1f}* ед.\n\n"

    back_kb = InlineKeyboardBuilder()
    back_kb.button(text="🏠 Меню", callback_data="back_to_main")
    if text == "📊 *CHIMERA AI — Трекер результатов*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n":
        await message.answer("📋 Пока нет проверенных матчей.", reply_markup=back_kb.as_markup())
        return
    await message.answer(text, parse_mode="Markdown", reply_markup=back_kb.as_markup())


@router.callback_query(lambda c: c.data == "stats_refresh")
async def stats_refresh_callback(call: types.CallbackQuery):
    await call.answer("🔄 Обновляю...", show_alert=False)
    invalidate_stats_cache()

    _loop_sr = asyncio.get_running_loop()
    _fresh_stats   = await _loop_sr.run_in_executor(None, get_statistics)
    _fresh_chimera = get_chimera_signal_history(limit=10)

    _main_sports_r = ("football", "tennis", "basketball", "hockey")
    all_total   = sum(_fresh_stats.get(k, {}).get("total", 0)         for k in _main_sports_r)
    all_checked = sum(_fresh_stats.get(k, {}).get("total_checked", 0) for k in _main_sports_r)
    all_correct = sum(_fresh_stats.get(k, {}).get("correct", 0)       for k in _main_sports_r)
    all_acc     = round(all_correct / all_checked * 100, 1) if all_checked > 0 else 0

    txt = "📊 *Статистика Chimera AI*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    if all_checked > 0:
        txt += (
            f"🎯 *Общий бот (без CS2):* *{all_correct} из {all_checked}*\n"
            f"`{_acc_bar(all_acc)}` *{all_acc}%*\n"
            f"📋 Всего: *{all_total}* | Ожидают: *{all_total - all_checked}*\n"
        )
    txt += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    _sl = [
        ("football", "⚽ Футбол"), ("cs2", "🎮 CS2 _(бета)_"),
        ("tennis", "🎾 Теннис"), ("basketball", "🏀 Баскетбол"), ("hockey", "🏒 Хоккей"),
    ]
    _sl.sort(key=lambda x: _fresh_stats.get(x[0], {}).get("accuracy", 0), reverse=True)
    for sport_key, sport_label in _sl:
        s = _fresh_stats.get(sport_key, {})
        if not s.get("total"):
            continue
        checked = s.get("total_checked", 0)
        correct = s.get("correct", 0)
        acc     = s.get("accuracy", 0)
        pending = s.get("total", 0) - checked
        recent_icons = [
            "✅" if r.get("is_correct") == 1 else "❌"
            for r in s.get("recent", []) if r.get("is_correct") in (0, 1)
        ][:5]
        txt += f"*{sport_label}*\n"
        if checked > 0:
            txt += f"`{_acc_bar(acc)}` *{acc:.0f}%* — *{correct}/{checked}*"
            if pending:
                txt += f"  ⏳ *{pending}*"
            txt += "\n"
        else:
            txt += f"⏳ Ожидают результата: *{s.get('total', 0)}*\n"
        if recent_icons:
            txt += f"Последние: {''.join(recent_icons)}\n"
        txt += "\n"

    if _fresh_chimera:
        ch_checked = [r for r in _fresh_chimera if r["is_correct"] is not None]
        ch_wins    = sum(1 for r in ch_checked if r["is_correct"] == 1)
        ch_acc     = round(ch_wins / len(ch_checked) * 100) if ch_checked else 0
        txt += "━━━━━━━━━━━━━━━━━━━━━━━━━\n*🎯 Сигналы дня*\n"
        if ch_checked:
            txt += f"`{_acc_bar(ch_acc)}` *{ch_acc}%* — *{ch_wins}/{len(ch_checked)}*\n"
        done_icons = [
            "✅" if r["is_correct"] == 1 else "❌"
            for r in _fresh_chimera if r["is_correct"] in (0, 1)
        ][:5]
        if done_icons:
            txt += f"Последние: {''.join(done_icons)}\n"

    _ref_kb = InlineKeyboardBuilder()
    _ref_kb.button(text="🔄 Обновить", callback_data="stats_refresh")
    _ref_kb.button(text="🏠 Меню",     callback_data="back_to_main")
    _ref_kb.adjust(2)
    try:
        await call.message.edit_text(txt, parse_mode="Markdown", reply_markup=_ref_kb.as_markup())
    except Exception as _e:
        logger.debug(f"[stats_refresh] {_e}")
