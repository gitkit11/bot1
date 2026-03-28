# -*- coding: utf-8 -*-
"""
football_data.py — get_matches() и get_bookmaker_odds().
Вынесено из main.py для использования в handlers/football.py без циркулярных импортов.
"""
import logging
import time

import state
from keyboards import FOOTBALL_LEAGUES

logger = logging.getLogger(__name__)


def get_matches(league: str = None, force: bool = False):
    """Получает список ближайших матчей через The Odds API для выбранной лиги (кеш 20 мин)."""
    if league:
        state._current_league = league
    league_key = state._current_league

    # Проверяем кеш по лиге (если force=False и кеш свежий)
    if not force:
        cached_entry = state._league_matches_cache.get(league_key)
        if cached_entry and (time.time() - cached_entry["ts"]) < state._LEAGUE_CACHE_TTL:
            state.matches_cache[:] = cached_entry["matches"]
            return cached_entry["matches"]

    # force=True или кеш устарел — инвалидируем только эту лигу
    if force:
        try:
            from odds_cache import invalidate as _inv
            _inv(league_key)
        except ImportError:
            pass

    try:
        from odds_cache import get_odds as _get_odds
        from datetime import datetime, timezone, timedelta
        data = _get_odds(league_key, markets="h2h,totals,spreads")
        if data:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=3)).isoformat()[:19]
            future = [m for m in data if m.get('commence_time', '') > cutoff]
            result = future[:20]
            state._league_matches_cache[league_key] = {"matches": result, "ts": time.time()}
            state.matches_cache[:] = result
            state._last_matches_refresh = time.time()
            league_name = dict(FOOTBALL_LEAGUES).get(league_key, league_key)
            print(f"[API] {league_name}: {len(result)} матчей.")
            return result
    except Exception as e:
        print(f"[API Ошибка] {e}")

    # Возвращаем кеш этой лиги если есть, иначе глобальный matches_cache
    cached_entry = state._league_matches_cache.get(league_key)
    if cached_entry:
        return cached_entry["matches"]
    return state.matches_cache


def get_bookmaker_odds(match_data: dict) -> dict:
    """
    Извлекает коэффициенты из данных матча.
    Приоритет: Pinnacle no-vig → шарп-буки → все буки.
    """
    result = {
        "home_win": 0, "draw": 0, "away_win": 0,
        "over_2_5": 0, "under_2_5": 0,
        "over_1_5": 0, "under_1_5": 0,
        "over_3_5": 0, "under_3_5": 0,
        "handicap_home": 0, "handicap_away": 0, "handicap_line": 0,
        "no_vig_home": 0.0, "no_vig_draw": 0.0, "no_vig_away": 0.0,
        "bookmakers_count": 0,
        "pinnacle_home": 0, "pinnacle_draw": 0, "pinnacle_away": 0,
    }

    SHARP_BOOKS = ["pinnacle", "betfair_ex", "betfair", "matchbook",
                   "smarkets", "lowvig", "betsson", "nordicbet", "marathonbet"]

    def _v(v):
        try:
            f = float(v)
            return f if f >= 1.02 else 0.0
        except Exception:
            return 0.0

    try:
        home_team = match_data.get("home_team", "")
        away_team = match_data.get("away_team", "")
        bookmakers = match_data.get("bookmakers", [])
        result["bookmakers_count"] = len(bookmakers)

        sharp_h, sharp_d, sharp_a = [], [], []
        all_h,   all_d,   all_a   = [], [], []

        for bm in bookmakers:
            bm_key = bm.get("key", "").lower()
            is_sharp = any(s in bm_key for s in SHARP_BOOKS)

            for market in bm.get("markets", []):
                if market.get("key") == "h2h":
                    oc = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                    h = _v(oc.get(home_team, 0))
                    a = _v(oc.get(away_team, 0))
                    d = _v(oc.get("Draw", 0))
                    if h and a and d:
                        all_h.append(h); all_d.append(d); all_a.append(a)
                        if is_sharp:
                            sharp_h.append(h); sharp_d.append(d); sharp_a.append(a)
                        if "pinnacle" in bm_key:
                            result["pinnacle_home"] = h
                            result["pinnacle_draw"] = d
                            result["pinnacle_away"] = a

                elif market.get("key") == "totals" and result["over_2_5"] == 0:
                    for o in market.get("outcomes", []):
                        pt    = o.get("point", 0)
                        name  = o.get("name", "")
                        price = _v(o.get("price", 0))
                        if not price:
                            continue
                        if pt == 2.5 and name == "Over"  and not result["over_2_5"]:
                            result["over_2_5"] = price
                        elif pt == 2.5 and name == "Under" and not result["under_2_5"]:
                            result["under_2_5"] = price
                        elif pt == 1.5 and name == "Over"  and not result["over_1_5"]:
                            result["over_1_5"] = price
                        elif pt == 1.5 and name == "Under" and not result["under_1_5"]:
                            result["under_1_5"] = price
                        elif pt == 3.5 and name == "Over"  and not result["over_3_5"]:
                            result["over_3_5"] = price
                        elif pt == 3.5 and name == "Under" and not result["under_3_5"]:
                            result["under_3_5"] = price

                elif market.get("key") == "spreads" and not result["handicap_home"]:
                    for o in market.get("outcomes", []):
                        name  = o.get("name", "")
                        price = _v(o.get("price", 0))
                        line  = o.get("point", 0)
                        if not price:
                            continue
                        if name == home_team:
                            result["handicap_home"] = price
                            result["handicap_line"] = line
                        elif name == away_team:
                            result["handicap_away"] = price

        src_h = sharp_h if sharp_h else all_h
        src_d = sharp_d if sharp_d else all_d
        src_a = sharp_a if sharp_a else all_a

        if src_h:
            src_h.sort(); src_d.sort(); src_a.sort()
            mid = len(src_h) // 2
            result["home_win"] = round(src_h[mid], 3)
            result["draw"]     = round(src_d[mid], 3)
            result["away_win"] = round(src_a[mid], 3)

        nv_h = result["pinnacle_home"] or result["home_win"]
        nv_d = result["pinnacle_draw"] or result["draw"]
        nv_a = result["pinnacle_away"] or result["away_win"]
        if nv_h and nv_d and nv_a:
            imp_h = 1 / nv_h
            imp_d = 1 / nv_d
            imp_a = 1 / nv_a
            total = imp_h + imp_d + imp_a
            if total > 0:
                result["no_vig_home"] = round(imp_h / total, 4)
                result["no_vig_draw"] = round(imp_d / total, 4)
                result["no_vig_away"] = round(imp_a / total, 4)

    except Exception as e:
        print(f"[API Ошибка коэффициентов] {e}")
    return result
