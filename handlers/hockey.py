# -*- coding: utf-8 -*-
"""handlers/hockey.py — /hockey и все hockey_ callbacks"""
import asyncio
import logging
import concurrent.futures as _cf
from datetime import datetime, timedelta

from aiogram import Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from state import _report_cache, _REPORT_CACHE_TTL
from handlers.common import show_ai_thinking

logger = logging.getLogger(__name__)
router = Router()

# Кэш матчей по лиге: {league_key: [матчи]}
_hockey_cache: dict = {}

# Кэш данных анализа для рынков: {"hockey_{league_key}_{idx}": {analysis, odds, home, away, ct, league_name}}
_hockey_analysis_cache: dict = {}


async def cmd_hockey(message: types.Message):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🏒 NHL",             callback_data="hockey_league_icehockey_nhl")],
        [types.InlineKeyboardButton(text="🇸🇪 SHL",            callback_data="hockey_league_icehockey_sweden_hockey_league")],
        [types.InlineKeyboardButton(text="🇺🇸 AHL",            callback_data="hockey_league_icehockey_ahl")],
        [types.InlineKeyboardButton(text="🇫🇮 Finnish Liiga",  callback_data="hockey_league_icehockey_liiga")],
        [types.InlineKeyboardButton(text="🇸🇪 Allsvenskan",    callback_data="hockey_league_icehockey_sweden_allsvenskan")],
    ])
    await message.answer(
        "<b>🏒 ХОККЕЙ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\nВыбери лигу:",
        parse_mode="HTML", reply_markup=kb
    )


@router.callback_query(lambda c: c.data and c.data.startswith("hockey_league_"))
async def hockey_select_league(call: types.CallbackQuery):
    league_key = call.data.replace("hockey_league_", "")

    league_names = {
        "icehockey_nhl":                    "🏒 NHL",
        "icehockey_sweden_hockey_league":   "🇸🇪 SHL",
        "icehockey_ahl":                    "🇺🇸 AHL",
        "icehockey_liiga":                  "🇫🇮 Finnish Liiga",
        "icehockey_sweden_allsvenskan":     "🇸🇪 Allsvenskan",
    }
    league_name = league_names.get(league_key, league_key)

    await call.answer()
    status = await call.message.edit_text(
        f"{league_name}\n⏳ Загружаю матчи...", parse_mode="HTML"
    )

    try:
        from sports.hockey import get_hockey_matches
        loop = asyncio.get_running_loop()
        matches = await loop.run_in_executor(None, get_hockey_matches, league_key)
        _hockey_cache[league_key] = matches

        if not matches:
            await status.edit_text(
                f"{league_name}\n\n📭 Матчей не найдено.", parse_mode="HTML"
            )
            return

        buttons = []
        for i, m in enumerate(matches):
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            ct   = m.get("commence_time", "")
            try:
                dt     = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                dt_msk = dt + timedelta(hours=3)
                time_label = dt_msk.strftime("%d.%m %H:%M")
            except Exception:
                time_label = ct[:10]
            _bm = m.get("bookmaker_odds", {})
            h_odds = _bm.get("home_win") or m.get("home_win") or 0
            a_odds = _bm.get("away_win") or m.get("away_win") or 0
            odds_str = f"  {h_odds}/{a_odds}" if h_odds and a_odds else ""
            buttons.append([types.InlineKeyboardButton(
                text=f"🏒 {time_label}  {home} — {away}{odds_str}",
                callback_data=f"hockey_match_{league_key}_{i}"
            )])
        buttons.append([types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")])
        kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await status.edit_text(
            f"<b>{league_name}</b> — {len(matches)} матчей\nВыбери матч для анализа:",
            parse_mode="HTML", reply_markup=kb
        )
    except Exception as e:
        logger.error(f"[Хоккей] Ошибка: {e}")
        await status.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.", parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("hockey_match_"))
async def hockey_analyze_match(call: types.CallbackQuery):
    await call.answer()
    parts      = call.data.split("_")
    idx        = int(parts[-1])
    # league_key = всё между "hockey_match_" и последним "_idx"
    league_key = "_".join(parts[2:-1])

    matches = _hockey_cache.get(league_key, [])
    if idx >= len(matches):
        await call.message.edit_text(
            "⚠️ Матч не найден. Список мог устареть — вернись и обнови.",
            parse_mode="HTML"
        )
        return

    import time as _time_hk
    _hk_cache_key = f"hockey_{league_key}_{idx}"
    _hk_cached = _report_cache.get(_hk_cache_key)
    if _hk_cached and _time_hk.time() - _hk_cached.get("ts", 0) < _REPORT_CACHE_TTL:
        await call.message.edit_text(
            _hk_cached["text"],
            parse_mode=_hk_cached.get("parse_mode"),
            reply_markup=_hk_cached.get("kb"),
        )
        return

    m    = matches[idx]
    home = m.get("home_team", "")
    away = m.get("away_team", "")
    ct   = m.get("commence_time", "")

    try:
        dt     = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        dt_msk = dt + timedelta(hours=3)
        time_label = dt_msk.strftime("%d.%m %H:%M МСК")
    except Exception:
        time_label = ct[:16]

    league_names = {
        "icehockey_nhl":                    "🏒 NHL",
        "icehockey_sweden_hockey_league":   "🇸🇪 SHL",
        "icehockey_ahl":                    "🇺🇸 AHL",
        "icehockey_liiga":                  "🇫🇮 Finnish Liiga",
        "icehockey_sweden_allsvenskan":     "🇸🇪 Allsvenskan",
    }
    league_name = league_names.get(league_key, league_key)

    status_msg = await call.message.edit_text(
        f"⏳ <b>{home} vs {away}</b>", parse_mode="HTML"
    )
    await show_ai_thinking(status_msg, home, away, sport="hockey")

    try:
        from sports.hockey.core import get_hockey_odds, calculate_hockey_win_prob
        from agents import client as _gpt_client, groq_client as _groq_client

        odds     = get_hockey_odds(m)
        analysis = calculate_hockey_win_prob(
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
            fav, fav_prob, fav_odds, fav_ev = home, h_prob, odds.get("home_win", 0), h_ev
        else:
            fav, fav_prob, fav_odds, fav_ev = away, a_prob, odds.get("away_win", 0), a_ev

        kelly = 0.0
        if fav_odds > 1.02 and fav_ev > 0:
            kelly = round((fav_prob - (1 - fav_prob) / (fav_odds - 1)) * 100, 1)
            kelly = max(0.0, min(kelly, 25.0))

        await call.message.edit_text(
            f"🏒 <b>{home} vs {away}</b>\n⏳ Запускаю AI анализ...", parse_mode="HTML"
        )

        home_form  = analysis.get("home_form", "")
        away_form  = analysis.get("away_form", "")
        home_b2b   = analysis.get("home_b2b", False)
        away_b2b   = analysis.get("away_b2b", False)
        home_goals = analysis.get("home_goals", {})
        away_goals = analysis.get("away_goals", {})

        form_block = ""
        if home_form or away_form:
            form_block = f"Форма: {home}={home_form or '—'}, {away}={away_form or '—'}\n"
        b2b_block = ""
        if home_b2b:
            b2b_block += f"⚠️ {home} играл вчера (усталость!)\n"
        if away_b2b:
            b2b_block += f"⚠️ {away} играл вчера (усталость!)\n"
        goals_block = ""
        if home_goals.get("gp", 0) >= 3 and away_goals.get("gp", 0) >= 3:
            goals_block = (
                f"Голы/игра: {home}={home_goals['gf']} GF/{home_goals['ga']} GA | "
                f"{away}={away_goals['gf']} GF/{away_goals['ga']} GA\n"
            )
        total_block = ""
        if total_data:
            total_block = (
                f"Тотал: {total_data['line']} "
                f"(Б {total_data['over_odds']} / М {total_data['under_odds']})."
            )

        # Новости и травмы — параллельно, перед AI запросами
        news_block = ""
        injuries_block = ""
        try:
            from oracle_ai import oracle_analyze as _oracle
            import asyncio as _aio
            _loop = _aio.get_event_loop()
            _oracle_fut = _loop.run_in_executor(None, _oracle, home, away)
            try:
                from injuries import get_match_injuries_async as _inj_async
                _h_inj, _a_inj, injuries_block = await _aio.wait_for(
                    _inj_async(home, away), timeout=8.0
                )
            except Exception:
                pass
            _oracle_res = await _aio.wait_for(_oracle_fut, timeout=10.0)
            _h_news = _oracle_res.get(home, {})
            _a_news = _oracle_res.get(away, {})
            _h_cnt  = _h_news.get("news_count", 0)
            _a_cnt  = _a_news.get("news_count", 0)
            _h_sent = _h_news.get("sentiment", 0)
            _a_sent = _a_news.get("sentiment", 0)
            def _sent_icon(s):
                return "📈" if s > 0.05 else ("📉" if s < -0.05 else "➡️")
            if _h_cnt > 0 or _a_cnt > 0:
                news_block = (
                    f"Новости: {home} {_sent_icon(_h_sent)}({_h_cnt}) | "
                    f"{away} {_sent_icon(_a_sent)}({_a_cnt})\n"
                )
        except Exception:
            pass

        # Expert Oracle: Reddit + СМИ для хоккея
        _hk_expert_block = ""
        try:
            import concurrent.futures as _cf_hk
            def _fetch_hk_expert():
                try:
                    from expert_oracle import get_expert_consensus, format_expert_block
                    exp = get_expert_consensus(home, away, "hockey")
                    return format_expert_block(exp, home, away) or ""
                except Exception:
                    return ""
            with _cf_hk.ThreadPoolExecutor(max_workers=1) as _pool_hk:
                _hk_expert_block = _pool_hk.submit(_fetch_hk_expert).result(timeout=12)
        except Exception as _hk_oe:
            logger.debug(f"[HK Expert] {_hk_oe}")

        def _run_gpt_hockey():
            try:
                import json as _json
                _elo_gap = analysis.get("elo_gap", 0)
                _nv_h = odds.get("no_vig_home", 0)
                _nv_a = odds.get("no_vig_away", 0)
                prompt = (
                    f"Хоккей. {league_name}. {home} vs {away}. {time_label}.\n"
                    f"ELO: {home}={analysis.get('elo_home',1550)}, {away}={analysis.get('elo_away',1550)} (разрыв {_elo_gap})\n"
                    f"Наша модель: {home}={round(h_prob*100)}% | {away}={round(a_prob*100)}%\n"
                    f"Букмекер no-vig: {home}={round(_nv_h*100,1)}% | {away}={round(_nv_a*100,1)}%\n"
                    f"Кэфы: {home}={odds.get('home_win','?')} | {away}={odds.get('away_win','?')}\n"
                    f"EV: {home}={round(h_ev*100,1)}% | {away}={round(a_ev*100,1)}%\n"
                    f"{form_block}{b2b_block}{goals_block}{total_block}"
                    f"{news_block}{injuries_block}"
                    f"{('Reddit/СМИ: ' + _hk_expert_block[:200] + chr(10)) if _hk_expert_block else ''}\n\n"
                    f"Напиши аналитический summary из 2-3 предложений:\n"
                    f"1) Главное преимущество фаворита — ELO разрыв, форма, домашний лёд, усталость B2B.\n"
                    f"2) Что говорит расхождение нашей модели с линией букмекера — где рынок недооценил?\n"
                    f"3) Уверенный вывод по тоталу — быстрый или позиционный хоккей.\n"
                    f"Если есть новости или травмы — учти их в анализе.\n"
                    f"Пиши как эксперт-беттор. Только факты и цифры, никакой воды.\n"
                    f"Формат ответа: {{'verdict': 'home_win'/'away_win', 'confidence': 0-100, 'summary': '...'}}"
                )
                resp = _gpt_client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[
                        {"role": "system", "content": "Ты — Химера, математический аналитик хоккея. Говоришь уверенно, кратко, с цифрами. Никогда не пишешь общих фраз — только конкретные выводы из данных."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4, max_tokens=350,
                )
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
                logger.warning(f"[GPT Hockey] {_e}")
                return {"summary": ""}

        def _run_llama_hockey():
            try:
                import json as _json
                prompt = (
                    f"Hockey. {league_name}. {home} vs {away}.\n"
                    f"Model: {home}={round(h_prob*100)}% | {away}={round(a_prob*100)}%\n"
                    f"Odds: {home}={odds.get('home_win','?')} | {away}={odds.get('away_win','?')}\n"
                    f"EV: {home}={round(h_ev*100,1)}% | {away}={round(a_ev*100,1)}%\n"
                    f"{form_block}{b2b_block}{goals_block}{news_block}{injuries_block}"
                    f"Write an independent 2-sentence sharp take:\n"
                    f"1) The key factor the model might miss (fatigue, home ice advantage, recent momentum, injuries).\n"
                    f"2) Your confident verdict with one specific reason — no hedging.\n"
                    f"JSON: {{'verdict': 'home_win'/'away_win', 'confidence': 0-100, 'summary': '...'}}"
                )
                resp = _groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are Shadow — a sharp, independent hockey analyst. You find angles others overlook. Be direct, specific, confident. No filler."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3, max_tokens=250,
                )
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
                logger.warning(f"[Llama Hockey] {_e}")
                return {"summary": ""}

        with _cf.ThreadPoolExecutor(max_workers=2) as pool:
            gpt_f   = pool.submit(_run_gpt_hockey)
            llama_f = pool.submit(_run_llama_hockey)
            gpt_r   = gpt_f.result(timeout=25)
            llama_r = llama_f.result(timeout=20)

        # AI Gate: повышаем/понижаем тир на основе согласия агентов
        from signal_engine import apply_ai_gate as _ai_gate
        _model_outcome = "home_win" if h_prob >= a_prob else "away_win"
        _gpt_v   = gpt_r.get("verdict", "")
        _llama_v = llama_r.get("verdict", "")
        bet_signal = _ai_gate(bet_signal, _model_outcome, _gpt_v, _llama_v)
        analysis = dict(analysis)
        analysis["bet_signal"] = bet_signal

        from sports.hockey.core import format_hockey_report
        report_text = format_hockey_report(
            home_team=home, away_team=away,
            analysis=analysis, odds=odds,
            gpt_result=gpt_r, llama_result=llama_r,
            match_time=ct, league_name=league_name,
        )

        # Травмы/дисквалификации — если есть, добавляем блок
        if injuries_block:
            report_text += f"\n\n{injuries_block.strip()}"

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
                elo_home=analysis.get("elo_home", 1550),
                elo_away=analysis.get("elo_away", 1550),
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
            logger.debug(f"[CHIMERA Hockey] {_ce}")

        if _hk_expert_block:
            report_text += f"\n\n{_hk_expert_block}"

        from database import save_prediction
        pred_id = save_prediction(
            sport="hockey",
            match_id=m.get("id", f"{home}_{away}"),
            match_date=ct,
            home_team=home, away_team=away, league=league_name,
            gpt_verdict=_gpt_v,
            llama_verdict=_llama_v,
            recommended_outcome=_model_outcome,
            bet_signal=bet_signal,
            bookmaker_odds_home=odds.get("home_win") or None,
            bookmaker_odds_away=odds.get("away_win") or None,
            ensemble_home=round(h_prob, 3),
            ensemble_away=round(a_prob, 3),
            ensemble_best_outcome="home_win" if h_prob >= a_prob else "away_win",
        )

        kb = InlineKeyboardBuilder()
        kb.button(text="🏒 Тотал шайб",    callback_data=f"hockey_mkt_total_{league_key}_{idx}")
        kb.button(text="📐 Пак-лайн (-1.5)", callback_data=f"hockey_mkt_puckline_{league_key}_{idx}")
        if bet_signal.startswith("СТАВИТЬ") and fav_odds > 1.0 and pred_id:
            _odds_int  = int(fav_odds * 100)
            _units_int = max(1, int(kelly)) if kelly > 0 else 1
            kb.button(
                text=f"✅ Я поставил на {fav} @ {fav_odds}",
                callback_data=f"mybet_hockey_{pred_id}_{_odds_int}_{_units_int}"
            )
        kb.button(text="🔙 Назад", callback_data=f"hockey_league_{league_key}")
        kb.button(text="🏠 Меню",  callback_data="back_to_main")
        kb.adjust(1)
        markup = kb.as_markup()

        # Сохраняем данные для рыночных хэндлеров
        _hockey_analysis_cache[_hk_cache_key] = {
            "analysis":    analysis,
            "odds":        odds,
            "home":        home,
            "away":        away,
            "ct":          ct,
            "league_name": league_name,
            "league_key":  league_key,
            "idx":         idx,
        }

        _report_cache[_hk_cache_key] = {
            "text": report_text, "kb": markup,
            "parse_mode": "HTML", "ts": _time_hk.time()
        }
        await call.message.edit_text(report_text, parse_mode="HTML", reply_markup=markup)

    except Exception as e:
        logger.error(f"[Хоккей анализ] {e}", exc_info=True)
        await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.")


def _back_to_hockey_kb(league_key: str, idx: int) -> types.InlineKeyboardMarkup:
    """Кнопки возврата из рыночного отчёта в основной анализ."""
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ К анализу",  callback_data=f"back_to_hockey_report_{league_key}_{idx}")
    kb.button(text="🔙 К лиге",    callback_data=f"hockey_league_{league_key}")
    kb.button(text="🏠 Меню",      callback_data="back_to_main")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(lambda c: c.data and c.data.startswith("back_to_hockey_report_"))
async def back_to_hockey_report(call: types.CallbackQuery):
    await call.answer()
    data   = call.data[len("back_to_hockey_report_"):]
    parts  = data.rsplit("_", 1)
    if len(parts) != 2:
        await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.")
        return
    league_key, idx_str = parts
    key    = f"hockey_{league_key}_{idx_str}"
    cached = _report_cache.get(key)
    if cached:
        await call.message.edit_text(
            cached["text"],
            parse_mode=cached.get("parse_mode", "HTML"),
            reply_markup=cached.get("kb"),
        )
    else:
        await call.message.edit_text(
            "⚠️ Анализ устарел. Выбери матч заново.",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("hockey_mkt_total_"))
async def hockey_mkt_total(call: types.CallbackQuery):
    await call.answer()
    data   = call.data[len("hockey_mkt_total_"):]
    parts  = data.rsplit("_", 1)
    if len(parts) != 2:
        await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.")
        return
    league_key, idx_str = parts
    key    = f"hockey_{league_key}_{idx_str}"
    cached = _hockey_analysis_cache.get(key)
    if not cached:
        await call.message.edit_text(
            "⚠️ Данные устарели. Вернись и выбери матч заново.", parse_mode="HTML"
        )
        return

    from sports.hockey.core import analyze_hockey_total_deep, format_hockey_total_report
    total  = analyze_hockey_total_deep(
        cached["analysis"]["home_prob"],
        cached["analysis"]["away_prob"],
        cached["odds"],
    )
    report = format_hockey_total_report(
        cached["home"], cached["away"], total,
        cached["ct"], cached["league_name"],
    )
    await call.message.edit_text(
        report, parse_mode="HTML",
        reply_markup=_back_to_hockey_kb(league_key, int(idx_str)),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("hockey_mkt_puckline_"))
async def hockey_mkt_puckline(call: types.CallbackQuery):
    await call.answer()
    data   = call.data[len("hockey_mkt_puckline_"):]
    parts  = data.rsplit("_", 1)
    if len(parts) != 2:
        await call.message.edit_text("😔 Произошёл сбой. Напиши нам в поддержку.")
        return
    league_key, idx_str = parts
    key    = f"hockey_{league_key}_{idx_str}"
    cached = _hockey_analysis_cache.get(key)
    if not cached:
        await call.message.edit_text(
            "⚠️ Данные устарели. Вернись и выбери матч заново.", parse_mode="HTML"
        )
        return

    from sports.hockey.core import analyze_puckline, format_hockey_puckline_report
    puckline = analyze_puckline(
        cached["home"], cached["away"],
        cached["analysis"]["home_prob"],
        cached["analysis"]["away_prob"],
        cached["odds"],
    )
    report = format_hockey_puckline_report(
        cached["home"], cached["away"], puckline,
        cached["ct"], cached["league_name"],
    )
    await call.message.edit_text(
        report, parse_mode="HTML",
        reply_markup=_back_to_hockey_kb(league_key, int(idx_str)),
    )
