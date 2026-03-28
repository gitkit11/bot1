# -*- coding: utf-8 -*-
"""handlers/football.py — все football callbacks: league_, m_, mkt_*, навигация матчей."""
import asyncio
import logging

from aiogram import Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

import state
from football_data import get_matches, get_bookmaker_odds
from keyboards import (
    FOOTBALL_LEAGUES, PAGE_SIZE,
    build_football_keyboard, build_matches_keyboard,
    build_markets_keyboard, build_back_to_markets_keyboard,
)
from formatters import (
    _safe_truncate, translate_outcome, conf_icon,
    format_main_report, format_goals_report, format_handicap_report,
)
from database import save_prediction, upsert_user, track_analysis, log_action
from state import matches_cache, analysis_cache, _report_cache, _REPORT_CACHE_TTL
from handlers.common import _elo_ratings, _team_form, _ai_semaphore, show_ai_thinking

logger = logging.getLogger(__name__)
router = Router()


# ─── Выбор лиги ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("league_"))
async def select_league(call: types.CallbackQuery):
    league_key  = call.data[7:]
    league_name = dict(FOOTBALL_LEAGUES).get(league_key, league_key)
    await call.answer()
    _loop_lg = asyncio.get_running_loop()
    matches = await _loop_lg.run_in_executor(None, lambda: get_matches(league=league_key, force=False))
    if not matches:
        await call.message.edit_text(f"⚽ *{league_name}*\n\n⏳ Загружаю матчи...", parse_mode="Markdown")
        try:
            matches = await asyncio.wait_for(
                _loop_lg.run_in_executor(None, lambda: get_matches(league=league_key, force=True)),
                timeout=20.0
            )
        except asyncio.TimeoutError:
            _err_kb = InlineKeyboardBuilder()
            _err_kb.button(text="🔄 Повторить", callback_data=f"league_{league_key}")
            _err_kb.button(text="⬅️ Лиги", callback_data="football")
            _err_kb.adjust(2)
            await call.message.edit_text(
                f"⚽ <b>{league_name}</b>\n\n⚠️ API не отвечает. Попробуй ещё раз.",
                parse_mode="HTML", reply_markup=_err_kb.as_markup()
            )
            return
    if not matches:
        _empty_kb = InlineKeyboardBuilder()
        _empty_kb.button(text="🔄 Обновить",   callback_data=f"league_{league_key}")
        _empty_kb.button(text="⬅️ Лиги",       callback_data="football")
        _empty_kb.adjust(2)
        await call.message.edit_text(
            f"⚽ <b>{league_name}</b>\n\n❌ Матчей пока нет. Попробуй через 5 минут.",
            parse_mode="HTML", reply_markup=_empty_kb.as_markup()
        )
        return
    await call.message.edit_text(
        f"⚽ *{league_name}*\n\nВыберите матч для анализа:",
        parse_mode="Markdown",
        reply_markup=build_matches_keyboard(matches)
    )


@router.callback_query(lambda c: c.data == "change_league")
async def change_league(call: types.CallbackQuery):
    league_name = dict(FOOTBALL_LEAGUES).get(state._current_league, "АПЛ")
    await call.message.edit_text(
        f"⚽ *Футбол* — выбери лигу:\nТекущая: *{league_name}*",
        parse_mode="Markdown",
        reply_markup=build_football_keyboard()
    )


@router.callback_query(lambda c: c.data == "back_to_matches")
async def back_to_matches(call: types.CallbackQuery):
    if not matches_cache:
        get_matches()
    await call.message.edit_text(
        "Выберите матч для анализа:",
        reply_markup=build_matches_keyboard(matches_cache, page=0)
    )


@router.callback_query(lambda c: c.data and c.data.startswith("matches_page_"))
async def matches_page(call: types.CallbackQuery):
    try:
        pg = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        pg = 0
    if not matches_cache:
        get_matches()
    await call.answer()
    total       = len(matches_cache)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    league_name = dict(FOOTBALL_LEAGUES).get(state._current_league, "Матчи")
    await call.message.edit_text(
        f"⚽ <b>{league_name}</b> — {total} матчей (стр. {pg+1}/{total_pages})\nВыберите матч:",
        parse_mode="HTML",
        reply_markup=build_matches_keyboard(matches_cache, page=pg)
    )


@router.callback_query(lambda c: c.data == "refresh_matches")
async def refresh_matches(call: types.CallbackQuery):
    await call.answer("🔄 Обновляю...")
    _loop_rm = asyncio.get_running_loop()
    try:
        matches = await asyncio.wait_for(
            _loop_rm.run_in_executor(None, lambda: get_matches(force=True)),
            timeout=20.0
        )
    except asyncio.TimeoutError:
        await call.message.edit_text(
            "😔 Произошёл сбой. Напиши нам в поддержку.",
            reply_markup=build_matches_keyboard(matches_cache)
        )
        return
    if not matches:
        await call.message.edit_text(
            "😔 Произошёл сбой. Напиши нам в поддержку.",
            reply_markup=build_matches_keyboard(matches_cache)
        )
        return
    league_name = dict(FOOTBALL_LEAGUES).get(state._current_league, "")
    await call.message.edit_text(
        f"✅ Список обновлён! {league_name}: {len(matches)} матчей.",
        reply_markup=build_matches_keyboard(matches)
    )


# ─── Меню рынков (из кеша) ────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("show_markets_"))
async def show_markets(call: types.CallbackQuery):
    try:
        match_index = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("⚠️ Некорректные данные.", show_alert=True)
        return
    if match_index >= len(matches_cache):
        await call.answer("⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.", show_alert=True)
        return
    match     = matches_cache[match_index]
    home_team = match["home_team"]
    away_team = match["away_team"]
    cached    = analysis_cache.get(match_index, {})
    if cached:
        from formatters import format_main_report as _fmt
        report = _fmt(
            home_team, away_team,
            cached["prophet_data"], cached["oracle_results"],
            cached["gpt_result"], cached["llama_result"],
            mixtral_result=cached.get("mixtral_result"),
            poisson_probs=cached.get("poisson_probs"),
            elo_probs=cached.get("elo_probs"),
            ensemble_probs=cached.get("ensemble_probs"),
            home_xg_stats=cached.get("home_xg_stats"),
            away_xg_stats=cached.get("away_xg_stats"),
            value_bets=cached.get("value_bets"),
            injuries_block=cached.get("injuries_block"),
            match_time=match.get('commence_time', ''),
            bookmaker_odds=cached.get("bookmaker_odds"),
        )
        await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_markets_keyboard(match_index))


# ─── Анализ матча (главный) ───────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("m_") and c.data[2:].isdigit())
async def analyze_match(call: types.CallbackQuery):
    try:
        match_index = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        await call.answer("⚠️ Некорректные данные.", show_alert=True)
        return
    if match_index >= len(matches_cache):
        await call.answer("⚠️ Матч не найден. Список мог устареть — вернись назад и обнови.", show_alert=True)
        return

    match     = matches_cache[match_index]
    home_team = match["home_team"]
    away_team = match["away_team"]

    # Кеш готового отчёта (45 мин)
    import time as _time_fb
    _fb_cache_key = f"football_{match_index}"
    _fb_cached    = _report_cache.get(_fb_cache_key)
    if _fb_cached and _time_fb.time() - _fb_cached.get("ts", 0) < _REPORT_CACHE_TTL:
        await call.answer()
        await call.message.edit_text(
            _fb_cached["text"], parse_mode=_fb_cached.get("parse_mode"),
            reply_markup=_fb_cached.get("kb"),
        )
        return

    _base = (
        f"<b>⚽ {home_team}  <code>vs</code>  {away_team}</b>\n"
        f"<b>🔮 CHIMERA AI</b> — запускаю анализ...\n\n"
    )
    _sm = await call.message.edit_text(
        _base + "🔮 <b>Пророк:</b> нейросеть считает вероятности...", parse_mode="HTML"
    )

    # ── Prophet + Oracle ──────────────────────────────────────────────────────
    from prophet_loader import get_prophet_prediction
    from oracle_ai import oracle_analyze
    prophet_data   = get_prophet_prediction(home_team, away_team)
    oracle_results = oracle_analyze(home_team, away_team)
    home_news      = oracle_results.get(home_team, {})
    away_news      = oracle_results.get(away_team, {})
    news_summary   = (
        f"Новости {home_team}: настроение {home_news.get('sentiment', 0):.2f}, "
        f"найдено {home_news.get('news_count', 0)} статей.\n"
        f"Новости {away_team}: настроение {away_news.get('sentiment', 0):.2f}, "
        f"найдено {away_news.get('news_count', 0)} статей."
    )

    try:
        await _sm.edit_text(
            _base +
            "🔮 <b>Пророк:</b> <i>готово ✓</i>\n"
            "🦁 <b>Лев:</b> <i>готово ✓</i>\n"
            "🐍 <b>Змея:</b> считает ELO, Пуассон, xG...",
            parse_mode="HTML"
        )
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")

    bookmaker_odds = get_bookmaker_odds(match)

    # ── API-Football статистика ────────────────────────────────────────────────
    from api_football import get_match_stats
    team_stats_text = get_match_stats(home_team, away_team) or ""

    # ── xG (Understat) ────────────────────────────────────────────────────────
    home_xg_stats = None
    away_xg_stats = None
    try:
        from understat_stats import get_team_xg_stats, format_xg_stats
        home_xg_stats = get_team_xg_stats(home_team)
        away_xg_stats = get_team_xg_stats(away_team)
        xg_stats_text = format_xg_stats(home_team, away_team)
        if xg_stats_text:
            team_stats_text = (team_stats_text + "\n\n" + xg_stats_text) if team_stats_text else xg_stats_text
    except Exception as _xe:
        logger.debug(f"[Understat] {_xe}")

    # Fallback xG из API-Football
    if not home_xg_stats:
        try:
            from config import API_FOOTBALL_KEY as _afk
            if _afk:
                from api_football import get_team_stats as _get_tf_stats
                _hf = _get_tf_stats(home_team)
                _af = _get_tf_stats(away_team)
                if _hf:
                    home_xg_stats = {
                        "avg_xg_last5": _hf.get("goals_scored_avg", 1.35),
                        "avg_xg_against_last5": _hf.get("goals_conceded_avg", 1.1),
                    }
                if _af:
                    away_xg_stats = {
                        "avg_xg_last5": _af.get("goals_scored_avg", 1.1),
                        "avg_xg_against_last5": _af.get("goals_conceded_avg", 1.35),
                    }
        except Exception:
            pass

    # ── ELO ──────────────────────────────────────────────────────────────────
    from math_model import elo_win_probabilities, get_form_string, calculate_expected_goals, poisson_match_probabilities
    elo_probs = None
    try:
        elo_probs = elo_win_probabilities(home_team, away_team, _elo_ratings, _team_form)
    except Exception as _ee:
        logger.debug(f"[ELO] {_ee}")

    # ── Пуассон ───────────────────────────────────────────────────────────────
    poisson_probs = None
    try:
        if home_xg_stats and away_xg_stats:
            home_exp, away_exp = calculate_expected_goals(home_xg_stats, away_xg_stats)
        elif home_xg_stats:
            home_exp, away_exp = home_xg_stats.get('avg_xg_last5', 1.35), 1.10
        elif away_xg_stats:
            home_exp, away_exp = 1.35, away_xg_stats.get('avg_xg_last5', 1.10)
        else:
            home_exp, away_exp = 1.35, 1.10
        poisson_probs = poisson_match_probabilities(home_exp, away_exp)
        poisson_probs['home_exp'] = round(home_exp, 2)
        poisson_probs['away_exp'] = round(away_exp, 2)
    except Exception as _pe:
        logger.debug(f"[Пуассон] {_pe}")

    # ── Dixon-Coles ML ────────────────────────────────────────────────────────
    _ml_block = ""
    _ml_pred  = {}
    try:
        from ml.predictor import get_football_prediction, format_ml_block as _fmt_ml
        _h_elo = elo_probs.get("home_elo", 1500) if elo_probs else 1500
        _a_elo = elo_probs.get("away_elo", 1500) if elo_probs else 1500
        _ml_pred  = get_football_prediction(home_team, away_team, bookmaker_odds, home_elo=_h_elo, away_elo=_a_elo)
        _ml_block = _fmt_ml(_ml_pred, home_team, away_team)
    except Exception as _mle:
        logger.debug(f"[ML] {_mle}")

    # ── Травмы ────────────────────────────────────────────────────────────────
    home_injuries = {}
    away_injuries = {}
    injuries_block = ""
    try:
        from injuries import get_match_injuries_async
        home_injuries, away_injuries, injuries_block = await get_match_injuries_async(home_team, away_team)
        if injuries_block and team_stats_text:
            team_stats_text += f"\n\n{injuries_block.replace('*', '')}"
        elif injuries_block:
            team_stats_text = injuries_block.replace('*', '')
    except Exception as _inj_e:
        logger.debug(f"[Травмы] {_inj_e}")

    # ── AI агенты ─────────────────────────────────────────────────────────────
    _loop = asyncio.get_running_loop()
    _form_h = get_form_string(home_team, _team_form)
    _form_a = get_form_string(away_team, _team_form)

    from agents import (
        run_statistician_agent, run_scout_agent, run_arbitrator_agent,
        run_llama_agent, run_mixtral_agent, build_math_ensemble, calculate_value_bets,
    )
    from circuit_breaker import get_breaker

    _cb_openai = get_breaker("openai", max_failures=3, recovery_timeout=300)
    async with _ai_semaphore:
        try:
            stats_result, scout_result = await asyncio.wait_for(
                asyncio.gather(
                    _loop.run_in_executor(None, lambda: run_statistician_agent(
                        prophet_data, team_stats_text,
                        poisson_probs=poisson_probs, elo_probs=elo_probs,
                        home_form=_form_h, away_form=_form_a,
                    )),
                    _loop.run_in_executor(None, run_scout_agent, home_team, away_team, news_summary),
                ),
                timeout=90.0
            )
            if not stats_result.get("error") and not scout_result.get("error"):
                _cb_openai.record_success()
            else:
                _cb_openai.record_failure()
        except asyncio.TimeoutError:
            stats_result = {"error": "Таймаут агента Статистик/Скаут (>90с)"}
            scout_result = {"error": "Таймаут агента Статистик/Скаут (>90с)"}
            _cb_openai.record_failure()

        try:
            gpt_result = await asyncio.wait_for(
                _loop.run_in_executor(None, lambda: run_arbitrator_agent(
                    stats_result, scout_result, bookmaker_odds,
                    poisson_probs=poisson_probs, elo_probs=elo_probs,
                )),
                timeout=90.0
            )
            if not gpt_result.get("error"):
                _cb_openai.record_success()
        except asyncio.TimeoutError:
            gpt_result = {"error": "Таймаут агента Арбитр (>90с)", "bet_signal": "ПРОПУСТИТЬ"}
            _cb_openai.record_failure()

    try:
        await _sm.edit_text(
            _base +
            "🔮 <b>Пророк:</b> <i>готово ✓</i>\n"
            "🦁 <b>Лев:</b> <i>готово ✓</i>\n"
            "🐍 <b>Змея:</b> <i>готово ✓</i>\n"
            "🐐 <b>Козёл:</b> <i>готово ✓</i>\n"
            "🌀 <b>Тень:</b> независимая проверка...",
            parse_mode="HTML"
        )
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")

    _cb_groq = get_breaker("groq", max_failures=3, recovery_timeout=300)
    async with _ai_semaphore:
        try:
            llama_result, mixtral_result = await asyncio.wait_for(
                asyncio.gather(
                    _loop.run_in_executor(None, lambda: run_llama_agent(
                        home_team, away_team, prophet_data, news_summary, bookmaker_odds,
                        team_stats_text, poisson_probs=poisson_probs, elo_probs=elo_probs,
                    )),
                    _loop.run_in_executor(None, run_mixtral_agent, home_team, away_team, prophet_data, news_summary, bookmaker_odds, team_stats_text, poisson_probs, elo_probs),
                ),
                timeout=90.0
            )
            if not llama_result.get("error"):
                _cb_groq.record_success()
            else:
                _cb_groq.record_failure()
        except asyncio.TimeoutError:
            llama_result   = {"error": "Таймаут агента Тень/Mixtral (>90с)"}
            mixtral_result = {"error": "Таймаут агента Тень/Mixtral (>90с)"}
            _cb_groq.record_failure()

    # ── Ансамбль ──────────────────────────────────────────────────────────────
    ensemble_probs = None
    value_bets     = []
    try:
        ensemble_probs = build_math_ensemble(
            prophet_data, poisson_probs, elo_probs,
            gpt_result, llama_result, mixtral_result,
            bookmaker_odds,
            dc_probs=_ml_pred if _ml_pred.get("model_used") == "Dixon-Coles" else None,
        )
        odds_for_value = {
            'home': bookmaker_odds.get('home_win', 0),
            'draw': bookmaker_odds.get('draw', 0),
            'away': bookmaker_odds.get('away_win', 0),
        }
        value_bets = calculate_value_bets(ensemble_probs, odds_for_value)
    except Exception as _ense:
        logger.debug(f"[Ансамбль] {_ense}")

    # ── Сигналы ───────────────────────────────────────────────────────────────
    football_ai_signals = []
    draw_signal = None
    _football_pred_id = None
    try:
        if not isinstance(gpt_result,     dict): gpt_result     = {}
        if not isinstance(llama_result,   dict): llama_result   = {}
        if not isinstance(mixtral_result, dict): mixtral_result = {}

        _gpt_out   = gpt_result.get("recommended_outcome", "")
        _llama_out = llama_result.get("recommended_outcome", "")
        _valid     = ("home_win", "away_win", "draw")
        if _gpt_out in _valid and _llama_out in _valid:
            ai_agrees_flag = _gpt_out == _llama_out
        elif _gpt_out in _valid or _llama_out in _valid:
            ai_agrees_flag = None
        else:
            ai_agrees_flag = None

        sig_probs = ensemble_probs or elo_probs or {}
        h_sig = sig_probs.get("home", 0.34)
        d_sig = sig_probs.get("draw", 0.33)
        a_sig = sig_probs.get("away", 0.33)
        elo_h = _elo_ratings.get(home_team, 1500)
        elo_a = _elo_ratings.get(away_team, 1500)
        form_h = get_form_string(home_team, _team_form)
        form_a = get_form_string(away_team, _team_form)

        from signal_engine import check_football_signal, check_draw_signal, format_signal, draw_radar as _draw_radar
        football_ai_signals = check_football_signal(
            home_team=home_team, away_team=away_team,
            home_prob=h_sig, away_prob=a_sig, draw_prob=d_sig,
            bookmaker_odds=bookmaker_odds,
            home_form=form_h, away_form=form_a,
            elo_home=elo_h, elo_away=elo_a,
            ai_agrees=ai_agrees_flag,
        )

        # ── Draw Radar: блокируем П1/П2 если 4+ индикаторов ничьей ──────────
        _draw_radar_result = None
        try:
            _draw_radar_result = _draw_radar(
                home_prob=h_sig, away_prob=a_sig, draw_prob=d_sig,
                bookmaker_odds=bookmaker_odds,
                home_form=form_h, away_form=form_a,
                elo_home=elo_h, elo_away=elo_a,
                poisson_probs=poisson_probs,
            )
            if _draw_radar_result.get("active"):
                # Radar активен — убираем сигналы П1/П2, ставка опасна
                football_ai_signals = [
                    s for s in football_ai_signals
                    if s.get("outcome") not in ("П1", "П2")
                ]
                logger.info(
                    f"[Draw Radar] {home_team} vs {away_team} — "
                    f"score {_draw_radar_result['score']}/7, сигналы П1/П2 заблокированы"
                )
        except Exception as _dre:
            logger.debug(f"[Draw Radar] {_dre}")

        _draw_odds = bookmaker_odds.get("draw") or bookmaker_odds.get("draw_win") or 0.0
        if not _draw_odds:
            try:
                _draw_odds = float(match.get("bookmakers", [{}])[0].get("markets", [{}])[0].get("outcomes", [{}])[1].get("price", 0) or 0)
            except Exception:
                _draw_odds = 0.0
        draw_signal = check_draw_signal(home_team, away_team, h_sig, a_sig, _draw_odds)
        if draw_signal:
            football_ai_signals = list(football_ai_signals) + [draw_signal]
    except Exception as _sig_e:
        logger.debug(f"[AI Сигнал] {_sig_e}")

    # ── Кеш для рынков ────────────────────────────────────────────────────────
    analysis_cache[match_index] = {
        "prophet_data": prophet_data, "oracle_results": oracle_results,
        "news_summary": news_summary, "bookmaker_odds": bookmaker_odds,
        "gpt_result": gpt_result, "llama_result": llama_result,
        "mixtral_result": mixtral_result, "poisson_probs": poisson_probs,
        "elo_probs": elo_probs, "ensemble_probs": ensemble_probs,
        "home_xg_stats": home_xg_stats, "away_xg_stats": away_xg_stats,
        "value_bets": value_bets, "home_team": home_team, "away_team": away_team,
        "match": match, "team_stats_text": team_stats_text,
        "injuries_block": injuries_block,
        "home_injuries": home_injuries, "away_injuries": away_injuries,
    }

    # ── Сохранение в БД ───────────────────────────────────────────────────────
    try:
        _probs_for_rec = (
            ensemble_probs or
            ({"home": elo_probs.get("home", 0), "draw": elo_probs.get("draw", 0), "away": elo_probs.get("away", 0)} if elo_probs else None) or
            ({"home": poisson_probs.get("home_win", 0), "draw": poisson_probs.get("draw", 0), "away": poisson_probs.get("away_win", 0)} if poisson_probs else None)
        )
        ens_best_key   = max(['home', 'draw', 'away'], key=lambda k: (_probs_for_rec or {}).get(k, 0)) if _probs_for_rec else "home"
        ens_best_map   = {'home': home_team, 'draw': 'Ничья', 'away': away_team}
        ens_best_label = ens_best_map.get(ens_best_key, home_team)
        _fb_bet_signal = "СТАВИТЬ" if football_ai_signals else "НЕ СТАВИТЬ"

        _football_pred_id = save_prediction(
            sport='football', match_id=str(match['id']),
            match_date=match.get('commence_time', ''),
            home_team=home_team, away_team=away_team,
            league=match.get('sport_key', 'soccer_epl'),
            gpt_verdict=gpt_result.get('recommended_outcome'),
            llama_verdict=llama_result.get('recommended_outcome'),
            gpt_confidence=gpt_result.get('final_confidence_percent', 0),
            llama_confidence=llama_result.get('final_confidence_percent', 0),
            bet_signal=_fb_bet_signal,
            total_goals_prediction=llama_result.get('total_goals_prediction'),
            btts_prediction=llama_result.get('both_teams_to_score_prediction'),
            bookmaker_odds_home=bookmaker_odds.get('home_win'),
            bookmaker_odds_draw=bookmaker_odds.get('draw'),
            bookmaker_odds_away=bookmaker_odds.get('away_win'),
            bookmaker_odds_over25=bookmaker_odds.get('over_2_5'),
            bookmaker_odds_under25=bookmaker_odds.get('under_2_5'),
            ensemble_home=(ensemble_probs or {}).get('home'),
            ensemble_draw=(ensemble_probs or {}).get('draw'),
            ensemble_away=(ensemble_probs or {}).get('away'),
            ensemble_best_outcome=ens_best_label,
            recommended_outcome={'home': 'home_win', 'draw': 'draw', 'away': 'away_win'}.get(ens_best_key, 'home_win'),
            poisson_home_win=(poisson_probs or {}).get('home_win'),
            poisson_draw=(poisson_probs or {}).get('draw'),
            poisson_away_win=(poisson_probs or {}).get('away_win'),
            poisson_over25=(poisson_probs or {}).get('over_25'),
            poisson_btts=(poisson_probs or {}).get('btts'),
            poisson_data_source='xg_based' if poisson_probs else None,
            elo_home=(elo_probs or {}).get('home_elo'),
            elo_away=(elo_probs or {}).get('away_elo'),
            elo_home_win=(elo_probs or {}).get('home'),
            elo_draw=(elo_probs or {}).get('draw'),
            elo_away_win=(elo_probs or {}).get('away'),
            prediction_data={
                "bet_signal": _fb_bet_signal,
                "ensemble_probs": ensemble_probs, "value_bets": value_bets,
                "league": match.get('sport_key', 'soccer_epl'),
            },
        )
    except Exception as _save_err:
        _football_pred_id = None
        logger.debug(f"[DB Save футбол] {_save_err}")

    try:
        upsert_user(call.from_user.id, call.from_user.username or "", call.from_user.first_name or "")
        track_analysis(call.from_user.id, "football")
        log_action(call.from_user.id, "анализ Футбол")
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")

    # ── CHIMERA Multi-Agent блок ───────────────────────────────────────────────
    _football_chimera_block = ""
    try:
        from agents import run_football_chimera_agents
        _fc = run_football_chimera_agents(
            home_team, away_team,
            ensemble_probs or elo_probs or {},
            bookmaker_odds,
            news_summary=news_summary,
            stats_text=team_stats_text or "",
            gpt_summary=gpt_result.get("final_verdict_summary", "") if gpt_result else "",
            llama_summary=llama_result.get("analysis_summary", "") if llama_result else "",
        )
        _football_chimera_block = _fc.get("verdict_block", "")
    except Exception as _fce:
        logger.debug(f"[Football CHIMERA] {_fce}")

    # ── Expert Oracle ─────────────────────────────────────────────────────────
    try:
        from expert_oracle import get_expert_consensus, format_expert_block
        _loop2 = asyncio.get_running_loop()
        _exp   = await _loop2.run_in_executor(None, get_expert_consensus, home_team, away_team, "football")
        _expert_block = format_expert_block(_exp, home_team, away_team)
        if _expert_block:
            _football_chimera_block = (_football_chimera_block + "\n\n" + _expert_block).strip()
    except Exception as _ee2:
        logger.debug(f"[ExpertOracle] {_ee2}")

    # ── Движение линий ────────────────────────────────────────────────────────
    _movement_block = ""
    try:
        from line_movement import make_match_key, record_odds, get_movement, format_movement_block
        _lm_key       = make_match_key(home_team, away_team, match.get("commence_time", ""))
        record_odds(_lm_key, bookmaker_odds)
        _movement     = get_movement(_lm_key, bookmaker_odds)
        _movement_block = format_movement_block(_movement) or ""
    except Exception as _lme:
        logger.debug(f"[ignore] {_lme}")

    # ── Финальный отчёт ───────────────────────────────────────────────────────
    final_report = format_main_report(
        home_team, away_team, prophet_data, oracle_results,
        gpt_result, llama_result, mixtral_result=mixtral_result,
        poisson_probs=poisson_probs, elo_probs=elo_probs,
        ensemble_probs=ensemble_probs,
        home_xg_stats=home_xg_stats, away_xg_stats=away_xg_stats,
        value_bets=value_bets, injuries_block=injuries_block,
        match_time=match.get('commence_time', ''),
        chimera_verdict_block=_football_chimera_block,
        ml_block=_ml_block, bookmaker_odds=bookmaker_odds,
        movement_block=_movement_block,
    )

    # ── Draw Radar блок в отчёте ─────────────────────────────────────────────
    try:
        _dr = _draw_radar_result if '_draw_radar_result' in dir() or '_draw_radar_result' in locals() else None
        if _dr and _dr.get("score", 0) >= 3:
            _dr_score = _dr["score"]
            _dr_icon = "🚨" if _dr.get("active") else "⚠️"
            _dr_status = "АКТИВЕН — ставки П1/П2 заблокированы" if _dr.get("active") else f"риск {_dr_score}/7"
            _dr_block = (
                f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━"
                f"\n{_dr_icon} *Draw Radar: {_dr_score}/7 — {_dr_status}*"
            )
            final_report = final_report + _dr_block
    except Exception:
        pass

    _football_kb = build_markets_keyboard(match_index)
    final_report = _safe_truncate(final_report)
    await call.message.edit_text(final_report, parse_mode="Markdown", reply_markup=_football_kb)

    import time as _time
    _report_cache[f"football_{match_index}"] = {
        "text": final_report, "kb": _football_kb,
        "parse_mode": "Markdown", "ts": _time.time(),
    }

    # ── AI-сигнал отдельным сообщением ────────────────────────────────────────
    if football_ai_signals:
        football_ai_signals.sort(key=lambda s: s.get("ev", 0), reverse=True)
        from signal_engine import format_signal
        top_sig = football_ai_signals[0]
        top_sig["sport"] = "football"
        try:
            from line_tracker import get_line_movement as _get_lm
            _lm = _get_lm(str(match.get("id", "")), top_sig.get("outcome", ""))
            if _lm:
                top_sig["line_movement"] = _lm
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")
        sig_text = format_signal(top_sig)
        if top_sig.get("draw_signal"):
            _gpt_s = gpt_result.get("summary", "") or ""
            _llm_s = llama_result.get("summary", "") or ""
            _gpt_c = gpt_result.get("confidence", 0)
            _llm_c = llama_result.get("confidence", 0)
            if _gpt_s or _llm_s:
                sig_text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━\n🤖 <b>Мнения агентов о матче:</b>\n"
                if _gpt_s: sig_text += f"🐍🦁🐐 Химера ({_gpt_c}%): <i>{_gpt_s[:250]}</i>\n"
                if _llm_s: sig_text += f"🌀 Тень ({_llm_c}%): <i>{_llm_s[:250]}</i>\n"
                sig_text += "⚠️ <i>Агенты анализировали исход матча, не ставку на ничью</i>"
        sig_text = "🐉 <b>ХИМЕРА (Змея + Лев + Козёл + Тень)</b>\n\n" + sig_text
        _sig_kb = None
        if _football_pred_id:
            _f_kelly   = top_sig.get("kelly", 2)
            _f_units   = 3 if _f_kelly >= 4 else (2 if _f_kelly >= 2 else 1)
            _f_odds    = top_sig.get("odds", 0)
            _f_odds_enc = int(round((_f_odds or 0) * 100))
            _sig_kb = types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(
                    text=f"✅ Я поставил {_f_units}u — записать в статистику",
                    callback_data=f"mybet_football_{_football_pred_id}_{_f_odds_enc}_{_f_units}"
                )
            ]])
        try:
            await call.message.answer(sig_text, parse_mode="HTML", reply_markup=_sig_kb)
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")

        for _extra_sig in football_ai_signals[1:]:
            try:
                _extra_text = "🔀 <b>Дополнительный сигнал</b>\n\n" + format_signal(_extra_sig)
                if _extra_sig.get("draw_signal"):
                    _gpt_s2 = gpt_result.get("summary", "") or ""
                    _llm_s2 = llama_result.get("summary", "") or ""
                    _gpt_c2 = gpt_result.get("confidence", 0)
                    _llm_c2 = llama_result.get("confidence", 0)
                    if _gpt_s2 or _llm_s2:
                        _extra_text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━\n🤖 <b>Мнения агентов о матче:</b>\n"
                        if _gpt_s2: _extra_text += f"🐍🦁🐐 Химера ({_gpt_c2}%): <i>{_gpt_s2[:250]}</i>\n"
                        if _llm_s2: _extra_text += f"🌀 Тень ({_llm_c2}%): <i>{_llm_s2[:250]}</i>\n"
                        _extra_text += "⚠️ <i>Агенты анализировали исход матча, не ставку на ничью</i>"
                await call.message.answer(_extra_text, parse_mode="HTML")
            except Exception as _e:
                logger.debug(f"[ignore extra sig] {_e}")


# ─── Рынки ────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("mkt_winner_"))
async def mkt_winner(call: types.CallbackQuery):
    try:
        match_index = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("⚠️ Некорректные данные.", show_alert=True)
        return
    cached = analysis_cache.get(match_index)
    if not cached:
        await call.answer("Сначала запустите анализ матча.", show_alert=True)
        return

    home_team      = cached["home_team"]
    away_team      = cached["away_team"]
    gpt_result     = cached["gpt_result"]
    llama_result   = cached["llama_result"]
    prophet_data   = cached["prophet_data"]
    bookmaker_odds = cached["bookmaker_odds"]

    gpt_verdict  = translate_outcome(gpt_result.get("recommended_outcome", ""), home_team, away_team)
    gpt_conf     = gpt_result.get("final_confidence_percent", 0)
    gpt_odds_val = gpt_result.get("bookmaker_odds", 0)
    gpt_stake    = gpt_result.get("recommended_stake_percent", 0)
    gpt_ev       = gpt_result.get("expected_value_percent", 0)
    bet_signal   = gpt_result.get("bet_signal", "ПРОПУСТИТЬ")
    signal_reason = gpt_result.get("signal_reason", "")
    llama_verdict = translate_outcome(llama_result.get("recommended_outcome", ""), home_team, away_team)
    llama_conf    = llama_result.get("final_confidence_percent", 0)
    signal_icon   = "🔥 СТАВИТЬ!" if bet_signal == "СТАВИТЬ" else "❌ НЕ СТАВИТЬ"

    report = f"""
🏆 *ПОБЕДИТЕЛЬ МАТЧА*
{home_team} vs {away_team}
━━━━━━━━━━━━━━━━━━━━━━━━━

📊 *Пророк (нейросеть):*
 П1: {(prophet_data[1]*100 if prophet_data else 0):.0f}% | Х: {(prophet_data[0]*100 if prophet_data else 0):.0f}% | П2: {(prophet_data[2]*100 if prophet_data else 0):.0f}%

🐍🦁🐐 *Вердикт Химеры:*
{conf_icon(gpt_conf)} {gpt_verdict} — {gpt_conf}%
🎯 Кэф: {gpt_odds_val} | Ставка: {gpt_stake:.1f}% | EV: +{gpt_ev:.1f}%

🌀 *Вердикт Тени:*
{conf_icon(llama_conf)} {llama_verdict} — {llama_conf}%

━━━━━━━━━━━━━━━━━━━━━━━━━
*{signal_icon}*
_{signal_reason}_
""".strip()
    await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))


@router.callback_query(lambda c: c.data and c.data.startswith("mkt_goals_"))
async def mkt_goals(call: types.CallbackQuery):
    try:
        match_index = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("⚠️ Некорректные данные.", show_alert=True)
        return
    cached = analysis_cache.get(match_index)
    if not cached:
        await call.answer("Сначала запустите анализ матча.", show_alert=True)
        return
    await call.message.edit_text("⏳ *Анализирую рынок голов...*", parse_mode="Markdown")
    from agents import run_goals_market_agent
    goals_result = run_goals_market_agent(
        cached["home_team"], cached["away_team"],
        cached.get("news_summary", ""), cached["bookmaker_odds"]
    )
    report = format_goals_report(
        cached["home_team"], cached["away_team"],
        goals_result, cached["bookmaker_odds"], cached.get("poisson_probs")
    )
    await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))


@router.callback_query(lambda c: c.data and c.data.startswith("mkt_handicap_"))
async def mkt_handicap(call: types.CallbackQuery):
    try:
        match_index = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("⚠️ Некорректные данные.", show_alert=True)
        return
    cached = analysis_cache.get(match_index)
    if not cached:
        await call.answer("Сначала запустите анализ матча.", show_alert=True)
        return
    await call.message.edit_text("⏳ *Анализирую гандикапы...*", parse_mode="Markdown")
    from agents import run_handicap_market_agent
    handicap_result = run_handicap_market_agent(
        cached["home_team"], cached["away_team"],
        cached["prophet_data"], cached["bookmaker_odds"],
        cached["gpt_result"], cached["llama_result"]
    )
    report = format_handicap_report(cached["home_team"], cached["away_team"], handicap_result)
    await call.message.edit_text(report, parse_mode="Markdown", reply_markup=build_back_to_markets_keyboard(match_index))
