# -*- coding: utf-8 -*-
"""handlers/cs2.py — CS2 callbacks: cs2_m_, cs2_league_, back_to_cs2"""
import asyncio
import logging

from aiogram import Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import save_prediction, upsert_user, track_analysis, log_action
from formatters import _safe_truncate
from handlers.common import show_ai_thinking, CS2_WHITELIST_LEAGUES
from state import cs2_matches_cache, _report_cache, _REPORT_CACHE_TTL

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(lambda c: c.data and c.data.startswith("cs2_m_"))
async def cs2_analyze_match(call: types.CallbackQuery):
    try:
        match_index = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("⚠️ Некорректные данные.", show_alert=True)
        return
    if match_index >= len(cs2_matches_cache):
        await call.answer("⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.", show_alert=True)
        return
    m = cs2_matches_cache[match_index]
    home_team = m["home"]
    away_team = m["away"]

    import time as _time_cs2
    _cs2_cache_key = f"cs2_{match_index}"
    _cs2_cached = _report_cache.get(_cs2_cache_key)
    if _cs2_cached and _time_cs2.time() - _cs2_cached.get("ts", 0) < _REPORT_CACHE_TTL:
        await call.answer()
        await call.message.edit_text(
            _cs2_cached["text"], parse_mode=_cs2_cached.get("parse_mode"),
            reply_markup=_cs2_cached.get("kb"),
        )
        return

    status_msg = await call.message.edit_text(f"⏳ {home_team} vs {away_team}", parse_mode="HTML")
    await show_ai_thinking(status_msg, home_team, away_team, sport="cs2")
    try:
        from sports.cs2 import calculate_cs2_win_prob, get_golden_signal, format_cs2_full_report, run_cs2_analyst_agent
        from sports.cs2.pandascore import classify_tournament
        from signal_engine import check_cs2_signal, predict_cs2_totals, get_cs2_ranked_bets

        _league = m.get("league", "")
        _tournament = m.get("tournament", "")
        _ctx = classify_tournament(_league, _tournament)
        analysis = calculate_cs2_win_prob(home_team, away_team, tournament_context=_ctx)
        analysis["home_team"] = home_team
        analysis["away_team"] = away_team
        odds = m.get("odds", {"home_win": 1.90, "away_win": 1.90})

        try:
            from line_movement import make_match_key, record_odds as _record_cs2_odds
            _cs2_lm_key = make_match_key(home_team, away_team, m.get("commence_time", ""))
            _record_cs2_odds(_cs2_lm_key, odds)
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")

        golden_signals = get_golden_signal(analysis, odds)
        h_stats = analysis.get("home_stats", {})
        a_stats = analysis.get("away_stats", {})
        h2h = analysis.get("h2h", {})
        _h_si = analysis.get("home_standin", {})
        _a_si = analysis.get("away_standin", {})
        map_stats_for_ai = {mp: {"home_prob": round(hp, 2), "away_prob": round(ap, 2)} for mp, hp, ap in analysis.get("maps", [])}
        _data_conf = analysis.get("data_confidence", 1.0)

        gpt_text = run_cs2_analyst_agent(
            home_team, away_team, map_stats_for_ai, odds,
            agent_type="gpt-4o", home_stats=h_stats, away_stats=a_stats, h2h=h2h,
            tournament_context=_ctx, home_standin=_h_si, away_standin=_a_si,
            data_confidence=_data_conf,
        )
        llama_text = run_cs2_analyst_agent(
            home_team, away_team, map_stats_for_ai, odds,
            agent_type="llama-3.3", home_stats=h_stats, away_stats=a_stats, h2h=h2h,
            tournament_context=_ctx, home_standin=_h_si, away_standin=_a_si,
            data_confidence=_data_conf,
        )

        h_players = analysis.get("home_players", [])
        a_players = analysis.get("away_players", [])
        h_avg_rating = sum(p['rating'] for p in h_players) / len(h_players) if h_players else 0
        a_avg_rating = sum(p['rating'] for p in a_players) / len(a_players) if a_players else 0
        predicted_maps = [mp for mp, _, _ in analysis.get("maps", [])]
        home_map_wr = {mp: hp for mp, hp, _ in analysis.get("maps", [])}
        away_map_wr = {mp: ap for mp, _, ap in analysis.get("maps", [])}
        ai_agrees = None
        if gpt_text and not gpt_text.startswith("❌") and home_team.lower() in gpt_text.lower():
            ai_agrees = True
        signal_checks = check_cs2_signal(
            home_team=home_team, away_team=away_team,
            home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
            bookmaker_odds=odds,
            home_form=h_stats.get("form", ""), away_form=a_stats.get("form", ""),
            elo_home=analysis.get("elo_home", 0), elo_away=analysis.get("elo_away", 0),
            mis_home=analysis["detail"].get("mis", 0), mis_away=1 - analysis["detail"].get("mis", 0),
            home_avg_rating=h_avg_rating, away_avg_rating=a_avg_rating,
            home_map_winrates=home_map_wr, away_map_winrates=away_map_wr,
            predicted_maps=predicted_maps,
            ai_cs2_agrees=ai_agrees,
        )

        home_map_stats_raw = {mp: hp * 100 for mp, hp, _ in analysis.get("maps", [])}
        away_map_stats_raw = {mp: ap * 100 for mp, _, ap in analysis.get("maps", [])}
        totals_data = predict_cs2_totals(
            home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
            home_map_stats=home_map_stats_raw, away_map_stats=away_map_stats_raw,
            predicted_maps=predicted_maps,
        )
        try:
            from signal_engine import predict_cs2_round_totals
            round_totals = predict_cs2_round_totals(
                home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
                home_map_stats=home_map_stats_raw, away_map_stats=away_map_stats_raw,
                predicted_maps=predicted_maps,
            )
            if totals_data and round_totals:
                totals_data["round_prediction"] = round_totals["rounds_prediction"]
                totals_data["round_confidence"] = round_totals["rounds_confidence"]
                totals_data["round_reason"]     = round_totals["rounds_reason"]
        except Exception as _rte:
            logger.debug(f"[CS2 Rounds] {_rte}")

        ranked_bets = get_cs2_ranked_bets(
            home_team=home_team, away_team=away_team,
            home_prob=analysis["home_prob"], away_prob=analysis["away_prob"],
            bookmaker_odds=odds,
            totals_data=totals_data,
            home_form=h_stats.get("form", ""),
            away_form=a_stats.get("form", ""),
        )

        _cs2_verdict_block = ""
        try:
            from sports.cs2.agents import run_cs2_chimera_agents
            _math_probs_cs2 = {"home": analysis.get("home_prob", 0.5), "away": analysis.get("away_prob", 0.5)}
            _chimera_cs2 = run_cs2_chimera_agents(
                home_team, away_team, _math_probs_cs2, odds,
                home_stats=h_stats, away_stats=a_stats, h2h=h2h,
                tournament_context=_ctx, home_standin=_h_si, away_standin=_a_si,
            )
            _cs2_verdict_block = _chimera_cs2.get("verdict_block", "")
        except Exception as _ce:
            logger.debug(f"[CS2 Chimera] {_ce}")

        try:
            from expert_oracle import get_expert_consensus, format_expert_block
            _loop_cs2 = asyncio.get_running_loop()
            _exp_cs2 = await _loop_cs2.run_in_executor(None, get_expert_consensus, home_team, away_team, "cs2")
            _expert_block_cs2 = format_expert_block(_exp_cs2, home_team, away_team)
            if _expert_block_cs2:
                _cs2_verdict_block = (_cs2_verdict_block + "\n\n" + _expert_block_cs2).strip()
        except Exception as _ee_cs2:
            logger.debug(f"[ExpertOracle CS2] {_ee_cs2}")

        report = format_cs2_full_report(
            home_team, away_team, analysis, gpt_text, llama_text,
            golden_signals, bookmaker_odds=odds, signal_checks=signal_checks,
            ranked_bets=ranked_bets, totals_data=totals_data,
            chimera_verdict_block=_cs2_verdict_block,
            commence_time=m.get("commence_time"),
        )

        try:
            top_bet = ranked_bets[0] if ranked_bets else None
            rec_outcome = None
            if top_bet:
                if top_bet["type"] == "П1":
                    rec_outcome = "home_win"
                elif top_bet["type"] == "П2":
                    rec_outcome = "away_win"
            if not rec_outcome:
                rec_outcome = "home_win" if analysis["home_prob"] >= analysis["away_prob"] else "away_win"
            _cs2_home_odds = odds.get("home_win") or None
            _cs2_away_odds = odds.get("away_win") or None

            def _cs2_parse_verdict(txt, ht, at):
                if not txt or txt.startswith("❌"):
                    return ""
                tl = txt.lower()
                h_words = [w.lower() for w in ht.split() if len(w) > 3]
                a_words = [w.lower() for w in at.split() if len(w) > 3]
                h_score = sum(tl.count(w) for w in h_words)
                a_score = sum(tl.count(w) for w in a_words)
                if h_score > a_score: return "home_win"
                if a_score > h_score: return "away_win"
                return ""

            _cs2_gpt_verdict   = _cs2_parse_verdict(gpt_text,   home_team, away_team)
            _cs2_llama_verdict = _cs2_parse_verdict(llama_text, home_team, away_team)

            _cs2_pred_id = save_prediction(
                sport="cs2",
                match_id=str(m.get("id", f"{home_team}_{away_team}")),
                match_date=m.get("commence_time") or m.get("time", ""),
                home_team=home_team, away_team=away_team,
                league=m.get("league", "CS2"),
                gpt_verdict=_cs2_gpt_verdict, llama_verdict=_cs2_llama_verdict,
                recommended_outcome=rec_outcome,
                bet_signal="СТАВИТЬ" if signal_checks else "ПРОПУСТИТЬ",
                elo_home=analysis.get("elo_home"), elo_away=analysis.get("elo_away"),
                elo_home_win=analysis["detail"].get("elo"),
                elo_away_win=round(1 - analysis["detail"].get("elo", 0.5), 3),
                ensemble_home=analysis["home_prob"], ensemble_away=analysis["away_prob"],
                ensemble_best_outcome="home_win" if analysis["home_prob"] >= analysis["away_prob"] else "away_win",
                bookmaker_odds_home=_cs2_home_odds, bookmaker_odds_away=_cs2_away_odds,
                predicted_maps=predicted_maps,
                prediction_data={
                    "total_prediction": totals_data.get("prediction") if totals_data else None,
                    "top_bet_type": top_bet["type"] if top_bet else None,
                    "top_bet_odds": top_bet["odds"] if top_bet else None,
                    "top_bet_ev":   top_bet["ev"]   if top_bet else None,
                    "signal_score": signal_checks[0]["score"] if signal_checks else None,
                }
            )
        except Exception as save_err:
            _cs2_pred_id = None
            logger.error(f"[CS2 Save] {save_err}")

        try:
            upsert_user(call.from_user.id, call.from_user.username or "", call.from_user.first_name or "")
            track_analysis(call.from_user.id, "cs2")
            log_action(call.from_user.id, "анализ CS2")
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")

        cs2_markets_kb = InlineKeyboardBuilder()
        cs2_markets_kb.button(text="🏆 Победитель матча", callback_data=f"cs2_mkt_winner_{match_index}")
        cs2_markets_kb.button(text="🗺️ По картам",        callback_data=f"cs2_mkt_maps_{match_index}")
        cs2_markets_kb.button(text="🎯 Тотал раундов",    callback_data=f"cs2_mkt_rounds_{match_index}")
        cs2_markets_kb.button(text="⬅️ Матчи",            callback_data="back_to_cs2")
        cs2_markets_kb.button(text="🏠 Меню",             callback_data="back_to_main")
        if _cs2_pred_id and ranked_bets:
            _cs2_bet_odds = ranked_bets[0].get("odds", 0) or odds.get("home_win" if rec_outcome == "home_win" else "away_win", 0) or 0
            _cs2_odds_enc = int(round(_cs2_bet_odds * 100))
            _cs2_kelly    = ranked_bets[0].get("kelly", 2)
            _cs2_units    = 3 if _cs2_kelly >= 4 else (2 if _cs2_kelly >= 2 else 1)
            cs2_markets_kb.button(
                text=f"✅ Я поставил {_cs2_units}u — записать в статистику",
                callback_data=f"mybet_cs2_{_cs2_pred_id}_{_cs2_odds_enc}_{_cs2_units}"
            )
        cs2_markets_kb.adjust(2)
        _cs2_kb = cs2_markets_kb.as_markup()
        report = _safe_truncate(report)
        try:
            await call.message.edit_text(report, parse_mode="Markdown", reply_markup=_cs2_kb)
        except Exception as _md_err:
            logger.warning(f"[CS2 Markdown] Fallback plain text: {_md_err}")
            import re as _re
            plain_report = _re.sub(r'[*_`\[\]]', '', report)
            await call.message.edit_text(plain_report, parse_mode=None, reply_markup=_cs2_kb)

        import time as _time
        _report_cache[f"cs2_{match_index}"] = {
            "text": report, "kb": _cs2_kb,
            "parse_mode": "Markdown", "ts": _time.time(),
        }
    except Exception as e:
        logger.error(f"[CS2 анализ] Ошибка: {e}", exc_info=True)
        _fail_kb = InlineKeyboardBuilder()
        _fail_kb.button(text="🔄 Повторить", callback_data=call.data)
        _fail_kb.button(text="🏠 Меню",      callback_data="back_to_main")
        _fail_kb.adjust(2)
        await call.message.edit_text(
            "😔 Произошёл сбой. Напиши нам в поддержку.",
            reply_markup=_fail_kb.as_markup()
        )


@router.callback_query(lambda c: c.data and c.data.startswith("cs2_league_"))
async def cs2_select_league(call: types.CallbackQuery):
    league_name = call.data[11:]
    league_matches = [
        m for m in cs2_matches_cache
        if league_name.lower() in f"{m.get('league', '')} {m.get('tournament', '')}".lower()
    ]
    if not league_matches:
        await call.answer("Матчи не найдены.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for m in league_matches:
        idx = cs2_matches_cache.index(m)
        tier_icon = {"S": "🏆", "A": "🎯", "B": "🎮"}.get(m.get("tier", "B"), "🎮")
        label = f"{tier_icon} {m['home']} vs {m['away']} | {m['time']}"
        builder.button(text=label, callback_data=f"cs2_m_{idx}")
    builder.button(text="⬅️ Назад к лигам", callback_data="back_to_cs2_leagues")
    builder.adjust(1)
    await call.message.edit_text(
        f"🏆 *{league_name}* — матчи:\nВыберите матч для анализа:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(lambda c: c.data in ("back_to_cs2_leagues", "back_to_cs2"))
async def cs2_back_to_leagues(call: types.CallbackQuery):
    if not cs2_matches_cache:
        await call.answer("⏰ Список устарел. Нажми ⬅️ Назад и открой лигу заново.", show_alert=True)
        return

    display_leagues: dict = {}
    for m in cs2_matches_cache:
        full_name = f"{m.get('league', '')} {m.get('tournament', '')}".lower()
        for allowed in CS2_WHITELIST_LEAGUES:
            if allowed.lower() in full_name:
                display_leagues[allowed] = display_leagues.get(allowed, 0) + 1
                break

    builder = InlineKeyboardBuilder()
    for league, count in sorted(display_leagues.items()):
        builder.button(text=f"🏆 {league} ({count})", callback_data=f"cs2_league_{league}")
    builder.adjust(1)
    await call.message.edit_text(
        "🎮 *CS2* — Выберите лигу:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cs2_mkt_"))
async def cs2_market(call: types.CallbackQuery):
    parts     = call.data.split("_")
    mkt_type  = parts[2]       # winner, maps, rounds
    match_idx = int(parts[3])
    m = cs2_matches_cache[match_idx] if match_idx < len(cs2_matches_cache) else None
    if not m:
        await call.answer("Матч не найден", show_alert=True)
        return
    home = m.get("home", "")
    away = m.get("away", "")

    from sports.cs2 import calculate_cs2_win_prob as _cs2_prob
    _loop = asyncio.get_running_loop()
    analysis = await _loop.run_in_executor(None, _cs2_prob, home, away)
    h_prob = analysis.get("home_prob", 0.5)
    a_prob = analysis.get("away_prob", 0.5)
    h_odds = round(1 / h_prob, 2) if h_prob > 0.01 else 1.9
    a_odds = round(1 / a_prob, 2) if a_prob > 0.01 else 1.9
    h_pct  = round(h_prob * 100, 1)
    a_pct  = round(a_prob * 100, 1)

    if mkt_type == "winner":
        text = (
            f"🏆 <b>Победитель матча</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>{home} vs {away}</b>\n\n"
            f"{'✅' if h_pct > a_pct else '▫️'} <b>{home}</b>\n"
            f"   Вероятность: <b>{h_pct}%</b> | Кэф: <b>{h_odds}</b>\n\n"
            f"{'✅' if a_pct > h_pct else '▫️'} <b>{away}</b>\n"
            f"   Вероятность: <b>{a_pct}%</b> | Кэф: <b>{a_odds}</b>\n\n"
            f"<i>💡 Ставь на {'<b>' + home + '</b>' if h_pct > a_pct else '<b>' + away + '</b>'} "
            f"если кэф у букмекера ≥ {min(h_odds, a_odds):.2f}</i>"
        )
    elif mkt_type == "maps":
        balance = 1 - abs(h_prob - a_prob)
        h_map1   = round(min(max(h_pct + 2, 30), 70), 1)
        a_map1   = round(100 - h_map1, 1)
        score_2_0 = round(balance * 20 + max(h_pct, a_pct) * 0.2, 1)
        score_2_1 = round(100 - score_2_0, 1)
        winner    = home if h_pct > a_pct else away
        text = (
            f"🗺️ <b>По картам</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>{home} vs {away}</b>\n\n"
            f"<b>Победа на карте 1:</b>\n"
            f"  {'✅' if h_map1 > a_map1 else '▫️'} {home}: <b>{h_map1}%</b>\n"
            f"  {'✅' if a_map1 > h_map1 else '▫️'} {away}: <b>{a_map1}%</b>\n\n"
            f"<b>Счёт серии:</b>\n"
            f"  📊 {winner} 2:0 → <b>{score_2_0:.0f}%</b>\n"
            f"  📊 {winner} 2:1 → <b>{score_2_1:.0f}%</b>\n\n"
            f"<i>💡 Лучший вариант: <b>{winner}</b> выигрывает серию</i>"
        )
    elif mkt_type == "rounds":
        balance  = 1 - abs(h_prob - a_prob)
        expected = round(24.5 + balance * 5, 1)
        over     = expected > 26.5
        text = (
            f"🎯 <b>Тотал раундов (Карта 1)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>{home} vs {away}</b>\n\n"
            f"📊 Прогноз раундов: <b>{expected}</b>\n\n"
            f"{'✅' if over else '▫️'} <b>Больше 26.5</b>\n"
            f"{'✅' if not over else '▫️'} <b>Меньше 26.5</b>\n\n"
            f"<i>{'⚖️ Равный матч — много раундов' if balance > 0.6 else '💪 Один доминирует — короткие карты'}</i>"
        )
    else:
        text = "⚠️ Неизвестный рынок"

    back_kb = InlineKeyboardBuilder()
    back_kb.button(
        text="🏆 Победитель" if mkt_type != "winner" else "🗺️ По картам",
        callback_data=f"cs2_mkt_{'winner' if mkt_type != 'winner' else 'maps'}_{match_idx}"
    )
    back_kb.button(
        text="🎯 Тотал раундов" if mkt_type != "rounds" else "🏆 Победитель",
        callback_data=f"cs2_mkt_{'rounds' if mkt_type != 'rounds' else 'winner'}_{match_idx}"
    )
    back_kb.button(text="↩️ К анализу", callback_data=f"back_to_report_cs2_{match_idx}")
    back_kb.button(text="🏠 Меню",       callback_data="back_to_main")
    back_kb.adjust(2)
    await call.answer()
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb.as_markup())
