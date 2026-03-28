# -*- coding: utf-8 -*-
"""handlers/basketball.py — /basketball и все bball_ callbacks"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from state import _basketball_cache, _report_cache, _REPORT_CACHE_TTL
from handlers.common import show_ai_thinking

logger = logging.getLogger(__name__)
router = Router()

# Текущая выбранная лига баскетбола
_basketball_league = "basketball_nba"


async def cmd_basketball(message: types.Message):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🏀 NBA",       callback_data="bball_league_basketball_nba")],
        [types.InlineKeyboardButton(text="🏆 Евролига",  callback_data="bball_league_basketball_euroleague")],
        [types.InlineKeyboardButton(text="🇦🇺 NBL",       callback_data="bball_league_basketball_nbl")],
    ])
    await message.answer(
        "<b>🏀 БАСКЕТБОЛ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\nВыбери лигу:",
        parse_mode="HTML", reply_markup=kb
    )


@router.callback_query(lambda c: c.data and c.data.startswith("bball_league_"))
async def bball_select_league(call: types.CallbackQuery):
    global _basketball_league
    league_key = call.data.replace("bball_league_", "")
    _basketball_league = league_key

    league_names = {"basketball_nba": "🏀 NBA", "basketball_euroleague": "🏆 Евролига", "basketball_nbl": "🇦🇺 NBL Australia"}
    league_name  = league_names.get(league_key, league_key)

    await call.answer()
    status = await call.message.edit_text(f"{league_name}\n⏳ Загружаю матчи...", parse_mode="HTML")

    try:
        from sports.basketball import get_basketball_matches
        loop = asyncio.get_running_loop()
        matches = await loop.run_in_executor(None, get_basketball_matches, league_key)
        _basketball_cache[league_key] = matches

        if not matches:
            await status.edit_text(f"{league_name}\n\n📭 Матчей не найдено.", parse_mode="HTML")
            return

        buttons = []
        for i, m in enumerate(matches):
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            ct   = m.get("commence_time", "")
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                dt_msk = dt + timedelta(hours=3)
                time_label = dt_msk.strftime("%d.%m %H:%M")
            except Exception:
                time_label = ct[:10]
            h_odds = m.get("bookmaker_odds", {}).get("home_win") or m.get("home_win") or 0
            a_odds = m.get("bookmaker_odds", {}).get("away_win") or m.get("away_win") or 0
            odds_str = f"  {h_odds}/{a_odds}" if h_odds and a_odds else ""
            buttons.append([types.InlineKeyboardButton(
                text=f"🏀 {time_label}  {home} — {away}{odds_str}",
                callback_data=f"bball_match_{league_key}_{i}"
            )])
        buttons.append([types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")])
        kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await status.edit_text(
            f"<b>{league_name}</b> — {len(matches)} матчей\nВыбери матч для анализа:",
            parse_mode="HTML", reply_markup=kb
        )
    except Exception as e:
        logger.error(f"[Баскетбол] Ошибка: {e}")
        await status.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.", parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("bball_match_"))
async def bball_analyze_match(call: types.CallbackQuery):
    await call.answer()
    parts      = call.data.split("_")
    idx        = int(parts[-1])
    league_key = "_".join(parts[2:-1])

    matches = _basketball_cache.get(league_key, [])
    if idx >= len(matches):
        await call.message.edit_text(
            "⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.",
            parse_mode="HTML"
        )
        return

    import time as _time_bb
    _bb_cache_key = f"bball_{league_key}_{idx}"
    _bb_cached = _report_cache.get(_bb_cache_key)
    if _bb_cached and _time_bb.time() - _bb_cached.get("ts", 0) < _REPORT_CACHE_TTL:
        await call.message.edit_text(
            _bb_cached["text"],
            parse_mode=_bb_cached.get("parse_mode"),
            reply_markup=_bb_cached.get("kb"),
        )
        return

    m    = matches[idx]
    home = m.get("home_team", "")
    away = m.get("away_team", "")
    ct   = m.get("commence_time", "")

    try:
        dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        dt_msk = dt + timedelta(hours=3)
        time_label = dt_msk.strftime("%d.%m %H:%M МСК")
    except Exception:
        time_label = ct[:16]

    league_names = {"basketball_nba": "🏀 NBA", "basketball_euroleague": "🏆 Евролига", "basketball_nbl": "🇦🇺 NBL Australia"}
    league_name  = league_names.get(league_key, league_key)

    status_msg = await call.message.edit_text(
        f"⏳ <b>{home} vs {away}</b>", parse_mode="HTML"
    )
    await show_ai_thinking(status_msg, home, away, sport="basketball")

    try:
        from sports.basketball.core import get_basketball_odds, calculate_basketball_win_prob
        from agents import client as _gpt_client, groq_client as _groq_client

        odds     = get_basketball_odds(m)
        analysis = calculate_basketball_win_prob(
            home, away, odds, league_key,
            no_vig_home=odds.get("no_vig_home", 0.0),
            no_vig_away=odds.get("no_vig_away", 0.0),
        )

        h_prob     = analysis["home_prob"]
        a_prob     = analysis["away_prob"]
        h_ev       = analysis["h_ev"]
        a_ev       = analysis["a_ev"]
        bet_signal = analysis["bet_signal"]
        total_data = analysis.get("total_analysis", {})

        if h_prob >= a_prob:
            fav, fav_prob, fav_odds, fav_ev = home, h_prob, odds["home_win"], h_ev
        else:
            fav, fav_prob, fav_odds, fav_ev = away, a_prob, odds["away_win"], a_ev

        kelly = 0.0
        if fav_odds > 1.02 and fav_ev > 0:
            kelly = round((fav_prob - (1 - fav_prob) / (fav_odds - 1)) * 100, 1)
            kelly = max(0.0, min(kelly, 25.0))

        await call.message.edit_text(
            f"🏀 <b>{home} vs {away}</b>\n⏳ Запускаю AI анализ...", parse_mode="HTML"
        )

        spread_block = ""
        if odds.get("spread_home"):
            spread_block = (
                f"Фора: {home} {odds['spread_home']:+.1f} @ {odds['spread_home_odds']}, "
                f"{away} {odds['spread_away']:+.1f} @ {odds['spread_away_odds']}."
            )

        total_block = ""
        if total_data:
            total_block = (
                f"Тотал линия: {total_data['line']} "
                f"(Over {total_data['over_odds']} / Under {total_data['under_odds']})."
            )

        home_form = analysis.get("home_form", "")
        away_form = analysis.get("away_form", "")
        home_b2b  = analysis.get("home_b2b", False)
        away_b2b  = analysis.get("away_b2b", False)
        home_inj  = analysis.get("home_injuries") or {}
        away_inj  = analysis.get("away_injuries") or {}

        form_block = ""
        if home_form or away_form:
            form_block = f"Форма (последние игры): {home}={home_form or '—'}, {away}={away_form or '—'}\n"
        b2b_block = ""
        if home_b2b:
            b2b_block += f"⚠️ {home} играл вчера (back-to-back — усталость!)\n"
        if away_b2b:
            b2b_block += f"⚠️ {away} играл вчера (back-to-back — усталость!)\n"
        inj_block = ""
        if home_inj.get("injured") or home_inj.get("doubts"):
            names = ", ".join(home_inj.get("injured", []) + home_inj.get("doubts", []))
            inj_block += f"🤕 {home} травмы/сомн: {names}\n"
        if away_inj.get("injured") or away_inj.get("doubts"):
            names = ", ".join(away_inj.get("injured", []) + away_inj.get("doubts", []))
            inj_block += f"🤕 {away} травмы/сомн: {names}\n"

        # ── Oracle AI: новости + Reddit (параллельно с AI запросами) ──────────
        _bb_news_block = ""
        _bb_expert_block = ""
        try:
            import asyncio as _aio_bb
            import concurrent.futures as _cf_bb
            _bb_loop = _aio_bb.get_event_loop()
            def _fetch_bb_oracle():
                try:
                    from oracle_ai import oracle_analyze as _oa
                    res = _oa(home, away)
                    lines = []
                    for team, data in res.items():
                        sent = data.get("sentiment", 0)
                        cnt  = data.get("news_count", 0)
                        icon = "📈" if sent > 0.05 else ("📉" if sent < -0.05 else "➡️")
                        if cnt > 0:
                            lines.append(f"{team} {icon}({cnt} новостей)")
                    return "Новости: " + " | ".join(lines) + "\n" if lines else ""
                except Exception:
                    return ""
            def _fetch_bb_expert():
                try:
                    from expert_oracle import get_expert_consensus, format_expert_block
                    exp = get_expert_consensus(home, away, "basketball")
                    return format_expert_block(exp, home, away) or ""
                except Exception:
                    return ""
            with _cf_bb.ThreadPoolExecutor(max_workers=2) as _pool_bb:
                _fut_oracle = _pool_bb.submit(_fetch_bb_oracle)
                _fut_expert = _pool_bb.submit(_fetch_bb_expert)
                _bb_news_block   = _fut_oracle.result(timeout=10)
                _bb_expert_block = _fut_expert.result(timeout=12)
        except Exception as _bb_oe:
            logger.debug(f"[BB Oracle] {_bb_oe}")

        def _run_gpt_basketball():
            try:
                _elo_gap = analysis.get("elo_gap", 0)
                _nv_h = odds.get("no_vig_home", 0)
                _nv_a = odds.get("no_vig_away", 0)
                prompt = (
                    f"Баскетбол. {league_name}. {home} vs {away}. {time_label}.\n"
                    f"ELO: {home}={analysis.get('elo_home',1500)}, {away}={analysis.get('elo_away',1500)} (разрыв {_elo_gap})\n"
                    f"Наша модель: {home}={round(h_prob*100)}% | {away}={round(a_prob*100)}%\n"
                    f"Букмекер no-vig: {home}={round(_nv_h*100,1)}% | {away}={round(_nv_a*100,1)}%\n"
                    f"Кэфы: {home}={odds.get('home_win','?')} | {away}={odds.get('away_win','?')}\n"
                    f"EV: {home}={round(h_ev*100,1)}% | {away}={round(a_ev*100,1)}%\n"
                    f"{form_block}{b2b_block}{inj_block}{spread_block}\n{total_block}\n"
                    f"{_bb_news_block}"
                    f"Напиши аналитический summary из 2-3 предложений:\n"
                    f"1) Главное математическое преимущество фаворита — ELO разрыв, серия побед/поражений, усталость B2B, травмы.\n"
                    f"2) Что говорит расхождение нашей модели с линией букмекера — где рынок ошибся?\n"
                    f"3) Уверенный вывод с конкретной причиной.\n"
                    f"Пиши как эксперт-беттор. Только факты и цифры, никакой воды.\n"
                    f"Формат ответа: {{'verdict': 'home_win'/'away_win', 'confidence': 0-100, 'summary': '...'}}"
                )
                resp = _gpt_client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[
                        {"role": "system", "content": "Ты — Химера, математический аналитик баскетбола. Говоришь уверенно, кратко, с цифрами. Никогда не пишешь общих фраз — только конкретные выводы из данных."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4, max_tokens=350,
                )
                import json as _json
                text_r = resp.choices[0].message.content.strip()
                try:
                    start = text_r.find('{')
                    end   = text_r.rfind('}') + 1
                    if start >= 0:
                        _raw = text_r[start:end]
                        try:
                            return _json.loads(_raw)
                        except Exception:
                            import ast as _ast
                            try:
                                return _ast.literal_eval(_raw)
                            except Exception:
                                pass
                    return {"summary": text_r}
                except Exception:
                    return {"summary": text_r}
            except Exception as _e:
                logger.warning(f"[GPT Basketball] {_e}")
                return {"summary": ""}

        def _run_llama_basketball():
            try:
                prompt = (
                    f"Basketball. {league_name}. {home} vs {away}.\n"
                    f"Model: {home}={round(h_prob*100)}% | {away}={round(a_prob*100)}%\n"
                    f"Odds: {home}={odds.get('home_win','?')} | {away}={odds.get('away_win','?')}\n"
                    f"EV: {home}={round(h_ev*100,1)}% | {away}={round(a_ev*100,1)}%\n"
                    f"{form_block}{b2b_block}{inj_block}\n"
                    f"Write an independent 2-sentence take as a sharp bettor:\n"
                    f"1) The key edge or risk the model might underweight (back-to-back fatigue, hot/cold streak, home court impact, injuries).\n"
                    f"2) Your confident final call with a specific reason — not a hedge.\n"
                    f"JSON: {{'verdict': 'home_win'/'away_win', 'confidence': 0-100, 'summary': '...'}}"
                )
                resp = _groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are Shadow — a sharp, independent basketball analyst. You spot what others miss. Be direct, specific, confident. No filler."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4, max_tokens=300,
                )
                import json as _json
                text_r = resp.choices[0].message.content.strip()
                try:
                    start = text_r.find('{')
                    end   = text_r.rfind('}') + 1
                    if start >= 0:
                        _raw = text_r[start:end]
                        try:
                            return _json.loads(_raw)
                        except Exception:
                            import ast as _ast
                            try:
                                return _ast.literal_eval(_raw)
                            except Exception:
                                pass
                    return {"summary": text_r}
                except Exception:
                    return {"summary": text_r}
            except Exception as _e:
                logger.warning(f"[Llama Basketball] {_e}")
                return {"summary": ""}

        loop = asyncio.get_running_loop()
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=2) as pool:
            gpt_f   = pool.submit(_run_gpt_basketball)
            llama_f = pool.submit(_run_llama_basketball)
            gpt_r   = gpt_f.result(timeout=25)
            llama_r = llama_f.result(timeout=20)

        # AI Gate: повышаем/понижаем тир на основе согласия агентов
        from signal_engine import apply_ai_gate as _ai_gate
        _model_outcome = "home_win" if h_prob >= a_prob else "away_win"
        _gpt_v  = gpt_r.get("verdict", "")
        _llama_v = llama_r.get("verdict", "")
        bet_signal = _ai_gate(bet_signal, _model_outcome, _gpt_v, _llama_v)
        # Обновляем analysis для format_basketball_report
        analysis = dict(analysis)
        analysis["bet_signal"] = bet_signal

        from sports.basketball.core import format_basketball_report
        report_text = format_basketball_report(
            home_team=home, away_team=away,
            analysis=analysis, odds=odds,
            gpt_result=gpt_r, llama_result=llama_r,
            match_time=ct, league_name=league_name,
        )

        # CHIMERA Score блок
        try:
            from chimera_signal import compute_chimera_score, score_label as _score_label
            _bm_odds = {"home_win": odds.get("home_win", 0), "away_win": odds.get("away_win", 0)}
            _chim = compute_chimera_score(
                home_team=home, away_team=away,
                home_prob=h_prob, away_prob=a_prob, draw_prob=0.0,
                bookmaker_odds=_bm_odds,
                home_form=analysis.get("home_form", ""),
                away_form=analysis.get("away_form", ""),
                elo_home=analysis.get("elo_home", 1500),
                elo_away=analysis.get("elo_away", 1500),
                league=league_name,
            )
            if _chim:
                _top = _chim[0]
                _cs  = _top.get("chimera_score", 0)
                report_text += (
                    f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━"
                    f"\n🧬 <b>CHIMERA Score: {round(_cs)}/100</b> — {_score_label(_cs)}"
                    f"\n├ ELO: {_top.get('elo_pts',0):+.0f}  "
                    f"Форма: {_top.get('form_pts',0):+.0f}  "
                    f"Ценность: {_top.get('value_pts',0):+.0f}  "
                    f"Вер-сть: {_top.get('prob_pts',0):+.0f}"
                    f"\n└ Рекомендация: <b>{_top.get('team','—')}</b>"
                )
        except Exception as _ce:
            logger.debug(f"[CHIMERA Basketball] {_ce}")

        # Expert Oracle (Reddit/СМИ) блок
        if _bb_expert_block:
            report_text += f"\n\n{_bb_expert_block}"

        from database import save_prediction
        pred_id = save_prediction(
            sport="basketball", match_id=m.get("id", f"{home}_{away}"),
            match_date=ct, home_team=home, away_team=away, league=league_name,
            gpt_verdict=_gpt_v,
            llama_verdict=_llama_v,
            recommended_outcome=_model_outcome,
            bet_signal=bet_signal,
            bookmaker_odds_home=odds.get("home_win"),
            bookmaker_odds_away=odds.get("away_win"),
            ensemble_home=round(h_prob, 3),
            ensemble_away=round(a_prob, 3),
            ensemble_best_outcome="home_win" if h_prob >= a_prob else "away_win",
        )

        from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
        kb = _IKB()
        if bet_signal.startswith("СТАВИТЬ") and fav_odds > 1.0 and pred_id:
            _odds_int = int(fav_odds * 100)
            _units_int = max(1, int(kelly)) if kelly > 0 else 1
            kb.button(
                text=f"✅ Я поставил на {fav} @ {fav_odds}",
                callback_data=f"mybet_basketball_{pred_id}_{_odds_int}_{_units_int}"
            )
        kb.button(text="🔙 Назад", callback_data=f"bball_league_{league_key}")
        kb.button(text="🏠 Меню", callback_data="back_to_main")
        kb.adjust(1)
        markup = kb.as_markup()

        _report_cache[_bb_cache_key] = {
            "text": report_text, "kb": markup,
            "parse_mode": "HTML", "ts": _time_bb.time()
        }
        await call.message.edit_text(report_text, parse_mode="HTML", reply_markup=markup)

    except Exception as e:
        logger.error(f"[Баскетбол анализ] {e}", exc_info=True)
        await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.")


@router.callback_query(lambda c: c.data and c.data.startswith("bball_mkt_"))
async def bball_market(call: types.CallbackQuery):
    import asyncio as _aio
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    parts = call.data.split("_")
    mkt_type  = parts[2]           # winner, total, spread
    match_idx = int(parts[-1])
    league_key = "_".join(parts[3:-1])

    _loop = _aio.get_running_loop()
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
    h_odds     = float(odds.get("home_win") or 1.9)
    a_odds     = float(odds.get("away_win") or 1.9)
    h_pct      = round(100 / h_odds, 1)
    a_pct      = round(100 / a_odds, 1)
    total_data = odds.get("total_analysis", {}) or {}
    total_line = total_data.get("line") or odds.get("total_over_line") or 220.5
    over_odds  = odds.get("total_over_odds") or 1.9
    under_odds = odds.get("total_under_odds") or 1.9
    spread_h   = odds.get("spread_home") or -3.5
    spread_a   = -spread_h

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

    back_kb = _IKB()
    back_kb.button(
        text="🏀 Победитель" if mkt_type != "winner" else "📊 Тотал",
        callback_data=f"bball_mkt_{'winner' if mkt_type != 'winner' else 'total'}_{league_key}_{match_idx}"
    )
    back_kb.button(
        text="⚖️ Фора" if mkt_type != "spread" else "📊 Тотал",
        callback_data=f"bball_mkt_{'spread' if mkt_type != 'spread' else 'total'}_{league_key}_{match_idx}"
    )
    back_kb.button(text="⬅️ Назад к матчу", callback_data=f"bball_match_{league_key}_{match_idx}")
    back_kb.button(text="↩️ К анализу",      callback_data=f"back_to_report_bball_{league_key}_{match_idx}")
    back_kb.button(text="🏠 Меню",            callback_data="back_to_main")
    back_kb.adjust(2)
    await call.answer()
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb.as_markup())
