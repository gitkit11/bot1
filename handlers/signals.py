# -*- coding: utf-8 -*-
"""handlers/signals.py — /signals (CHIMERA SIGNAL ENGINE) + chimera_ callbacks."""
import asyncio
import logging

from aiogram import Router, types
from aiogram.filters import Command

from database import (
    save_prediction, get_user_bankroll, log_action, mark_user_bet,
)
from formatters import (
    _format_chimera_page, _build_chimera_kb, _build_chimera_carousel_kb,
)
from keyboards import FOOTBALL_LEAGUES
from math_model import get_form_string, elo_win_probabilities
from state import (
    cs2_matches_cache,
    _signals_scan_cache, SIGNALS_SCAN_TTL,
)
from handlers.common import _elo_ratings, _team_form
from football_data import get_bookmaker_odds

logger = logging.getLogger(__name__)
router = Router()

_signals_scan_in_progress: bool = False

CS2_TIER3_KEYWORDS = [
    "regional", "open", "qualifier", "division", "roman imperium",
    "nodwin", "exort", "dust2.dk", "game masters",
]


async def _send_access_denied(message: types.Message, reason: str):
    """Отправляет сообщение об отказе в доступе."""
    from access import get_access_denied_text
    text = get_access_denied_text(reason)
    if reason == "no_channel":
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="📢 Подписаться на канал",
                url="https://t.me/chimera_bet_community"
            )],
            [types.InlineKeyboardButton(
                text="✅ Я подписался",
                callback_data="reenter_main"
            )],
        ])
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("signals"))
async def cmd_signals(message: types.Message):
    """Кнопка 'Сигналы дня'."""
    global _signals_scan_in_progress
    if message.from_user and not getattr(message.from_user, 'is_bot', False):
        log_action(message.from_user.id, "signals")
        from access import check_access
        reason = await check_access(message.from_user.id, message.bot,
                                    require_full=True, count_analysis=False)
        if reason != "ok":
            await _send_access_denied(message, reason)
            return
    import time as _time_mod
    from chimera_signal import compute_chimera_score, run_ai_verification, format_chimera_signals

    # ── Кеш: если скан свежий (<45 мин) — отдаём моментально ────────────────
    _cached = _signals_scan_cache.get("last")
    if _cached and _cached.get("candidates") and "_pred_id" not in _cached["candidates"][0]:
        _cached = None
        _signals_scan_cache.clear()
    if _cached and (_time_mod.time() - _cached["ts"]) < SIGNALS_SCAN_TTL:
        top_candidates       = _cached["candidates"]
        _chimera_top_pred_id = _cached.get("top_pred_id")
        _chimera_top_sport   = _cached.get("top_sport", "football")
        _chimera_top_odds    = _cached.get("top_odds", 0)
        _cache_age_min = int((_time_mod.time() - _cached["ts"]) / 60)
        print(f"[CHIMERA] Кеш сигналов использован (возраст {_cache_age_min} мин)")
        try:
            _broll_sig = get_user_bankroll(message.from_user.id) or 0
            result_text = _format_chimera_page(top_candidates, 0, bankroll=_broll_sig)
            result_text += f"\n\n<i>🕐 Обновлено {_cache_age_min} мин назад</i>"
            _chimera_kb = _build_chimera_kb(
                top_candidates, _chimera_top_pred_id, _chimera_top_sport,
                _chimera_top_odds, message.from_user.id
            )
            await message.answer(result_text, parse_mode="HTML", reply_markup=_chimera_kb)
        except Exception as _ce:
            logger.error(f"[CHIMERA Cache] Ошибка форматирования: {_ce}")
            await message.answer("⚠️ Ошибка загрузки кеша. Перезапускаю скан...", parse_mode="HTML")
            _signals_scan_cache.clear()
            await cmd_signals(message)
        return

    if _signals_scan_in_progress:
        await message.answer(
            "⏳ <b>Сканирование уже идёт...</b>\n"
            "<i>Подожди — результаты появятся через 30–90 секунд.</i>",
            parse_mode="HTML"
        )
        return

    _signals_scan_in_progress = True
    status_msg = await message.answer(
        "🔍 <b>CHIMERA SIGNAL запущен...</b>\n\n"
        "⏳ <i>Это займёт 30–90 секунд — Химера сканирует рынок.</i>\n\n"
        "⚙️ Шаг 1/3: Загрузка матчей (Футбол + CS2 + Теннис + Баскетбол)...",
        parse_mode="HTML"
    )

    try:
        from agents import client as _gpt_client, groq_client as _groq_client
    except ImportError:
        _gpt_client = None
        _groq_client = None

    try:
        from line_movement import make_match_key, record_odds, get_movement
        _line_movement_ok = True
    except ImportError:
        _line_movement_ok = False

    try:
        from api_football import get_h2h
        _h2h_ok = True
    except ImportError:
        _h2h_ok = False

    all_candidates = []
    _scan_errors = []

    def _run_math_scan():
        """Весь блокирующий скан — запускается в thread executor."""
        import concurrent.futures as _cf
        from datetime import datetime, timezone as _tz, timedelta as _td
        import requests as _req
        from odds_cache import get_odds as _get_odds

        _now = datetime.now(_tz.utc)
        _tomorrow_end = (_now + _td(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
        _cutoff_future = _tomorrow_end.isoformat()[:19]
        _cutoff_past   = (_now - _td(hours=3)).isoformat()[:19]

        def _fetch_league(lkey):
            raw = _get_odds(lkey, markets="h2h,totals,spreads")
            if raw is None:
                return "quota", []
            if isinstance(raw, list):
                filtered = [m for m in raw
                            if _cutoff_past < m.get("commence_time", "") <= _cutoff_future]
                return lkey, filtered
            return lkey, []

        def _fetch_bball_league(lkey):
            raw = _get_odds(lkey, markets="h2h,totals,spreads")
            if raw and isinstance(raw, list):
                now2 = datetime.now(_tz.utc)
                cutoff2 = (now2 - _td(hours=2)).isoformat()[:19]
                return lkey, [m for m in raw if m.get("commence_time", "") > cutoff2][:25]
            return lkey, []

        def _scan_football(matches):
            cands = []
            try:
                from historical_movement import get_line_movement as _get_hist_mov
                _hist_mov_ok = True
            except ImportError:
                _hist_mov_ok = False

            for m in matches[:30]:
                try:
                    home = m.get("home_team", "")
                    away = m.get("away_team", "")
                    if not home or not away:
                        continue
                    odds = get_bookmaker_odds(m)
                    if not odds.get("home_win"):
                        continue
                    elo_h  = _elo_ratings.get(home, 1500)
                    elo_a  = _elo_ratings.get(away, 1500)
                    form_h = get_form_string(home, _team_form)
                    form_a = get_form_string(away, _team_form)
                    elo_p  = elo_win_probabilities(home, away, _elo_ratings, _team_form)
                    _movement = {}
                    if _line_movement_ok and odds:
                        _mkey = make_match_key(home, away, m.get("commence_time", ""))
                        record_odds(_mkey, odds)
                        _movement = get_movement(_mkey, odds)
                    c_list = compute_chimera_score(
                        home_team=home, away_team=away,
                        home_prob=elo_p["home"], away_prob=elo_p["away"], draw_prob=elo_p["draw"],
                        bookmaker_odds=odds, home_form=form_h, away_form=form_a,
                        elo_home=elo_h, elo_away=elo_a,
                        league=m.get("sport_key", ""), line_movement=_movement,
                    )
                    _ct       = m.get("commence_time", "")
                    _mid      = m.get("id", "")
                    _sport_key = m.get("sport_key", "")
                    for c in c_list:
                        c["commence_time"] = _ct
                        if _hist_mov_ok and odds.get("pinnacle_home"):
                            try:
                                hist_mov = _get_hist_mov(
                                    sport_key=_sport_key,
                                    match_id=_mid,
                                    home_team=home, away_team=away,
                                    current_pinnacle_home=odds.get("pinnacle_home", 0),
                                    current_pinnacle_away=odds.get("pinnacle_away", 0),
                                    current_pinnacle_draw=odds.get("pinnacle_draw", 0),
                                )
                                if hist_mov.get("score_boost"):
                                    c["chimera_score"] = c.get("chimera_score", 0) + hist_mov["score_boost"]
                                    c["hist_movement"] = hist_mov
                            except Exception as _e:
                                logger.debug(f"[ignore] {_e}")
                    cands.extend(c_list)
                except Exception as _ce:
                    print(f"[CHIMERA] Ошибка {m.get('home_team','')} vs {m.get('away_team','')}: {_ce}")
            return cands

        def _scan_cs2():
            cands = []
            try:
                from sports.cs2 import calculate_cs2_win_prob
                from signal_engine import predict_cs2_totals as _ps_totals

                _cs2_source = cs2_matches_cache
                if not _cs2_source:
                    try:
                        from sports.cs2.pandascore import get_cs2_matches_pandascore
                        _fetched = get_cs2_matches_pandascore()
                        if _fetched:
                            cs2_matches_cache.clear()
                            cs2_matches_cache.extend(_fetched)
                            _cs2_source = _fetched
                            print(f"[CHIMERA CS2] Загружено {len(_fetched)} матчей из PandaScore")
                    except Exception as _fe:
                        print(f"[CHIMERA CS2] Ошибка фетча матчей: {_fe}")

                for m in _cs2_source[:25]:
                    try:
                        home = m.get("home", "")
                        away = m.get("away", "")
                        if not home or not away:
                            continue
                        _ct        = m.get("commence_time", "") or m.get("time", "")
                        _cs2_tier  = m.get("tier", "B")
                        _league_low = (m.get("league", "") + " " + m.get("tournament", "")).lower()
                        _is_t3 = any(kw in _league_low for kw in CS2_TIER3_KEYWORDS) or _cs2_tier not in ("S", "A")
                        if _is_t3:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: Tier-3/regional")
                            continue
                        analysis   = calculate_cs2_win_prob(home, away)
                        h_prob     = analysis.get("home_prob", 0)
                        a_prob     = analysis.get("away_prob", 0)
                        if not h_prob:
                            continue
                        data_conf = analysis.get("data_confidence", 0)
                        if data_conf < 0.45:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: нет данных (conf={data_conf:.2f})")
                            continue
                        elo_h_val = analysis.get("elo_home", 0)
                        elo_a_val = analysis.get("elo_away", 0)
                        if elo_h_val > 0 and elo_a_val > 0 and abs(elo_h_val - elo_a_val) < 150:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: ELO разрыв мал ({abs(elo_h_val - elo_a_val)})")
                            continue
                        raw_odds = m.get("odds", {})
                        h_odds   = raw_odds.get("home_win")
                        a_odds   = raw_odds.get("away_win")
                        # Требуем РЕАЛЬНЫЕ кэфы от букмекера — без них EV и Kelly считаются неверно
                        if not h_odds or not a_odds:
                            print(f"[CHIMERA CS2] Пропуск {home} vs {away}: нет реальных кэфов")
                            continue
                        h_stats  = analysis.get("home_stats", {})
                        a_stats  = analysis.get("away_stats", {})
                        c_list   = compute_chimera_score(
                            home_team=home, away_team=away,
                            home_prob=h_prob, away_prob=a_prob, draw_prob=0,
                            bookmaker_odds={"home_win": h_odds, "away_win": a_odds, "draw": 0},
                            home_form=h_stats.get("form", ""), away_form=a_stats.get("form", ""),
                            elo_home=analysis.get("elo_home", 1450), elo_away=analysis.get("elo_away", 1450),
                            league="CS2",
                            apply_calibration=False,
                        )
                        try:
                            _cs2_totals = _ps_totals(
                                home_prob=h_prob, away_prob=a_prob,
                                home_map_stats={mp: hp * 100 for mp, hp, _ in analysis.get("maps", [])},
                                away_map_stats={mp: ap * 100 for mp, _, ap in analysis.get("maps", [])},
                                predicted_maps=[mp for mp, _, _ in analysis.get("maps", [])],
                            )
                        except Exception:
                            _cs2_totals = None
                        for c in c_list:
                            c["sport"]       = "cs2"
                            c["commence_time"] = _ct
                            c["cs2_tier"]    = _cs2_tier
                            c["tier_label"]  = m.get("tier_label", "🎮")
                            c["totals_data"] = _cs2_totals
                        cands.extend(c_list)
                    except Exception as _ce:
                        print(f"[CHIMERA CS2] Ошибка {m.get('home','')} vs {m.get('away','')}: {_ce}")
            except Exception as e:
                print(f"[CHIMERA] CS2 ошибка: {e}")
            return cands

        def _scan_tennis():
            try:
                from sports.tennis import scan_tennis_signals
                from sports.tennis.matches import get_tennis_matches, get_active_tennis_sports
                sport_keys = get_active_tennis_sports()
                print(f"[CHIMERA] Теннис: активных турниров = {len(sport_keys)}: {sport_keys[:5]}")
                if not sport_keys:
                    print("[CHIMERA] Теннис: нет активных турниров в The Odds API")
                    return []
                raw_matches = get_tennis_matches()
                print(f"[CHIMERA] Теннис: матчей с коэффициентами = {len(raw_matches)}")
                if not raw_matches:
                    return []
                cands = scan_tennis_signals()
                cands = [c for c in cands if c.get("prob", 0) >= 55]
                print(f"[CHIMERA] Теннис: кандидатов после скана = {len(cands)}")
                return cands
            except Exception as e:
                import traceback
                print(f"[CHIMERA] Теннис ошибка: {e}")
                traceback.print_exc()
                return []

        def _scan_hockey():
            cands = []
            try:
                from sports.hockey import get_hockey_matches
                from sports.hockey.core import get_hockey_odds, calculate_hockey_win_prob
                for league_key, league_name in [
                    ("icehockey_nhl",                  "🏒 NHL"),
                    ("icehockey_sweden_hockey_league", "🇸🇪 SHL"),
                    ("icehockey_ahl",                  "🇺🇸 AHL"),
                    ("icehockey_liiga",                "🇫🇮 Finnish Liiga"),
                    ("icehockey_sweden_allsvenskan",   "🇸🇪 Allsvenskan"),
                ]:
                    try:
                        matches = get_hockey_matches(league_key)
                        for hm in matches[:15]:
                            try:
                                home = hm.get("home_team", "")
                                away = hm.get("away_team", "")
                                if not home or not away:
                                    continue
                                _ct = hm.get("commence_time", "")
                                if _ct and _ct > _cutoff_future:
                                    continue
                                hodds = get_hockey_odds(hm)
                                if not hodds.get("home_win") or not hodds.get("away_win"):
                                    continue
                                hres = calculate_hockey_win_prob(
                                    home, away, hodds, league_key,
                                    no_vig_home=hodds.get("no_vig_home", 0.0),
                                    no_vig_away=hodds.get("no_vig_away", 0.0),
                                )
                                hp = hres.get("home_prob", 0)
                                ap = hres.get("away_prob", 0)
                                if not hp:
                                    continue
                                if hres.get("no_elo_data"):
                                    logger.debug(f"[CHIMERA HOCKEY] Пропуск {home} vs {away}: нет ELO данных")
                                    continue
                                if hres.get("bet_signal", "") == "НЕ СТАВИТЬ":
                                    continue
                                hcands = compute_chimera_score(
                                    home_team=home, away_team=away,
                                    home_prob=hp, away_prob=ap, draw_prob=0,
                                    bookmaker_odds={"home_win": hodds.get("home_win", 0),
                                                   "away_win": hodds.get("away_win", 0), "draw": 0},
                                    home_form=hres.get("home_form", ""), away_form=hres.get("away_form", ""),
                                    elo_home=hres.get("elo_home", 1550), elo_away=hres.get("elo_away", 1550),
                                    league=league_key,
                                    apply_calibration=False,
                                )
                                for hc in hcands:
                                    hc["sport"]       = "hockey"
                                    hc["league_name"] = league_name
                                    hc["commence_time"] = _ct
                                cands.extend(hcands)
                            except Exception as _he:
                                logger.debug(f"[CHIMERA HOCKEY] {home} vs {away}: {_he}")
                    except Exception as _le:
                        logger.debug(f"[CHIMERA HOCKEY] {league_key}: {_le}")
                print(f"[CHIMERA] Хоккей: {len(cands)} кандидатов")
            except Exception as e:
                print(f"[CHIMERA] Хоккей ошибка: {e}")
            return cands

        def _scan_basketball(bball_data):
            cands = []
            try:
                from sports.basketball import calculate_basketball_win_prob
                from sports.basketball.core import get_basketball_odds
                total = 0
                for bkey, bname, bmatches in bball_data:
                    for bm in bmatches:
                        try:
                            bh = bm.get("home_team", "")
                            ba = bm.get("away_team", "")
                            if not bh or not ba:
                                continue
                            bodds = get_basketball_odds(bm)
                            if not bodds.get("home_win"):
                                continue
                            bres = calculate_basketball_win_prob(
                                bh, ba, bodds, bkey,
                                no_vig_home=bodds.get("no_vig_home", 0.0),
                                no_vig_away=bodds.get("no_vig_away", 0.0),
                            )
                            hp = bres.get("home_prob", 0)
                            ap = bres.get("away_prob", 0)
                            if not hp:
                                continue
                            bcands = compute_chimera_score(
                                home_team=bh, away_team=ba,
                                home_prob=hp, away_prob=ap, draw_prob=0,
                                bookmaker_odds={"home_win": bodds.get("home_win", 0),
                                               "away_win": bodds.get("away_win", 0), "draw": 0},
                                home_form=bres.get("home_form", ""), away_form=bres.get("away_form", ""),
                                elo_home=bres.get("elo_home", 1550), elo_away=bres.get("elo_away", 1550),
                                league=bkey,
                                apply_calibration=False,
                            )
                            bcands = [
                                c for c in bcands
                                if (c.get("odds", 0) <= 2.8)
                                and (c.get("prob", 0) >= 55)
                            ]
                            bct = bm.get("commence_time", "")
                            for bc in bcands:
                                bc["sport"]       = "basketball"
                                bc["league_name"] = bname
                                bc["commence_time"] = bct
                            cands.extend(bcands)
                            total += len(bcands)
                        except Exception as bce:
                            print(f"[CHIMERA BBALL] Ошибка {bm.get('home_team','')} vs {bm.get('away_team','')}: {bce}")
                print(f"[CHIMERA] Баскетбол: {total} кандидатов")
            except Exception as e:
                print(f"[CHIMERA] Баскетбол ошибка: {e}")
            return cands

        from sports.basketball.core import BASKETBALL_LEAGUES as _BBALL_LEAGUES
        all_league_keys = [lk for lk, _ in FOOTBALL_LEAGUES] + [bk for bk, _ in _BBALL_LEAGUES]

        football_matches = []
        bball_raw = {bk: [] for bk, _ in _BBALL_LEAGUES}

        with _cf.ThreadPoolExecutor(max_workers=12) as pool:
            fball_futures = {pool.submit(_fetch_league, lk): lk for lk, _ in FOOTBALL_LEAGUES}
            bball_futures = {pool.submit(_fetch_bball_league, bk): bk for bk, _ in _BBALL_LEAGUES}

            for fut in _cf.as_completed(fball_futures):
                lkey, matches = fut.result()
                if lkey == "quota":
                    _scan_errors.append("quota")
                else:
                    football_matches.extend(matches)

            for fut in _cf.as_completed(bball_futures):
                bkey, matches = fut.result()
                bball_raw[bkey] = matches

        print(f"[CHIMERA] Всего матчей для скана: {len(football_matches)}")
        bball_data = [(bk, bn, bball_raw.get(bk, [])) for bk, bn in _BBALL_LEAGUES]

        with _cf.ThreadPoolExecutor(max_workers=5) as pool:
            f_football   = pool.submit(_scan_football, football_matches)
            f_cs2        = pool.submit(_scan_cs2)
            f_tennis     = pool.submit(_scan_tennis)
            f_basketball = pool.submit(_scan_basketball, bball_data)
            f_hockey     = pool.submit(_scan_hockey)

            _sport_names = ["football", "cs2", "tennis", "basketball", "hockey"]
            candidates = []
            for _sname, fut in zip(_sport_names, [f_football, f_cs2, f_tennis, f_basketball, f_hockey]):
                try:
                    candidates.extend(fut.result(timeout=120))
                except Exception as e:
                    import traceback
                    print(f"[CHIMERA] Скан ошибка [{_sname}]: {type(e).__name__}: {e}")
                    traceback.print_exc()

        return candidates

    import functools
    loop = asyncio.get_running_loop()
    all_candidates = await loop.run_in_executor(None, _run_math_scan)

    # Pre-AI порог специально ниже MIN_CHIMERA_SCORE:
    # скан использует только ELO (без ensemble/xG/H2H), поэтому базовый score ~38-48.
    # AI верификация потом добавляет +25 к подтверждённым → итоговый score 60-70+.
    _MIN_CS_FOOTBALL = 36
    _MIN_CS_OTHER    = 32

    def _is_live_match(ct_str: str) -> bool:
        """Матч уже начался (< 3ч назад) — EV ненадёжен."""
        if not ct_str:
            return False
        try:
            from datetime import datetime as _dt2, timezone as _tz2
            _now_live = _dt2.now(_tz2.utc)
            _ct = ct_str.replace("Z", "+00:00")
            _diff = (_now_live - _dt2.fromisoformat(_ct)).total_seconds()
            return 0 < _diff < 10800
        except Exception:
            return False

    all_candidates = [
        c for c in all_candidates
        if c.get("ev", 0) > 2
        and c.get("odds", 0) >= 1.40
        and c.get("ev", 0) <= 80
        and c.get("chimera_score", 0) >= (
            _MIN_CS_FOOTBALL if c.get("sport") == "football" else _MIN_CS_OTHER
        )
        and not _is_live_match(c.get("commence_time", ""))
    ]
    all_candidates.sort(key=lambda x: x["chimera_score"], reverse=True)
    top_candidates = all_candidates[:3]
    print(f"[CHIMERA] Кандидатов найдено: {len(all_candidates)}, топ-3 scores: {[round(c['chimera_score'],1) for c in top_candidates]}")

    if not top_candidates:
        _signals_scan_in_progress = False
        if "quota" in _scan_errors:
            await status_msg.edit_text(
                "⚠️ <b>CHIMERA SIGNAL</b>\n\n"
                "Футбольные матчи временно недоступны.\n\n"
                "<i>Попробуй позже или воспользуйся разделами CS2 и Теннис.</i>",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(
                "📊 <b>CHIMERA SIGNAL</b>\n\nСегодня матчей с ценностью не найдено.\nПопробуйте позже.",
                parse_mode="HTML"
            )
        return

    await status_msg.edit_text(
        "🔍 <b>CHIMERA SIGNAL</b>\n\n"
        "✅ Шаг 1/3: Матчи загружены\n"
        f"📰 Шаг 2/3: Собираю новости и запускаю AI для топ-{len(top_candidates)}...\n"
        "<i>⏳ Ещё 20–50 секунд...</i>",
        parse_mode="HTML"
    )

    def _fetch_news_for_candidates():
        import concurrent.futures as _cf_news
        from oracle_ai import oracle_analyze
        def _get_news(c):
            try:
                res = oracle_analyze(c.get("home", ""), c.get("away", ""))
                summaries = []
                for team, data in res.items():
                    headlines = [a.get("title", "") for a in data.get("articles", [])[:2]]
                    if headlines:
                        summaries.append(f"{team}: {'; '.join(headlines)}")
                c["news_context"] = " | ".join(summaries)[:400] if summaries else ""
            except Exception:
                c["news_context"] = ""
        with _cf_news.ThreadPoolExecutor(max_workers=3) as _pool:
            list(_pool.map(_get_news, top_candidates))

    try:
        await loop.run_in_executor(None, _fetch_news_for_candidates)
    except Exception as _ne:
        print(f"[CHIMERA News] Ошибка: {_ne}")

    try:
        top_candidates = await loop.run_in_executor(
            None,
            functools.partial(
                run_ai_verification,
                top_candidates,
                gpt_client=_gpt_client,
                groq_client=_groq_client,
            )
        )
    except Exception as e:
        print(f"[CHIMERA AI] Ошибка верификации: {e}")

    _chimera_top_pred_id = None
    _chimera_top_sport   = "football"
    _chimera_top_odds    = 0
    for _ci, _cand in enumerate(top_candidates):
        try:
            _c_sport = _cand.get("sport", "football")
            _c_home  = _cand.get("home", "")
            _c_away  = _cand.get("away", "")
            _c_team  = _cand.get("team", "")
            _c_odds  = _cand.get("odds", 0)
            _c_time  = _cand.get("commence_time", "")
            _c_rec   = "home_win" if _c_team == _c_home else "away_win"
            _c_odds_h = _c_odds if _c_rec == "home_win" else 0
            _c_odds_a = _c_odds if _c_rec == "away_win" else 0
            _mid = f"chimera_{_c_home}_{_c_away}_{_c_time[:10]}"
            _saved_id = save_prediction(
                sport=_c_sport,
                match_id=_mid,
                match_date=_c_time,
                home_team=_c_home,
                away_team=_c_away,
                league=_cand.get("league_name", _c_sport),
                recommended_outcome=_c_rec,
                bet_signal="СТАВИТЬ",
                bookmaker_odds_home=_c_odds_h if _c_odds_h > 1 else None,
                bookmaker_odds_away=_c_odds_a if _c_odds_a > 1 else None,
                ensemble_home=round(_cand.get("prob", 50) / 100, 3),
                ensemble_away=round(1 - _cand.get("prob", 50) / 100, 3),
                ensemble_best_outcome=_c_rec,
            )
            if not _saved_id:
                from database import _get_db_connection
                _tbl = {"football": "football_predictions", "cs2": "cs2_predictions",
                        "tennis": "tennis_predictions", "basketball": "basketball_predictions"}.get(_c_sport, "football_predictions")
                with _get_db_connection() as _conn:
                    _row = _conn.execute(f"SELECT id FROM {_tbl} WHERE match_id=?", (_mid,)).fetchone()
                    if _row:
                        _saved_id = _row[0]
            _cand["_pred_id"] = _saved_id
            if _ci == 0:
                _chimera_top_pred_id = _saved_id
                _chimera_top_sport   = _c_sport
                _chimera_top_odds    = _c_odds
        except Exception as _cs_err:
            print(f"[CHIMERA Save] {_cs_err}")

    import time as _time_mod2
    _signals_scan_cache["last"] = {
        "ts":          _time_mod2.time(),
        "candidates":  top_candidates,
        "top_pred_id": _chimera_top_pred_id,
        "top_sport":   _chimera_top_sport,
        "top_odds":    _chimera_top_odds,
    }
    print(f"[CHIMERA] Результаты скана закешированы на {SIGNALS_SCAN_TTL // 60} мин")
    _signals_scan_in_progress = False

    try:
        _broll_new = get_user_bankroll(message.from_user.id) or 0
        result_text = _format_chimera_page(top_candidates, 0, bankroll=_broll_new)
        _chimera_kb = _build_chimera_kb(
            top_candidates, _chimera_top_pred_id, _chimera_top_sport,
            _chimera_top_odds, message.from_user.id
        )
        await status_msg.edit_text(result_text, parse_mode="HTML", reply_markup=_chimera_kb)
    except Exception as _fmt_e:
        logger.error(f"[CHIMERA] Ошибка отправки: {_fmt_e}")
        best = top_candidates[0] if top_candidates else {}
        fallback = (
            f"🎯 <b>CHIMERA SIGNAL</b>\n\n"
            f"<b>{best.get('home','')} vs {best.get('away','')}</b>\n"
            f"📌 {best.get('team','')} ({best.get('outcome','')})\n"
            f"💰 Кэф: <b>{best.get('odds','?')}</b> | "
            f"Вероятность: <b>{best.get('prob','?')}%</b>\n"
            f"📈 Score: <b>{best.get('chimera_score',0):.0f}/100</b>"
        ) if best else "📊 Сигналов нет"
        await status_msg.edit_text(fallback, parse_mode="HTML")


# ── Chimera callbacks ─────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "chimera_noop")
async def cb_chimera_noop(call: types.CallbackQuery):
    await call.answer()


@router.callback_query(lambda c: c.data == "chimera_refresh")
async def cb_chimera_refresh(call: types.CallbackQuery):
    from access import check_access, get_access_denied_text
    _r = await check_access(call.from_user.id, call.bot,
                            require_full=True, count_analysis=False)
    if _r != "ok":
        await call.answer(get_access_denied_text(_r)[:200], show_alert=True)
        return
    _signals_scan_cache.clear()
    await call.answer("Запускаю новый скан...", show_alert=False)
    await cmd_signals(call.message)


@router.callback_query(lambda c: c.data and c.data.startswith("chimera_bet_"))
async def cb_chimera_bet(call: types.CallbackQuery):
    try:
        parts = call.data.split("_")
        idx   = int(parts[2])
        units = int(parts[3]) if len(parts) > 3 else 1
    except (IndexError, ValueError):
        await call.answer("Ошибка формата", show_alert=True)
        return
    cached     = _signals_scan_cache.get("last", {})
    candidates = cached.get("candidates", [])
    if not candidates or idx >= len(candidates):
        await call.answer("Данные устарели — обновите сигналы /signals", show_alert=True)
        return
    c    = candidates[idx]
    sp   = c.get("sport", "football")
    home = c.get("home", "")
    away = c.get("away", "")
    odds = c.get("odds", 0)
    t_str = c.get("commence_time", "")
    rec  = "home_win" if c.get("team") == home else "away_win"
    mid  = f"chimera_{home}_{away}_{t_str[:10]}"
    pred_id = c.get("_pred_id")
    if not pred_id:
        try:
            pred_id = save_prediction(
                sport=sp, match_id=mid, match_date=t_str,
                home_team=home, away_team=away,
                league=c.get("league_name", sp),
                recommended_outcome=rec, bet_signal="СТАВИТЬ",
                bookmaker_odds_home=odds if rec == "home_win" else None,
                bookmaker_odds_away=odds if rec == "away_win" else None,
                ensemble_home=round(c.get("prob", 50) / 100, 3),
                ensemble_away=round(1 - c.get("prob", 50) / 100, 3),
                ensemble_best_outcome=rec,
            )
            if not pred_id:
                from database import _get_db_connection
                _tbl = {"football": "football_predictions", "cs2": "cs2_predictions",
                        "tennis": "tennis_predictions", "basketball": "basketball_predictions",
                        "hockey": "hockey_predictions"}.get(sp, "football_predictions")
                with _get_db_connection() as _conn:
                    _row = _conn.execute(f"SELECT id FROM {_tbl} WHERE match_id=?", (mid,)).fetchone()
                    if _row:
                        pred_id = _row[0]
            c["_pred_id"] = pred_id
        except Exception as _e:
            try:
                from database import _get_db_connection
                _tbl = {"football": "football_predictions", "cs2": "cs2_predictions",
                        "tennis": "tennis_predictions", "basketball": "basketball_predictions",
                        "hockey": "hockey_predictions"}.get(sp, "football_predictions")
                with _get_db_connection() as _conn:
                    _row = _conn.execute(f"SELECT id FROM {_tbl} WHERE match_id=?", (mid,)).fetchone()
                    if _row:
                        pred_id = _row[0]
                        c["_pred_id"] = pred_id
            except Exception:
                pass
            if not pred_id:
                logger.error(f"[chimera_bet] Ошибка сохранения: {_e}")
    if not pred_id:
        await call.answer("Не удалось записать — попробуйте ещё раз", show_alert=True)
        return
    saved = mark_user_bet(call.from_user.id, sp, pred_id, odds, units)
    if saved:
        await call.answer("✅ Записано! Результат добавится автоматически после матча.", show_alert=True)
        try:
            kb = _build_chimera_carousel_kb(candidates, idx, call.from_user.id)
            new_rows = [kb.inline_keyboard[0], [types.InlineKeyboardButton(
                text="📝 Ставка уже записана", callback_data="noop"
            )]]
            await call.message.edit_reply_markup(
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=new_rows)
            )
        except Exception as _e:
            logger.debug(f"[ignore] {_e}")
    else:
        await call.answer("Ты уже записал эту ставку.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("chimera_page_"))
async def cb_chimera_page(call: types.CallbackQuery):
    try:
        idx = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer()
        return
    cached     = _signals_scan_cache.get("last", {})
    candidates = cached.get("candidates", [])
    if not candidates or idx >= len(candidates):
        await call.answer("Данные устарели — нажмите /signals снова", show_alert=True)
        return
    _broll = get_user_bankroll(call.from_user.id) or 0
    text   = _format_chimera_page(candidates, idx, bankroll=_broll)
    kb     = _build_chimera_carousel_kb(candidates, idx, call.from_user.id)
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as _e:
        logger.debug(f"[ignore] {_e}")
    await call.answer()
