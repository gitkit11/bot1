# -*- coding: utf-8 -*-
"""
Хоккейный движок CHIMERA.
Стратегия:
  - ELO 35% + Odds 35% + Home Ice 15% + Form 15%
  - Тоталы: Over/Under с анализом темпа
  - Учёт Back-to-back (усталость)
"""

import os
import logging
import statistics
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

try:
    from config import THE_ODDS_API_KEY
except ImportError:
    THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")

HOCKEY_LEAGUES = [
    ("icehockey_nhl",                    "🏒 NHL"),
    ("icehockey_sweden_hockey_league",   "🇸🇪 SHL"),
    ("icehockey_ahl",                    "🇺🇸 AHL"),
    ("icehockey_liiga",                  "🇫🇮 Finnish Liiga"),
    ("icehockey_sweden_allsvenskan",     "🇸🇪 Allsvenskan"),
]

# ── ELO рейтинги NHL (сезон 2025-26, обновлено март 2026) ─────────────────────
# Источник: NHL standings + playoff history 2024-25
NHL_ELO = {
    # Восточная конференция
    "Washington Capitals":        1650,   # Стабильный топ Востока
    "Florida Panthers":           1645,   # Чемпионы Кубка Стэнли 2024
    "Toronto Maple Leafs":        1630,
    "Tampa Bay Lightning":        1620,
    "Boston Bruins":              1615,
    "Carolina Hurricanes":        1610,
    "New Jersey Devils":          1600,
    "Ottawa Senators":            1590,
    "New York Rangers":           1580,
    "Detroit Red Wings":          1565,
    "Buffalo Sabres":             1555,
    "New York Islanders":         1545,
    "Pittsburgh Penguins":        1535,
    "Philadelphia Flyers":        1530,
    "Montreal Canadiens":         1520,
    # Западная конференция
    "Winnipeg Jets":              1660,   # Лучший старт в Западной конференции
    "Vegas Golden Knights":       1645,
    "Colorado Avalanche":         1640,
    "Dallas Stars":               1635,
    "Edmonton Oilers":            1625,   # Финалисты Кубка 2024, сильный состав
    "Minnesota Wild":             1615,
    "Los Angeles Kings":          1610,
    "Calgary Flames":             1580,
    "St. Louis Blues":            1570,
    "Nashville Predators":        1560,
    "Vancouver Canucks":          1550,
    "Seattle Kraken":             1540,
    "Utah Hockey Club":           1525,
    "Columbus Blue Jackets":      1515,
    "Anaheim Ducks":              1505,
    "Chicago Blackhawks":         1495,
    "San Jose Sharks":            1475,   # Отстройка команды
}

# ── ELO рейтинги SHL (Швеция) ─────────────────────────────────────────────────
SHL_ELO = {
    "Djurgarden IF":              1650,
    "Frolunda HC":                1640,
    "Farjestad BK":               1625,
    "Leksands IF":                1600,
    "Skelleftea AIK":             1595,
    "Rogle BK":                   1580,
    "Lulea HF":                   1570,
    "MoDo Hockey":                1555,
    "HV71":                       1545,
    "Malmo Redhawks":             1535,
    "Brynas IF":                  1525,
    "Timra IK":                   1515,
    "Linkoping HC":               1505,
    "Orebro HK":                  1490,
}

DEFAULT_ELO        = 1550
HOME_ADVANTAGE_ELO = 40   # домашний лёд важен, но меньше, чем корт в баскетболе
B2B_PENALTY        = 0.04  # -4% за back-to-back

REST_PENALTY = {0: -0.06, 1: -0.04, 2: -0.02}

_form_cache:      dict  = {}
_b2b_cache:       dict  = {}
_rest_days_cache: dict  = {}
_goals_cache:     dict  = {}   # {team: {"gf": float, "ga": float, "gp": int}}
_cache_ts:        float = 0.0
_CACHE_TTL = 3600  # 1 час


# ── ELO утилиты ──────────────────────────────────────────────────────────────

def _get_elo(team: str, league_key: str = "") -> int:
    try:
        import json
        if os.path.exists("elo_hockey.json"):
            with open("elo_hockey.json", "r", encoding="utf-8") as f:
                live = json.load(f)
            if team in live:
                return live[team]
    except Exception:
        pass

    if "sweden" in league_key or "shl" in league_key:
        return SHL_ELO.get(team, DEFAULT_ELO)
    return NHL_ELO.get(team) or SHL_ELO.get(team) or DEFAULT_ELO


def elo_win_prob(home: str, away: str, league_key: str = "") -> tuple:
    h_elo = _get_elo(home, league_key) + HOME_ADVANTAGE_ELO
    a_elo = _get_elo(away, league_key)
    h_prob = 1 / (1 + 10 ** ((a_elo - h_elo) / 400))
    return round(h_prob, 3), round(1 - h_prob, 3)


# ── Форма и back-to-back ──────────────────────────────────────────────────────

def _fetch_recent_scores(league_key: str) -> list:
    if not THE_ODDS_API_KEY:
        return []
    try:
        from odds_cache import get_scores as _get_scores
        all_scores = _get_scores(league_key, days_from=7)
        return [m for m in all_scores if m.get("completed")]
    except ImportError:
        pass
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{league_key}/scores/",
            params={"apiKey": THE_ODDS_API_KEY, "daysFrom": 7},
            timeout=10,
        )
        if r.ok:
            return [m for m in r.json() if m.get("completed")]
    except Exception as e:
        logger.warning(f"[Hockey] scores fetch error: {e}")
    return []


def _build_form_and_b2b(league_key: str):
    global _form_cache, _b2b_cache, _rest_days_cache, _goals_cache, _cache_ts
    import time
    if time.time() - _cache_ts < _CACHE_TTL:
        return

    scores = _fetch_recent_scores(league_key)
    now = datetime.now(timezone.utc)
    team_results: dict = {}
    team_goals:   dict = {}   # {team: {"gf": [], "ga": []}}

    for m in scores:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        raw_scores = m.get("scores") or []
        score_map  = {s["name"]: int(s["score"]) for s in raw_scores if s.get("name") and s.get("score")}
        h_score = score_map.get(home, 0)
        a_score = score_map.get(away, 0)
        if h_score == 0 and a_score == 0:
            continue
        ct = m.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        except Exception:
            dt = now - timedelta(days=3)

        # Goals tracking
        team_goals.setdefault(home, {"gf": [], "ga": []})
        team_goals.setdefault(away, {"gf": [], "ga": []})
        team_goals[home]["gf"].append(h_score)
        team_goals[home]["ga"].append(a_score)
        team_goals[away]["gf"].append(a_score)
        team_goals[away]["ga"].append(h_score)

        if h_score == a_score:
            continue
        h_won = h_score > a_score
        team_results.setdefault(home, []).append((dt, h_won))
        team_results.setdefault(away, []).append((dt, not h_won))

    for team, results in team_results.items():
        results.sort(key=lambda x: x[0], reverse=True)
        form_str = "".join("W" if w else "L" for _, w in results[:5])
        _form_cache[team] = form_str
        if results:
            last_dt   = results[0][0]
            hours_ago = (now - last_dt).total_seconds() / 3600
            days_rest = int(hours_ago / 24)
            _b2b_cache[team] = hours_ago < 36
            _rest_days_cache[team] = days_rest

    for team, g in team_goals.items():
        gp = len(g["gf"])
        if gp > 0:
            _goals_cache[team] = {
                "gf": round(sum(g["gf"]) / gp, 2),
                "ga": round(sum(g["ga"]) / gp, 2),
                "gp": gp,
            }

    _cache_ts = __import__("time").time()


def get_team_form(team: str, league_key: str = "") -> str:
    _build_form_and_b2b(league_key)
    return _form_cache.get(team, "")


def is_back_to_back(team: str, league_key: str = "") -> bool:
    _build_form_and_b2b(league_key)
    return _b2b_cache.get(team, False)


def get_rest_days(team: str, league_key: str = "") -> int:
    _build_form_and_b2b(league_key)
    return _rest_days_cache.get(team, 99)


def get_team_goals_stats(team: str, league_key: str = "") -> dict:
    """Возвращает {'gf': float, 'ga': float, 'gp': int} из недавних матчей."""
    _build_form_and_b2b(league_key)
    return _goals_cache.get(team, {})


def _fatigue_penalty(team: str, league_key: str = "") -> float:
    days = get_rest_days(team, league_key)
    return REST_PENALTY.get(days, 0.0)


# ── Загрузка матчей ───────────────────────────────────────────────────────────

def get_hockey_matches(league_key: str) -> list:
    if not THE_ODDS_API_KEY:
        return []
    try:
        from odds_cache import get_odds as _get_odds
        raw = _get_odds(league_key, markets="h2h,totals")
    except ImportError:
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/",
                params={"apiKey": THE_ODDS_API_KEY, "regions": "eu,uk,us,au",
                        "markets": "h2h,totals", "oddsFormat": "decimal"},
                timeout=12,
            )
            raw = r.json() if r.ok else []
        except Exception as e:
            logger.error(f"[Hockey] Ошибка {league_key}: {e}")
            return []

    if not raw:
        return []
    now    = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=2)).isoformat()[:19]
    matches = [m for m in raw if m.get("commence_time", "") > cutoff]
    logger.info(f"[Hockey] {league_key}: {len(matches)} матчей")
    return matches[:25]


# ── Извлечение коэффициентов ─────────────────────────────────────────────────

SHARP_BOOKS_HOCKEY = {"pinnacle", "betfair_ex", "betfair", "matchbook",
                      "smarkets", "lowvig", "betsson", "nordicbet"}


def get_hockey_odds(match: dict) -> dict:
    home_team = match.get("home_team", "")
    away_team = match.get("away_team", "")

    result = {
        "home_win": 0.0, "away_win": 0.0,
        "over": 0.0, "under": 0.0, "total_line": 0.0,
        "bookmaker": "",
        "no_vig_home": 0.0, "no_vig_away": 0.0,
        "pinnacle_home": 0.0, "pinnacle_away": 0.0,
        "bookmakers_count": 0,
        "spread_home": -1.5, "spread_away": 1.5,
        "spread_home_odds": 0.0, "spread_away_odds": 0.0,
    }

    all_home_odds:   list = []
    all_away_odds:   list = []
    sharp_home_odds: list = []
    sharp_away_odds: list = []
    spread_home_odds_list: list = []
    spread_away_odds_list: list = []
    spread_home_pt  = -1.5
    spread_away_pt  = +1.5
    pinnacle_home = 0.0
    pinnacle_away = 0.0
    total_found   = False
    spread_found  = False

    bookmakers = match.get("bookmakers", [])
    result["bookmakers_count"] = len(bookmakers)

    for bm in bookmakers:
        bm_key  = bm.get("key", "").lower()
        is_sharp = any(s in bm_key for s in SHARP_BOOKS_HOCKEY)

        for market in bm.get("markets", []):
            key = market.get("key", "")

            if key == "h2h":
                for out in market.get("outcomes", []):
                    name = out.get("name", "")
                    price = float(out.get("price", 0))
                    if price < 1.01:
                        continue
                    if name == home_team:
                        all_home_odds.append(price)
                        if is_sharp:
                            sharp_home_odds.append(price)
                        if "pinnacle" in bm_key:
                            pinnacle_home = price
                    elif name == away_team:
                        all_away_odds.append(price)
                        if is_sharp:
                            sharp_away_odds.append(price)
                        if "pinnacle" in bm_key:
                            pinnacle_away = price

            elif key == "totals" and not total_found:
                for out in market.get("outcomes", []):
                    nm = out.get("name", "")
                    pt = float(out.get("point", 5.5))
                    pr = float(out.get("price", 0))
                    if nm == "Over":
                        result["over"] = pr
                        result["total_line"] = pt
                    elif nm == "Under":
                        result["under"] = pr
                total_found = True

            elif key == "spreads" and not spread_found:
                for out in market.get("outcomes", []):
                    nm = out.get("name", "")
                    pt = float(out.get("point", -1.5))
                    pr = float(out.get("price", 0))
                    if pr < 1.01:
                        continue
                    if nm == home_team:
                        spread_home_pt = pt
                        spread_home_odds_list.append(pr)
                    elif nm == away_team:
                        spread_away_pt = pt
                        spread_away_odds_list.append(pr)
                spread_found = True

    def _best_odds(sharp, all_bm):
        if sharp:
            return statistics.median(sharp)
        if all_bm:
            return statistics.median(all_bm)
        return 0.0

    h_odds = _best_odds(sharp_home_odds, all_home_odds)
    a_odds = _best_odds(sharp_away_odds, all_away_odds)

    result["home_win"] = round(h_odds, 3)
    result["away_win"] = round(a_odds, 3)
    result["spread_home"]      = spread_home_pt
    result["spread_away"]      = spread_away_pt
    result["spread_home_odds"] = round(statistics.median(spread_home_odds_list), 3) if spread_home_odds_list else 0.0
    result["spread_away_odds"] = round(statistics.median(spread_away_odds_list), 3) if spread_away_odds_list else 0.0

    if all_home_odds:
        result["bookmaker"] = "median"
    if pinnacle_home > 1.01 and pinnacle_away > 1.01:
        result["pinnacle_home"] = pinnacle_home
        result["pinnacle_away"] = pinnacle_away
        margin  = 1 / pinnacle_home + 1 / pinnacle_away
        result["no_vig_home"] = round((1 / pinnacle_home) / margin, 4)
        result["no_vig_away"] = round((1 / pinnacle_away) / margin, 4)
    elif h_odds > 1.01 and a_odds > 1.01:
        margin = 1 / h_odds + 1 / a_odds
        result["no_vig_home"] = round((1 / h_odds) / margin, 4)
        result["no_vig_away"] = round((1 / a_odds) / margin, 4)

    return result


# ── Расчёт вероятностей ───────────────────────────────────────────────────────

def calculate_hockey_win_prob(
    home: str, away: str, odds: dict, league_key: str = "",
    no_vig_home: float = 0.0, no_vig_away: float = 0.0,
) -> dict:
    """
    Ансамбль: ELO 35% + No-Vig Odds 35% + Home Ice 15% + Form 15%.
    Возвращает словарь с home_prob, away_prob, EV, bet_signal и доп. данными.
    """
    # ELO вероятности
    elo_h, elo_a = elo_win_prob(home, away, league_key)

    # No-Vig вероятности из букмекеров
    nv_h = no_vig_home or odds.get("no_vig_home", 0.0)
    nv_a = no_vig_away or odds.get("no_vig_away", 0.0)
    if nv_h < 0.01 or nv_a < 0.01:
        nv_h, nv_a = elo_h, elo_a

    # Форма
    home_form = get_team_form(home, league_key)
    away_form = get_team_form(away, league_key)

    def _form_score(form_str: str) -> float:
        weights = [1.0, 0.7, 0.5, 0.35, 0.25]
        total = sum(weights[:len(form_str)])
        score = sum(w for w, c in zip(weights, form_str) if c == "W")
        return score / total if total > 0 else 0.5

    form_h = _form_score(home_form)
    form_a = _form_score(away_form)

    # Читаем веса из HOCKEY_CFG (MetaLearner обновляет их после накопления данных)
    # W_HOME=0 — домашнее преимущество уже учтено в ELO (+40) и рыночных коэффициентах
    try:
        from signal_engine import HOCKEY_CFG
        W_ELO  = HOCKEY_CFG.get("weight_elo",  0.35)
        W_ODDS = HOCKEY_CFG.get("weight_odds", 0.50)
        W_FORM = HOCKEY_CFG.get("weight_form", 0.15)
    except Exception:
        W_ELO, W_ODDS, W_FORM = 0.35, 0.50, 0.15

    # Нормализуем форму чтобы сумма = 1 (иначе форма влияет на масштаб, а не на соотношение)
    form_total = form_h + form_a
    if form_total > 0:
        norm_form_h = form_h / form_total
        norm_form_a = form_a / form_total
    else:
        norm_form_h = norm_form_a = 0.5

    # Голы за последние игры (Голы/Игра) — дополнительный фактор атаки/защиты
    h_goals = get_team_goals_stats(home, league_key)
    a_goals = get_team_goals_stats(away, league_key)
    goals_factor_h = goals_factor_a = 0.0
    if h_goals.get("gp", 0) >= 3 and a_goals.get("gp", 0) >= 3:
        # Комбинированная сила = ((GF - GA) / среднее) — центрируем относительно друг друга
        h_net = h_goals.get("gf", 3.0) - h_goals.get("ga", 3.0)
        a_net = a_goals.get("gf", 3.0) - a_goals.get("ga", 3.0)
        net_range = max(abs(h_net - a_net), 0.1)
        goals_factor_h = max(-0.06, min(0.06, (h_net - a_net) / net_range * 0.06))
        goals_factor_a = -goals_factor_h

    raw_h = W_ELO * elo_h + W_ODDS * nv_h + W_FORM * norm_form_h
    raw_a = W_ELO * elo_a + W_ODDS * nv_a + W_FORM * norm_form_a
    total = raw_h + raw_a
    h_prob = round(raw_h / total, 4) if total > 0 else 0.5
    a_prob = round(1 - h_prob, 4)

    # Голевой фактор (малый корректировочный вес)
    h_prob = max(0.05, min(0.95, h_prob + goals_factor_h))
    a_prob = round(1 - h_prob, 4)

    # Штраф за усталость (применяем обоим независимо, затем ренормализуем)
    h_fatigue = _fatigue_penalty(home, league_key)
    a_fatigue = _fatigue_penalty(away, league_key)
    h_prob = max(0.05, min(0.95, h_prob + h_fatigue))
    a_prob = max(0.05, min(0.95, a_prob + a_fatigue))
    # ВАЖНО: ренормализация после независимых штрафов чтобы h+a = 1.0
    _ft = h_prob + a_prob
    if _ft > 0:
        h_prob = round(h_prob / _ft, 4)
        a_prob = round(1 - h_prob, 4)

    # Штраф за травмы (NHL через ESPN API, -2.5% за игрока, макс -10%)
    h_inj = a_inj = None
    if "nhl" in league_key.lower() or league_key in ("icehockey_nhl", ""):
        try:
            from injuries import get_nhl_injuries as _get_nhl_inj
            h_inj = _get_nhl_inj(home)
            a_inj = _get_nhl_inj(away)
            h_missing = h_inj.get("total_missing", 0)
            a_missing = a_inj.get("total_missing", 0)
            h_inj_pen = min(0.10, h_missing * 0.025)
            a_inj_pen = min(0.10, a_missing * 0.025)
            h_prob = max(0.05, min(0.95, h_prob + a_inj_pen - h_inj_pen))
            a_prob = round(1 - h_prob, 4)
        except Exception:
            pass

    # EV
    h_odds_val = odds.get("home_win", 0.0)
    a_odds_val = odds.get("away_win", 0.0)
    h_ev = round(h_prob * h_odds_val - 1, 4) if h_odds_val > 1.01 else 0.0
    a_ev = round(a_prob * a_odds_val - 1, 4) if a_odds_val > 1.01 else 0.0

    # Сигнал — если хотя бы один кеф отсутствует → сигнал недостоверен
    both_odds_present = h_odds_val > 1.01 and a_odds_val > 1.01
    best_prob = max(h_prob, a_prob)
    best_pick = home if h_prob >= a_prob else away
    best_ev   = h_ev if h_prob >= a_prob else a_ev
    best_odds = h_odds_val if h_prob >= a_prob else a_odds_val

    # Проверяем наличие реальных ELO данных (если обе команды = DEFAULT_ELO → нет данных)
    _h_elo_val = _get_elo(home, league_key)
    _a_elo_val = _get_elo(away, league_key)
    _no_elo_data = (_h_elo_val == DEFAULT_ELO and _a_elo_val == DEFAULT_ELO)

    try:
        from signal_engine import get_bet_tier as _get_tier, HOCKEY_CFG as _HCFG
        _min_hk_odds = _HCFG.get("min_odds", 1.55)
        _max_hk_odds = _HCFG.get("max_odds", 2.4)
        if not both_odds_present or best_odds < _min_hk_odds or best_odds > _max_hk_odds:
            bet_signal = "НЕ СТАВИТЬ"
        else:
            bet_signal = _get_tier(best_prob, best_ev * 100, "hockey")
    except Exception:
        bet_signal = "СТАВИТЬ 🔥" if (best_ev > 0.08 and best_prob >= 0.52 and both_odds_present) else "НЕ СТАВИТЬ"

    # Блокируем ставки для команд без реального ELO (AHL / неизвестные лиги)
    if _no_elo_data and best_odds > 2.3:
        bet_signal = "НЕ СТАВИТЬ"

    # Market divergence фильтр: если наша модель расходится с рынком > 12pp → блок
    # Sharps (Pinnacle) видят больше — не стоит ставить против них при большом разрыве
    if bet_signal != "НЕ СТАВИТЬ" and nv_h > 0.01 and nv_a > 0.01:
        nv_best = nv_h if best_pick == home else nv_a
        _divergence = abs(best_prob - nv_best)
        if _divergence > 0.12:
            bet_signal = "НЕ СТАВИТЬ"
            no_bet_reason = (
                f"⚠️ Дивергенция {_divergence*100:.0f}pp — модель расходится с рынком "
                f"(наша {round(best_prob*100)}% vs бук {round(nv_best*100)}%)"
            )

    # Андердог-ценность для хоккея
    underdog_value = None
    if both_odds_present and best_ev < 0:
        und_pick = away if best_pick == home else home
        und_prob = a_prob if best_pick == home else h_prob
        und_odds = (odds.get("away_win", 0) if best_pick == home else odds.get("home_win", 0))
        und_ev   = round((und_prob * und_odds - 1) * 100, 1) if und_odds > 1.02 else 0
        if und_ev > 20 and und_odds >= 2.5 and und_prob >= 0.15:
            underdog_value = {
                "team": und_pick,
                "odds": und_odds,
                "prob": round(und_prob * 100),
                "ev":   und_ev,
            }

    # Причина НЕ СТАВИТЬ
    no_bet_reason = ""
    if bet_signal == "НЕ СТАВИТЬ":
        if _no_elo_data and best_odds > 2.3:
            no_bet_reason = "⚠️ Нет ELO данных для этих команд — прогноз ненадёжен при высоком кэфе"
        elif not both_odds_present:
            no_bet_reason = "⚠️ Коэффициенты не найдены у букмекера"
        elif best_ev < 0:
            bk_implied = round(100 / best_odds) if best_odds > 1 else 0
            no_bet_reason = (
                f"📉 Букмекер переоценивает фаворита: "
                f"бук {bk_implied}% vs наша модель {round(best_prob*100)}% → EV {best_ev*100:+.1f}%"
            )
        else:
            no_bet_reason = f"📊 EV {best_ev*100:+.1f}% или вероятность {round(best_prob*100)}% ниже порога"

    return {
        "home_prob":     h_prob,
        "away_prob":     a_prob,
        "h_ev":          h_ev,
        "a_ev":          a_ev,
        "bet_signal":      bet_signal,
        "no_bet_reason":   no_bet_reason,
        "underdog_value":  underdog_value,
        "elo_home":    _h_elo_val,
        "elo_away":    _a_elo_val,
        "elo_gap":     abs(_h_elo_val - _a_elo_val),
        "no_elo_data": _no_elo_data,
        "home_form":   home_form,
        "away_form":   away_form,
        "home_b2b":    is_back_to_back(home, league_key),
        "away_b2b":    is_back_to_back(away, league_key),
        "total_analysis": _analyze_total(odds),
        "home_injuries": h_inj or {},
        "away_injuries": a_inj or {},
        "home_goals":  h_goals,
        "away_goals":  a_goals,
    }


def _analyze_total(odds: dict) -> dict:
    """Анализ тотала шайб."""
    line    = odds.get("total_line", 0.0)
    over_o  = odds.get("over", 0.0)
    under_o = odds.get("under", 0.0)
    if not line or not over_o or not under_o:
        return {}
    margin  = 1 / over_o + 1 / under_o
    nv_over = (1 / over_o) / margin
    # В NHL средний тотал 6.0 голов. ~25% игр идут в ОТ/буллиты (+1 гол).
    # Линия < 5.5 → склонность к OVER (матчи обычно результативнее)
    # Линия > 6.5 → склонность к UNDER (стены)
    lean = "Over" if line < 5.5 else ("Under" if line > 6.5 else "—")
    return {
        "line":       line,
        "over_odds":  over_o,
        "under_odds": under_o,
        "nv_over":    round(nv_over, 3),
        "lean":       lean,
        "ot_note":    "~25% игр NHL завершаются в ОТ/буллиты (+1 шайба)" if 5.0 <= line <= 6.5 else "",
    }


# ── Дополнительные рынки: пак-лайн и тотал ───────────────────────────────────

def analyze_puckline(home: str, away: str, h_prob: float, a_prob: float, odds: dict) -> dict:
    """
    Анализ пак-лайна (-1.5 / +1.5).
    P(фав закрывает -1.5) ≈ P(фав побеждает) × 0.62
    Исторически в NHL: когда команда побеждает, она побеждает с разрывом 2+ шайбы в ~62% случаев.
    """
    h_spr_odds = odds.get("spread_home_odds", 0.0)
    a_spr_odds = odds.get("spread_away_odds", 0.0)
    h_spread   = odds.get("spread_home", -1.5)
    a_spread   = odds.get("spread_away", +1.5)

    if not h_spr_odds or not a_spr_odds:
        return {}

    COVER_RATE = 0.62  # % побед, когда команда закрывает -1.5 (NHL историческое)

    h_cover = round(h_prob * COVER_RATE, 4)
    a_cover = round(1 - h_cover, 4)

    h_ev = round(h_cover * h_spr_odds - 1, 4) if h_spr_odds > 1.01 else 0.0
    a_ev = round(a_cover * a_spr_odds - 1, 4) if a_spr_odds > 1.01 else 0.0

    return {
        "home_cover_prob": h_cover,
        "away_cover_prob": a_cover,
        "home_spread":     h_spread,
        "away_spread":     a_spread,
        "home_spread_odds": h_spr_odds,
        "away_spread_odds": a_spr_odds,
        "home_ev":         h_ev,
        "away_ev":         a_ev,
    }


def analyze_hockey_total_deep(h_prob: float, a_prob: float, odds: dict) -> dict:
    """Детальный EV-анализ тотала шайб."""
    total_data = _analyze_total(odds)
    if not total_data:
        return {}

    over_o  = total_data["over_odds"]
    under_o = total_data["under_odds"]
    line    = total_data["line"]

    if over_o < 1.01 or under_o < 1.01:
        return {}

    margin   = 1 / over_o + 1 / under_o
    nv_over  = round((1 / over_o) / margin, 4)
    nv_under = round(1 - nv_over, 4)

    # Небольшая корректировка: чем равнее матч, тем чуть выше вероятность овертайма → тотал меньше
    balance = 1 - abs(h_prob - a_prob)  # 1 = матч равный
    over_adj  = max(0.35, min(0.65, nv_over  - (balance - 0.5) * 0.02))
    under_adj = round(1 - over_adj, 4)

    over_ev  = round(over_adj  * over_o  - 1, 4)
    under_ev = round(under_adj * under_o - 1, 4)

    return {
        "line":       line,
        "over_odds":  over_o,
        "under_odds": under_o,
        "nv_over":    nv_over,
        "nv_under":   nv_under,
        "over_prob":  round(over_adj, 4),
        "under_prob": round(under_adj, 4),
        "over_ev":    over_ev,
        "under_ev":   under_ev,
        "lean":       total_data.get("lean", "—"),
    }


def format_hockey_total_report(
    home_team: str, away_team: str,
    total: dict, match_time: str, league_name: str,
) -> str:
    if not total:
        return (
            f"<b>🏒 {home_team} vs {away_team}</b>\n\n"
            f"⚠️ Данные о тотале не найдены (букмекеры не предоставляют линию)."
        )

    try:
        from datetime import datetime as _dt, timedelta as _td
        dt     = _dt.fromisoformat(match_time.replace("Z", "+00:00"))
        dt_msk = dt + _td(hours=3)
        time_label = dt_msk.strftime("%d.%m %H:%M МСК")
    except Exception:
        time_label = match_time[:16]

    line      = total["line"]
    over_o    = total["over_odds"]
    under_o   = total["under_odds"]
    over_p    = total["over_prob"]
    under_p   = total["under_prob"]
    over_ev   = total["over_ev"]
    under_ev  = total["under_ev"]
    nv_over   = total["nv_over"]
    nv_under  = total["nv_under"]
    lean      = total.get("lean", "—")

    if over_ev > 0.04 and over_ev >= under_ev:
        rec   = f"Больше {line} ⬆️ @ {over_o}"
        rec_ev = over_ev
        icon  = "✅"
    elif under_ev > 0.04:
        rec   = f"Меньше {line} ⬇️ @ {under_o}"
        rec_ev = under_ev
        icon  = "✅"
    else:
        rec   = "Нет ценной ставки"
        rec_ev = 0.0
        icon  = "❌"

    lines = [
        f"🏒 <b>{home_team} vs {away_team}</b>",
        f"📅 {league_name} | {time_label}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🏒 <b>ТОТАЛ ШАЙБ</b>",
        "",
        f"📊 Линия: <b>{line}</b>",
        f"⬆️ Больше {line}: кэф <b>{over_o}</b>  (no-vig {round(nv_over*100,1)}%)",
        f"⬇️ Меньше {line}: кэф <b>{under_o}</b>  (no-vig {round(nv_under*100,1)}%)",
        "",
        f"🧮 Расчёт: Over {round(over_p*100,1)}% | EV {over_ev*100:+.1f}%",
        f"🧮 Расчёт: Under {round(under_p*100,1)}% | EV {under_ev*100:+.1f}%",
    ]
    if lean != "—":
        lines.append(f"📐 Склонность: <b>{lean}</b>  (NHL avg ≈ 6.0 шайб)")
    ot_note = total.get("ot_note", "")
    if ot_note:
        lines.append(f"⏱ <i>{ot_note}</i>")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icon} {rec}",
    ]
    if rec_ev > 0:
        lines.append(f"📈 EV: <b>{rec_ev*100:+.1f}%</b>")

    return "\n".join(lines)


def format_hockey_puckline_report(
    home_team: str, away_team: str,
    puckline: dict, match_time: str, league_name: str,
) -> str:
    try:
        from datetime import datetime as _dt, timedelta as _td
        dt     = _dt.fromisoformat(match_time.replace("Z", "+00:00"))
        dt_msk = dt + _td(hours=3)
        time_label = dt_msk.strftime("%d.%m %H:%M МСК")
    except Exception:
        time_label = match_time[:16]

    if not puckline:
        return (
            f"🏒 <b>{home_team} vs {away_team}</b>\n"
            f"📅 {league_name} | {time_label}\n\n"
            f"⚠️ Пак-лайн не найден в данных букмекеров."
        )

    h_spr      = puckline.get("home_spread", -1.5)
    a_spr      = puckline.get("away_spread", +1.5)
    h_spr_o    = puckline.get("home_spread_odds", 0.0)
    a_spr_o    = puckline.get("away_spread_odds", 0.0)
    h_cover    = puckline.get("home_cover_prob", 0.0)
    a_cover    = puckline.get("away_cover_prob", 0.0)
    h_ev       = puckline.get("home_ev", 0.0)
    a_ev       = puckline.get("away_ev", 0.0)

    if not h_spr_o or not a_spr_o:
        return (
            f"🏒 <b>{home_team} vs {away_team}</b>\n"
            f"📅 {league_name} | {time_label}\n\n"
            f"⚠️ Пак-лайн не найден в данных букмекеров."
        )

    if h_ev > a_ev and h_ev > 0.04:
        rec_line = f"<b>{home_team} {h_spr:+.1f}</b> @ {h_spr_o}  |  EV {h_ev*100:+.1f}%"
        icon = "✅"
    elif a_ev > 0.04:
        rec_line = f"<b>{away_team} {a_spr:+.1f}</b> @ {a_spr_o}  |  EV {a_ev*100:+.1f}%"
        icon = "✅"
    else:
        rec_line = "Нет ценной ставки на пак-лайн"
        icon = "❌"

    return "\n".join([
        f"🏒 <b>{home_team} vs {away_team}</b>",
        f"📅 {league_name} | {time_label}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📐 <b>ПАК-ЛАЙН (-1.5 / +1.5)</b>",
        "",
        f"🏠 {home_team} <b>{h_spr:+.1f}</b>:  кэф <b>{h_spr_o}</b>",
        f"   Вер-сть закрыть: {round(h_cover*100,1)}%   EV: {h_ev*100:+.1f}%",
        "",
        f"✈️ {away_team} <b>{a_spr:+.1f}</b>:  кэф <b>{a_spr_o}</b>",
        f"   Вер-сть закрыть: {round(a_cover*100,1)}%   EV: {a_ev*100:+.1f}%",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icon} {rec_line}",
        "",
        "<i>* Фаворит закрывает -1.5 когда побеждает с разрывом 2+ шайбы (~62% от побед NHL)</i>",
    ])


# ── Форматирование отчёта ─────────────────────────────────────────────────────

def format_hockey_report(
    home_team: str, away_team: str,
    analysis: dict, odds: dict,
    gpt_result: dict, llama_result: dict,
    match_time: str, league_name: str,
) -> str:
    h_prob     = analysis["home_prob"]
    a_prob     = analysis["away_prob"]
    h_ev       = analysis["h_ev"]
    a_ev       = analysis["a_ev"]
    bet_signal      = analysis["bet_signal"]
    no_bet_reason   = analysis.get("no_bet_reason", "")
    underdog_value  = analysis.get("underdog_value")
    total_data      = analysis.get("total_analysis", {})
    home_form     = analysis.get("home_form", "")
    away_form     = analysis.get("away_form", "")
    home_b2b      = analysis.get("home_b2b", False)
    away_b2b      = analysis.get("away_b2b", False)

    # Время
    try:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        dt     = _dt.fromisoformat(match_time.replace("Z", "+00:00"))
        dt_msk = dt + _td(hours=3)
        time_label = dt_msk.strftime("%d.%m %H:%M МСК")
    except Exception:
        time_label = match_time[:16]

    # Определяем фаворита
    if h_prob >= a_prob:
        fav, und   = home_team, away_team
        fav_prob   = h_prob
        fav_ev     = h_ev
        fav_odds   = odds.get("home_win", 0)
        und_odds   = odds.get("away_win", 0)
    else:
        fav, und   = away_team, home_team
        fav_prob   = a_prob
        fav_ev     = a_ev
        fav_odds   = odds.get("away_win", 0)
        und_odds   = odds.get("home_win", 0)

    und_prob = 1 - fav_prob

    # Kelly
    kelly = 0.0
    if fav_odds > 1.02 and fav_ev > 0:
        kelly = round((fav_prob - (1 - fav_prob) / (fav_odds - 1)) * 100, 1)
        kelly = max(0.0, min(kelly, 25.0))

    # Сигнал блок
    if "🔥🔥🔥" in bet_signal:
        signal_icon = "🔥"
    elif "🔥🔥" in bet_signal:
        signal_icon = "🟢"
    elif "🔥" in bet_signal:
        signal_icon = "🟡"
    else:
        signal_icon = "🔴"

    # EV полоса
    ev_pct = round(fav_ev * 100, 1)
    ev_bar_filled = min(10, max(0, int(ev_pct / 3)))
    ev_bar = "▓" * ev_bar_filled + "░" * (10 - ev_bar_filled)

    # GPT + Llama вердикты
    gpt_verdict   = gpt_result.get("verdict", "")
    gpt_conf      = gpt_result.get("confidence", 0)
    gpt_summary   = gpt_result.get("summary", "")
    llama_verdict = llama_result.get("verdict", "")
    llama_conf    = llama_result.get("confidence", 0)
    llama_summary = llama_result.get("summary", "")

    def _verd_icon(v, fav_is_home):
        if not v:
            return "❓"
        is_home_win = (v == "home_win")
        return "✅" if (is_home_win == fav_is_home) else "⚠️"

    fav_is_home = (fav == home_team)

    # Блок консенсуса
    consensus_block = ""
    ai_agree = (
        bool(gpt_verdict) and bool(llama_verdict)
        and gpt_verdict == llama_verdict
    )
    if ai_agree:
        consensus_block = "🤝 <b>AI Консенсус:</b> Оба агента согласны\n"
    elif gpt_verdict and llama_verdict:
        consensus_block = "⚡ <b>AI Расхождение:</b> Агенты не согласны — выше риск\n"

    # Предупреждение отсутствия ELO данных
    no_elo_warn = ""
    if analysis.get("no_elo_data"):
        no_elo_warn = "⚠️ <i>Команды не в базе ELO — прогноз основан только на букмекерах</i>\n"

    # Форма + голы
    form_block = ""
    if home_form or away_form:
        form_block = (
            f"📈 <b>Форма:</b>  {home_team}: {home_form or '—'}  |  {away_team}: {away_form or '—'}\n"
        )
    home_goals = analysis.get("home_goals", {})
    away_goals = analysis.get("away_goals", {})
    goals_block = ""
    if home_goals.get("gp", 0) >= 3 and away_goals.get("gp", 0) >= 3:
        goals_block = (
            f"🥅 <b>Голы/игра</b> (посл. {home_goals['gp']}г): "
            f"{home_team} {home_goals['gf']} GF / {home_goals['ga']} GA  |  "
            f"{away_team} {away_goals['gf']} GF / {away_goals['ga']} GA\n"
        )
    b2b_block = ""
    if home_b2b:
        b2b_block += f"⚠️ {home_team} играл вчера (усталость)\n"
    if away_b2b:
        b2b_block += f"⚠️ {away_team} играл вчера (усталость)\n"

    # Травмы (NHL через ESPN)
    inj_block = ""
    home_inj = analysis.get("home_injuries", {})
    away_inj = analysis.get("away_injuries", {})
    for team_name, inj in ((home_team, home_inj), (away_team, away_inj)):
        if not inj:
            continue
        parts = []
        if inj.get("injured"):
            parts.append(f"🤕 {', '.join(inj['injured'])}")
        if inj.get("doubts"):
            parts.append(f"❓ {', '.join(inj['doubts'])}")
        if parts:
            impact_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(inj.get("impact", ""), "")
            inj_block += f"{impact_icon} {team_name}: {' | '.join(parts)}\n"

    # Тотал
    total_block = ""
    if total_data:
        lean_icon = "📈" if total_data.get("lean") == "Over" else ("📉" if total_data.get("lean") == "Under" else "➡️")
        total_block = (
            f"\n🏒 <b>Тотал шайб:</b> {total_data['line']} "
            f"(Б {total_data['over_odds']} / М {total_data['under_odds']})\n"
            f"{lean_icon} Склонность: <b>{total_data.get('lean', '—')}</b>\n"
        )

    lines = [
        f"🏒 <b>{home_team} vs {away_team}</b>",
        f"📅 {league_name} | {time_label}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{signal_icon} <b>СИГНАЛ: {bet_signal}</b>",
        *([f"<i>{no_bet_reason}</i>"] if no_bet_reason else []),
        "",
        f"🎯 <b>Ставка:</b> Победа {fav}",
        f"📊 <b>Вероятность:</b> {round(fav_prob*100)}%  (андердог: {round(und_prob*100)}%)",
        f"💰 <b>Кэф:</b> {fav} @ <b>{fav_odds}</b>  |  {und} @ {und_odds}",
        f"📈 <b>EV:</b> {ev_pct:+.1f}%   <code>{ev_bar}</code>",
    ]
    if kelly > 0:
        lines.append(f"🎲 <b>Kelley:</b> {kelly:.1f}% от банка")

    lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━━"]

    if gpt_summary:
        lines += [
            f"🐍🦁🐐 <b>Химера:</b> {_verd_icon(gpt_verdict, fav_is_home)} уверенность {gpt_conf}%",
            f"<i>{gpt_summary[:300]}</i>",
        ]
    if llama_summary:
        lines += [
            f"🌀 <b>Тень:</b> {_verd_icon(llama_verdict, fav_is_home)} уверенность {llama_conf}%",
            f"<i>{llama_summary[:300]}</i>",
        ]

    if no_elo_warn or consensus_block or form_block or goals_block or b2b_block or inj_block:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━━"]
        if no_elo_warn:
            lines.append(no_elo_warn.strip())
        if consensus_block:
            lines.append(consensus_block.strip())
        if form_block:
            lines.append(form_block.strip())
        if goals_block:
            lines.append(goals_block.strip())
        if b2b_block:
            lines.append(b2b_block.strip())
        if inj_block:
            lines += ["", f"🏥 <b>Травмы/выбывшие (NHL):</b>", inj_block.strip()]

    if total_block:
        lines.append(total_block.strip())

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 ELO: {home_team} <b>{analysis['elo_home']}</b>  vs  {away_team} <b>{analysis['elo_away']}</b>",
        f"🔢 Ансамбль: {home_team} {round(h_prob*100)}%  |  {away_team} {round(a_prob*100)}%",
        f"🏦 No-Vig: {home_team} {round(odds.get('no_vig_home',0)*100,1)}%  |  {away_team} {round(odds.get('no_vig_away',0)*100,1)}%",
    ]

    if underdog_value:
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⚠️ <b>КОНТРАРНАЯ СТАВКА (против прогноза):</b>",
            f"Модель даёт победу <b>{fav}</b>, но кэф на <b>{underdog_value['team']}</b> завышен.",
            f"💎 {underdog_value['team']} @ <b>{underdog_value['odds']}</b>  |  Наша вер-сть: {underdog_value['prob']}%  |  EV: <b>+{underdog_value['ev']}%</b>",
            f"🎲 Максимум <b>1% банка</b> — очень высокий риск, только для опытных",
        ]

    return "\n".join(lines)
