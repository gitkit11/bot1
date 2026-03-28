# -*- coding: utf-8 -*-
"""
Баскетбольный движок CHIMERA.
Стратегия:
  - ELO 35% + Odds 35% + Home Court 15% + Form 15%
  - Тоталы: Over/Under с анализом темпа и тренда
  - Back-to-back штраф: -5% если команда играла вчера
  - Форма: последние 5 игр из The Odds API /scores/
"""

import os
import requests
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

try:
    from config import THE_ODDS_API_KEY
except ImportError:
    THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")

BASKETBALL_LEAGUES = [
    ("basketball_nba",        "🏀 NBA"),
    ("basketball_euroleague", "🏆 Евролига"),
    ("basketball_nbl",        "🇦🇺 NBL Australia"),
]

# ── ELO рейтинги NBA (сезон 2025-26) ─────────────────────────────────────────
NBA_ELO = {
    # Запад
    "Oklahoma City Thunder":      1770,
    "Minnesota Timberwolves":     1720,
    "Houston Rockets":            1710,
    "Los Angeles Lakers":         1680,
    "LA Lakers":                  1680,
    "Denver Nuggets":             1665,
    "Dallas Mavericks":           1650,
    "Golden State Warriors":      1655,
    "Memphis Grizzlies":          1640,
    "Los Angeles Clippers":       1625,
    "LA Clippers":                1625,
    "Phoenix Suns":               1610,
    "Sacramento Kings":           1595,
    "New Orleans Pelicans":       1580,
    "Utah Jazz":                  1530,
    "San Antonio Spurs":          1520,
    "Portland Trail Blazers":     1525,
    # Восток
    "Cleveland Cavaliers":        1760,
    "Boston Celtics":             1750,
    "New York Knicks":            1700,
    "Indiana Pacers":             1690,
    "Milwaukee Bucks":            1660,
    "Miami Heat":                 1645,
    "Orlando Magic":              1630,
    "Atlanta Hawks":              1615,
    "Chicago Bulls":              1600,
    "Detroit Pistons":            1590,
    "Philadelphia 76ers":         1575,
    "Toronto Raptors":            1560,
    "Brooklyn Nets":              1545,
    "Charlotte Hornets":          1535,
    "Washington Wizards":         1510,
}

# ── ELO рейтинги Евролиги (сезон 2025-26) ────────────────────────────────────
EUROLEAGUE_ELO = {
    "FC Barcelona":               1770,
    "Real Madrid":                1755,
    "Olympiacos":                 1730,
    "Fenerbahce SK":              1715,
    "Fenerbahce Beko":            1715,
    "Panathinaikos":              1700,
    "Bayern Munich":              1680,
    "Anadolu Efes":               1660,
    "Efes":                       1660,
    "Maccabi Tel Aviv":           1645,
    "KK Partizan NIS":            1620,
    "Partizan":                   1620,
    "Paris Basketball":           1600,
    "Valencia Basket":            1585,
    "Baskonia":                   1570,
    "AS Monaco":                  1555,
    "Hapoel Tel Aviv":            1540,
    "Virtus Bologna":             1525,
    "Alba Berlin":                1510,
    "Zalgiris Kaunas":            1495,
    "Dubai Basketball":           1475,
    "Crvena Zvezda":              1490,
}

# ── ELO рейтинги NBA G-League / международные ─────────────────────────────────
EXTRA_ELO = {
    # FIBA сборные (для международных турниров)
    "USA":                        1820,
    "Serbia":                     1760,
    "Germany":                    1750,
    "Australia":                  1740,
    "Spain":                      1730,
    "France":                     1720,
    "Canada":                     1710,
    "Greece":                     1700,
    "Slovenia":                   1695,
    "Latvia":                     1680,
    "Lithuania":                  1670,
    "Croatia":                    1660,
    "Italy":                      1650,
    "Argentina":                  1640,
    "Brazil":                     1620,
    "Puerto Rico":                1600,
    # Lega Basket (Италия)
    "EA7 Emporio Armani Milan":   1640,
    "Olimpia Milano":             1640,
    "Dolomiti Energia Trento":    1580,
    "Germani Brescia":            1570,
    # BSL (Турция)
    "Galatasaray":                1590,
    "Besiktas":                   1570,
    "Karsiyaka":                  1550,
}

DEFAULT_ELO       = 1550
HOME_ADVANTAGE_ELO = 50    # домашний корт в баскетболе очень важен
HOME_WIN_RATE_NBA  = 0.595  # исторически НБА: 59.5% дома
B2B_PENALTY        = 0.05   # -5% вероятности за back-to-back

# Градуированный штраф за усталость (дней отдыха → поправка к вероятности)
# 0 дней (сегодня) = -7%, 1 день = -5%, 2 дня = -2%, 3+ = 0%
REST_PENALTY = {0: -0.07, 1: -0.05, 2: -0.02}

# ── Кэш формы и back-to-back (обновляется при каждом запросе) ─────────────────
_form_cache: dict = {}
_b2b_cache:  dict = {}
_rest_days_cache: dict = {}  # team -> days since last game
_cache_ts:   float = 0.0
_CACHE_TTL   = 3600  # 1 час


def _get_elo(team: str, league_key: str = "") -> int:
    """Ищет ELO: сначала файл (после калибровки), потом захардкоженные таблицы."""
    # Попытка загрузить из откалиброванного файла
    try:
        import json
        if os.path.exists("elo_basketball.json"):
            with open("elo_basketball.json", "r", encoding="utf-8") as f:
                live = json.load(f)
            if team in live:
                return live[team]
    except Exception:
        pass

    if "euroleague" in league_key:
        return EUROLEAGUE_ELO.get(team, DEFAULT_ELO)
    return (
        NBA_ELO.get(team)
        or EUROLEAGUE_ELO.get(team)
        or EXTRA_ELO.get(team)
        or DEFAULT_ELO
    )


def _fetch_recent_scores(league_key: str) -> list:
    """Загружает результаты последних 3 дней из The Odds API /scores/ (с кешем 15 мин)."""
    if not THE_ODDS_API_KEY:
        return []
    try:
        from odds_cache import get_scores as _get_scores
        all_scores = _get_scores(league_key, days_from=3)
        return [m for m in all_scores if m.get("completed")]
    except ImportError:
        pass
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{league_key}/scores/",
            params={"apiKey": THE_ODDS_API_KEY, "daysFrom": 3},
            timeout=10,
        )
        if r.ok:
            return [m for m in r.json() if m.get("completed")]
    except Exception as e:
        logger.warning(f"[Basketball] scores fetch error: {e}")
    return []


def _build_form_and_b2b(league_key: str):
    """
    Заполняет _form_cache и _b2b_cache на основе последних результатов.
    form_cache[team] = "WWLWL" (последние 5, слева = новее)
    b2b_cache[team]  = True если последний матч был вчера или сегодня
    """
    global _form_cache, _b2b_cache, _cache_ts
    import time
    if time.time() - _cache_ts < _CACHE_TTL:
        return

    scores = _fetch_recent_scores(league_key)
    now = datetime.now(timezone.utc)

    team_results: dict = {}  # team -> [(dt, won)]

    for m in scores:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        raw_scores = m.get("scores") or []
        score_map  = {s["name"]: int(s["score"]) for s in raw_scores if s.get("name") and s.get("score")}
        h_score = score_map.get(home, 0)
        a_score = score_map.get(away, 0)
        if h_score == a_score:
            continue

        # Дата матча
        ct = m.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        except Exception:
            dt = now - timedelta(days=3)

        h_won = h_score > a_score
        team_results.setdefault(home, []).append((dt, h_won))
        team_results.setdefault(away, []).append((dt, not h_won))

    for team, results in team_results.items():
        results.sort(key=lambda x: x[0], reverse=True)  # новее первым
        # Форма: последние 5 с экспоненциальным весом (последний матч = 1.0, -1 = 0.7, -2 = 0.5 …)
        weights = [1.0, 0.7, 0.5, 0.35, 0.25]
        form_str = "".join("W" if w else "L" for _, w in results[:5])
        _form_cache[team] = form_str
        # B2B + дней отдыха
        if results:
            last_dt = results[0][0]
            hours_ago = (now - last_dt).total_seconds() / 3600
            days_rest = int(hours_ago / 24)
            _b2b_cache[team] = hours_ago < 36
            _rest_days_cache[team] = days_rest

    _cache_ts = __import__("time").time()


def get_team_form(team: str, league_key: str = "") -> str:
    """Возвращает строку формы 'WWLWL' или '' если нет данных."""
    _build_form_and_b2b(league_key)
    return _form_cache.get(team, "")


def is_back_to_back(team: str, league_key: str = "") -> bool:
    """True если команда играла вчера/сегодня."""
    _build_form_and_b2b(league_key)
    return _b2b_cache.get(team, False)


def get_rest_days(team: str, league_key: str = "") -> int:
    """Возвращает количество дней отдыха с последней игры (0 = сегодня, 99 = нет данных)."""
    _build_form_and_b2b(league_key)
    return _rest_days_cache.get(team, 99)


def _fatigue_penalty(team: str, league_key: str = "") -> float:
    """
    Штраф за усталость на основе дней отдыха.
    0 дней = -7%, 1 день = -5%, 2 дня = -2%, 3+ = 0%
    """
    days = get_rest_days(team, league_key)
    return REST_PENALTY.get(days, 0.0)


def elo_win_prob(home: str, away: str, league_key: str = "") -> tuple:
    """Вероятность победы по ELO с учётом домашнего корта."""
    h_elo = _get_elo(home, league_key) + HOME_ADVANTAGE_ELO
    a_elo = _get_elo(away, league_key)
    h_prob = 1 / (1 + 10 ** ((a_elo - h_elo) / 400))
    return round(h_prob, 3), round(1 - h_prob, 3)


def get_basketball_matches(league_key: str) -> list:
    """Загружает матчи из The Odds API для баскетбола (с кешем, все регионы)."""
    if not THE_ODDS_API_KEY:
        return []
    try:
        from odds_cache import get_odds as _get_odds
        raw = _get_odds(league_key, markets="h2h,totals,spreads")
    except ImportError:
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/",
                params={"apiKey": THE_ODDS_API_KEY, "regions": "eu,uk,us,au",
                        "markets": "h2h,totals,spreads", "oddsFormat": "decimal"},
                timeout=12,
            )
            raw = r.json() if r.ok else []
        except Exception as e:
            logger.error(f"[Basketball] Ошибка {league_key}: {e}")
            return []

    if not raw:
        return []
    now    = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=2)).isoformat()[:19]
    matches = [m for m in raw if m.get("commence_time", "") > cutoff]
    logger.info(f"[Basketball] {league_key}: {len(matches)} матчей")
    return matches[:25]


SHARP_BOOKS_BBALL = {"pinnacle", "betfair_ex", "betfair", "matchbook",
                     "smarkets", "lowvig", "betsson", "nordicbet"}


def get_basketball_odds(match: dict) -> dict:
    """
    Извлекает H2H, тотал и фору из матча.
    - Pinnacle no-vig вероятности (убирает маржу)
    - Медиана острых букмекеров (не первый попавшийся)
    - Все регионы (eu, uk, us, au) через odds_cache
    """
    import statistics

    home_team = match.get("home_team", "")
    away_team = match.get("away_team", "")

    result = {
        "home_win": 0.0, "away_win": 0.0,
        "over": 0.0, "under": 0.0, "total_line": 0.0,
        "spread_home": 0.0, "spread_home_odds": 0.0,
        "spread_away": 0.0, "spread_away_odds": 0.0,
        "bookmaker": "",
        # Новые поля
        "no_vig_home": 0.0, "no_vig_away": 0.0,
        "pinnacle_home": 0.0, "pinnacle_away": 0.0,
        "bookmakers_count": 0,
    }

    all_home_odds: list = []   # коэффициенты всех букмекеров
    all_away_odds: list = []
    sharp_home_odds: list = [] # только острые
    sharp_away_odds: list = []
    pinnacle_home = 0.0
    pinnacle_away = 0.0

    total_found   = False
    spreads_found = False

    bookmakers = match.get("bookmakers", [])
    result["bookmakers_count"] = len(bookmakers)

    for bm in bookmakers:
        bm_key   = bm.get("key", "").lower()
        bm_title = bm.get("title", "")
        is_sharp = any(s in bm_key for s in SHARP_BOOKS_BBALL)

        for market in bm.get("markets", []):
            mkey = market.get("key", "")

            if mkey == "h2h":
                oc = {o["name"]: float(o.get("price", 0) or 0)
                      for o in market.get("outcomes", [])}
                ph = oc.get(home_team, 0.0)
                pa = oc.get(away_team, 0.0)
                if ph >= 1.02 and pa >= 1.02:
                    all_home_odds.append(ph)
                    all_away_odds.append(pa)
                    if is_sharp:
                        sharp_home_odds.append(ph)
                        sharp_away_odds.append(pa)
                    if "pinnacle" in bm_key and pinnacle_home == 0.0:
                        pinnacle_home = ph
                        pinnacle_away = pa

            elif mkey == "totals" and not total_found and is_sharp:
                for o in market.get("outcomes", []):
                    if o.get("name") == "Over":
                        result["over"]       = float(o.get("price", 0))
                        result["total_line"] = float(o.get("point", 0))
                    elif o.get("name") == "Under":
                        result["under"] = float(o.get("price", 0))
                if result["over"] and result["under"]:
                    total_found = True

            elif mkey == "spreads" and not spreads_found and is_sharp:
                for o in market.get("outcomes", []):
                    if o.get("name") == home_team:
                        result["spread_home"]      = float(o.get("point", 0))
                        result["spread_home_odds"] = float(o.get("price", 0))
                    elif o.get("name") == away_team:
                        result["spread_away"]      = float(o.get("point", 0))
                        result["spread_away_odds"] = float(o.get("price", 0))
                if result["spread_home_odds"]:
                    spreads_found = True

    # Totals/spreads fallback: если у острых не нашли — берём любой
    if not total_found:
        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market.get("key") == "totals" and not result["over"]:
                    for o in market.get("outcomes", []):
                        if o.get("name") == "Over":
                            result["over"]       = float(o.get("price", 0))
                            result["total_line"] = float(o.get("point", 0))
                        elif o.get("name") == "Under":
                            result["under"] = float(o.get("price", 0))

    if not spreads_found:
        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market.get("key") == "spreads" and not result["spread_home_odds"]:
                    for o in market.get("outcomes", []):
                        if o.get("name") == home_team:
                            result["spread_home"]      = float(o.get("point", 0))
                            result["spread_home_odds"] = float(o.get("price", 0))
                        elif o.get("name") == away_team:
                            result["spread_away"]      = float(o.get("point", 0))
                            result["spread_away_odds"] = float(o.get("price", 0))

    # Медиана острых букмекеров → основные коэффициенты H2H
    pool_h = sharp_home_odds if sharp_home_odds else all_home_odds
    pool_a = sharp_away_odds if sharp_away_odds else all_away_odds
    if pool_h and pool_a:
        result["home_win"] = round(statistics.median(pool_h), 3)
        result["away_win"] = round(statistics.median(pool_a), 3)
        result["bookmaker"] = "median_sharp" if sharp_home_odds else "median_all"

    # Pinnacle no-vig
    if pinnacle_home >= 1.02 and pinnacle_away >= 1.02:
        imp_h = 1 / pinnacle_home
        imp_a = 1 / pinnacle_away
        total_imp = imp_h + imp_a
        result["no_vig_home"]   = round(imp_h / total_imp, 4)
        result["no_vig_away"]   = round(imp_a / total_imp, 4)
        result["pinnacle_home"] = pinnacle_home
        result["pinnacle_away"] = pinnacle_away

    return result


def _implied_prob(odds: float) -> float:
    return 1 / odds if odds > 1.02 else 0.0


def calculate_basketball_win_prob(home: str, away: str,
                                   odds: dict = None,
                                   league_key: str = "",
                                   no_vig_home: float = 0.0,
                                   no_vig_away: float = 0.0) -> dict:
    """
    Финальная вероятность победы:
      ELO 35% + Bookmaker Odds 35% + Form/Context 15% + Home Court 15%
      Если есть Pinnacle no-vig — блендируем: model×0.50 + no_vig×0.50
    """
    # Загружаем актуальные веса из signal_engine если есть
    weight_elo  = 0.35
    weight_odds = 0.35
    weight_home = 0.15
    weight_form = 0.15
    try:
        from signal_engine import BASKETBALL_CFG
        weight_elo  = BASKETBALL_CFG.get("weight_elo",  0.35)
        weight_odds = BASKETBALL_CFG.get("weight_odds", 0.35)
        weight_home = BASKETBALL_CFG.get("weight_home", 0.15)
        weight_form = BASKETBALL_CFG.get("weight_form", 0.15)
    except Exception:
        pass

    h_elo_prob, a_elo_prob = elo_win_prob(home, away, league_key)

    # Приоритет: Pinnacle no-vig → медианные коэффициенты → ELO
    if no_vig_home > 0.05 and no_vig_away > 0.05:
        # No-vig уже без маржи — используем напрямую
        h_odds_prob = no_vig_home
        a_odds_prob = no_vig_away
    else:
        # Implied probability из медианных коэффициентов (убираем маржу)
        h_imp = _implied_prob(odds.get("home_win", 0) if odds else 0)
        a_imp = _implied_prob(odds.get("away_win", 0) if odds else 0)
        if h_imp > 0 and a_imp > 0:
            total_imp   = h_imp + a_imp
            h_odds_prob = h_imp / total_imp
            a_odds_prob = a_imp / total_imp
        else:
            h_odds_prob = h_elo_prob
            a_odds_prob = a_elo_prob

    # Форма команд
    h_form = get_team_form(home, league_key)
    a_form = get_team_form(away, league_key)

    def _form_factor(form_str: str) -> float:
        """0.45–0.55 в зависимости от формы."""
        if not form_str:
            return 0.50
        wins = form_str.count("W")
        return 0.40 + wins * 0.03  # 0W=0.40 … 5W=0.55

    h_form_factor = _form_factor(h_form)
    a_form_factor = _form_factor(a_form)
    # Нормализуем форму в вероятность победы
    total_form = h_form_factor + a_form_factor
    h_form_prob = h_form_factor / total_form if total_form > 0 else 0.50

    # Домашнее преимущество уже учтено в ELO (+50) и рыночных коэффициентах
    # weight_home=0 в BASKETBALL_CFG — не двойной счёт

    # Финальная вероятность (веса из BASKETBALL_CFG)
    h_prob = (
        h_elo_prob  * weight_elo  +
        h_odds_prob * weight_odds +
        h_form_prob * weight_form
    )

    # Градуированный штраф за усталость (заменяет плоский B2B_PENALTY)
    h_fatigue = _fatigue_penalty(home, league_key)
    a_fatigue = _fatigue_penalty(away, league_key)
    # Применяем разницу: если оба устали одинаково — нейтрально
    h_prob += (a_fatigue - h_fatigue)  # хозяин получает выгоду если гость устал больше

    # Штраф за травмы ключевых игроков (NBA через ESPN API, -2% за каждого missing)
    if "nba" in league_key.lower() or league_key == "basketball_nba":
        try:
            from injuries import get_nba_injuries as _get_inj
            h_inj = _get_inj(home)
            a_inj = _get_inj(away)
            h_missing = h_inj.get("total_missing", 0)
            a_missing = a_inj.get("total_missing", 0)
            # Каждый травмированный игрок = -2% вероятности, макс -10%
            h_inj_pen = min(0.10, h_missing * 0.02)
            a_inj_pen = min(0.10, a_missing * 0.02)
            h_prob += (a_inj_pen - h_inj_pen)
        except Exception:
            h_inj = a_inj = {"total_missing": 0, "impact": "none", "injured": [], "doubts": []}
    else:
        h_inj = a_inj = None

    h_prob = min(0.95, max(0.05, round(h_prob, 3)))
    a_prob = round(1 - h_prob, 3)

    h_elo = _get_elo(home, league_key)
    a_elo = _get_elo(away, league_key)
    elo_gap = h_elo - a_elo

    # EV расчёт
    h_ev = round((h_prob * (odds["home_win"] if odds else 0) - 1) * 100, 1) if (odds and odds.get("home_win", 0) > 1.02) else 0.0
    a_ev = round((a_prob * (odds["away_win"] if odds else 0) - 1) * 100, 1) if (odds and odds.get("away_win", 0) > 1.02) else 0.0

    # Анализ тотала
    total_analysis = _analyze_total(h_prob, a_prob, odds, elo_gap)

    # Сигнал — prob и EV должны быть от одной и той же команды
    # Если хотя бы один кеф отсутствует — сигнал недостоверен
    both_odds_present = odds and odds.get("home_win", 0) > 1.02 and odds.get("away_win", 0) > 1.02
    if h_ev >= a_ev:
        best_ev    = h_ev
        best_prob  = h_prob
        best_pick  = home
        best_odds  = odds["home_win"] if odds else 0
    else:
        best_ev    = a_ev
        best_prob  = a_prob
        best_pick  = away
        best_odds  = odds["away_win"] if odds else 0
    try:
        from signal_engine import get_bet_tier as _get_tier, BASKETBALL_CFG as _BCFG
        _min_bball_odds = _BCFG.get("min_odds", 1.55)
        _max_bball_odds = _BCFG.get("max_odds", 2.2)
        if best_odds > _max_bball_odds or best_odds < _min_bball_odds:
            bet_signal = "НЕ СТАВИТЬ"
        else:
            bet_signal = _get_tier(best_prob, best_ev, "basketball") if both_odds_present else "НЕ СТАВИТЬ"
    except Exception:
        bet_signal = "СТАВИТЬ 🔥" if (best_ev > 5 and both_odds_present) else "НЕ СТАВИТЬ"

    # Андердог-ценность: если фаворит не проходит порог, проверяем андердога
    underdog_value = None
    if both_odds_present and best_ev < 0:
        und_pick  = away if best_pick == home else home
        und_prob  = a_prob if best_pick == home else h_prob
        und_odds  = (odds.get("away_win", 0) if best_pick == home else odds.get("home_win", 0))
        und_ev    = round((und_prob * und_odds - 1) * 100, 1) if und_odds > 1.02 else 0
        # Ценная ставка на андердога: EV > 20% и кэф >= 3.0 и наша вер-сть >= 15%
        if und_ev > 20 and und_odds >= 3.0 and und_prob >= 0.15:
            und_kelly = round(max(0, min(2.0, (und_prob - (1 - und_prob) / (und_odds - 1)) * 100)), 1)
            underdog_value = {
                "team":   und_pick,
                "odds":   und_odds,
                "prob":   round(und_prob * 100),
                "ev":     und_ev,
                "kelly":  und_kelly,
            }

    # Причина НЕ СТАВИТЬ
    no_bet_reason = ""
    if bet_signal == "НЕ СТАВИТЬ":
        if not both_odds_present:
            no_bet_reason = "⚠️ Коэффициенты не найдены у букмекера"
        elif best_ev < 0:
            bk_implied = round(100 / best_odds) if best_odds > 1 else 0
            no_bet_reason = (
                f"📉 Букмекер переоценивает фаворита: "
                f"бук {bk_implied}% vs наша модель {round(best_prob*100)}% → EV {best_ev:+.1f}%"
            )
        else:
            no_bet_reason = f"📊 EV {best_ev:+.1f}% или вероятность {round(best_prob*100)}% ниже порога"

    return {
        "home_prob":      h_prob,
        "away_prob":      a_prob,
        "elo_home":       h_elo,
        "elo_away":       a_elo,
        "elo_gap":        elo_gap,
        "h_ev":           h_ev,
        "a_ev":           a_ev,
        "best_pick":      best_pick,
        "best_odds":      best_odds,
        "best_ev":        best_ev,
        "bet_signal":      bet_signal,
        "no_bet_reason":   no_bet_reason,
        "underdog_value":  underdog_value,
        "total_analysis":  total_analysis,
        "h_elo_prob":     h_elo_prob,
        "h_odds_prob":    h_odds_prob,
        "home_form":       h_form,
        "away_form":       a_form,
        "home_b2b":        is_back_to_back(home, league_key),
        "away_b2b":        is_back_to_back(away, league_key),
        "home_rest_days":  get_rest_days(home, league_key),
        "away_rest_days":  get_rest_days(away, league_key),
        "home_fatigue":    h_fatigue,
        "away_fatigue":    a_fatigue,
        "home_injuries":   h_inj,
        "away_injuries":   a_inj,
    }


def _analyze_total(h_prob: float, a_prob: float, odds: dict, elo_gap: int) -> dict:
    """
    Анализ тотала (Over/Under) с реальным EV.

    Вероятность Over/Under считается из:
    1. No-vig вероятность из котировок (убираем маржу букмекера)
    2. Корректировка нашей модели: ±3-5% в зависимости от ELO-разрыва и баланса команд
    3. EV = наша вероятность × кэф − 1

    Рекомендуем ставить только при EV > 3%.
    """
    if not odds or not odds.get("total_line"):
        return {}

    line  = odds["total_line"]
    over  = odds["over"]
    under = odds["under"]

    if not over or not under or over < 1.02 or under < 1.02:
        return {}

    # No-vig вероятности из котировок (убираем маржу)
    imp_over  = 1 / over
    imp_under = 1 / under
    total_imp = imp_over + imp_under
    nv_over  = imp_over  / total_imp  # истинная рыночная вероятность Over
    nv_under = imp_under / total_imp  # истинная рыночная вероятность Under

    # Модельная корректировка: ELO-разрыв + баланс команд влияют на темп
    # Сильный фаворит (ELO gap > 150) → удерживает темп → лёгкий сдвиг к Under
    # Равные команды → открытый баскетбол → лёгкий сдвиг к Over
    gap_adj  = 0.0
    strength_gap = abs(h_prob - a_prob)

    if abs(elo_gap) > 200:
        gap_adj = -0.03   # явный фаворит → Under
    elif abs(elo_gap) > 150:
        gap_adj = -0.015
    elif strength_gap < 0.08:
        gap_adj = +0.02   # очень равные → Over

    # Наша вероятность Over = рыночная ± небольшая поправка
    our_over  = max(0.30, min(0.70, nv_over  + gap_adj))
    our_under = 1.0 - our_over

    # EV для обеих сторон
    ev_over  = round((our_over  * over  - 1) * 100, 1)
    ev_under = round((our_under * under - 1) * 100, 1)

    # Выбираем сторону с лучшим EV
    if ev_over >= ev_under and ev_over > 3.0:
        lean      = "Over"
        lean_odds = over
        lean_prob = our_over
        lean_ev   = ev_over
        reason    = f"Равные команды — открытый баскетбол" if strength_gap < 0.08 else f"Рыночная перекос: линия давит на Over"
    elif ev_under > ev_over and ev_under > 3.0:
        lean      = "Under"
        lean_odds = under
        lean_prob = our_under
        lean_ev   = ev_under
        reason    = f"Явный фаворит (ELO разрыв {abs(elo_gap)}) удержит низкий темп" if abs(elo_gap) > 150 else f"Рыночная перекос: линия давит на Under"
    else:
        # Нет ценности — просто информируем
        lean      = "Over" if nv_over >= nv_under else "Under"
        lean_odds = over if lean == "Over" else under
        lean_prob = nv_over if lean == "Over" else nv_under
        lean_ev   = ev_over if lean == "Over" else ev_under
        reason    = "Нет ценности — рынок сбалансирован"

    return {
        "line":       line,
        "lean":       lean,
        "lean_odds":  round(lean_odds, 2),
        "lean_ev":    lean_ev,
        "lean_prob":  round(lean_prob * 100, 1),
        "reason":     reason,
        "over_odds":  over,
        "under_odds": under,
        "nv_over":    round(nv_over * 100, 1),
        "nv_under":   round(nv_under * 100, 1),
        "has_value":  lean_ev > 3.0,
    }


# ── Форматирование отчёта ─────────────────────────────────────────────────────

def format_basketball_report(
    home_team: str, away_team: str,
    analysis: dict, odds: dict,
    gpt_result: dict, llama_result: dict,
    match_time: str, league_name: str,
) -> str:
    h_prob     = analysis["home_prob"]
    a_prob     = analysis["away_prob"]
    h_ev       = analysis["h_ev"]   # уже в процентах
    a_ev       = analysis["a_ev"]
    bet_signal      = analysis["bet_signal"]
    no_bet_reason   = analysis.get("no_bet_reason", "")
    underdog_value  = analysis.get("underdog_value")
    total_data      = analysis.get("total_analysis", {})
    home_form  = analysis.get("home_form", "")
    away_form  = analysis.get("away_form", "")
    home_b2b   = analysis.get("home_b2b", False)
    away_b2b   = analysis.get("away_b2b", False)

    try:
        from datetime import datetime as _dt, timedelta as _td
        dt     = _dt.fromisoformat(match_time.replace("Z", "+00:00"))
        dt_msk = dt + _td(hours=3)
        time_label = dt_msk.strftime("%d.%m %H:%M МСК")
    except Exception:
        time_label = match_time[:16]

    if h_prob >= a_prob:
        fav, und = home_team, away_team
        fav_prob = h_prob
        fav_ev   = h_ev
        fav_odds = odds.get("home_win", 0)
        und_odds = odds.get("away_win", 0)
    else:
        fav, und = away_team, home_team
        fav_prob = a_prob
        fav_ev   = a_ev
        fav_odds = odds.get("away_win", 0)
        und_odds = odds.get("home_win", 0)

    und_prob = 1 - fav_prob

    kelly = 0.0
    if fav_odds > 1.02 and fav_ev > 0:
        kelly = round((fav_prob - (1 - fav_prob) / (fav_odds - 1)) * 100, 1)
        kelly = max(0.0, min(kelly, 25.0))

    # Иконка сигнала
    if "🔥🔥🔥" in bet_signal:
        signal_icon = "🔥"
    elif "🔥🔥" in bet_signal:
        signal_icon = "🟢"
    elif "🔥" in bet_signal:
        signal_icon = "🟡"
    else:
        signal_icon = "🔴"

    # EV-полоса (EV уже в %, напр. 12.5)
    ev_bar_filled = min(10, max(0, int(fav_ev / 3)))
    ev_bar = "▓" * ev_bar_filled + "░" * (10 - ev_bar_filled)

    gpt_verdict   = gpt_result.get("verdict", "")
    gpt_conf      = gpt_result.get("confidence", 0)
    gpt_summary   = gpt_result.get("summary", "")
    llama_verdict = llama_result.get("verdict", "")
    llama_conf    = llama_result.get("confidence", 0)
    llama_summary = llama_result.get("summary", "")

    def _verd_icon(v, fav_is_home):
        if not v:
            return "❓"
        return "✅" if ((v == "home_win") == fav_is_home) else "⚠️"

    fav_is_home = (fav == home_team)

    ai_agree = bool(gpt_verdict) and bool(llama_verdict) and gpt_verdict == llama_verdict
    consensus_block = ""
    if ai_agree:
        consensus_block = "🤝 <b>AI Консенсус:</b> Оба агента согласны\n"
    elif gpt_verdict and llama_verdict:
        consensus_block = "⚡ <b>AI Расхождение:</b> Агенты не согласны — выше риск\n"

    form_block = ""
    if home_form or away_form:
        form_block = f"📈 <b>Форма:</b>  {home_team}: {home_form or '—'}  |  {away_team}: {away_form or '—'}\n"
    b2b_block = ""
    if home_b2b:
        b2b_block += f"⚠️ {home_team} играл вчера (back-to-back)\n"
    if away_b2b:
        b2b_block += f"⚠️ {away_team} играл вчера (back-to-back)\n"

    total_block = ""
    if total_data:
        lean_icon = "📈" if total_data.get("lean") == "Over" else ("📉" if total_data.get("lean") == "Under" else "➡️")
        total_block = (
            f"\n🏀 <b>Тотал очков:</b> {total_data['line']} "
            f"(Б {total_data['over_odds']} / М {total_data['under_odds']})\n"
            f"{lean_icon} Склонность: <b>{total_data.get('lean', '—')}</b>\n"
        )

    lines = [
        f"🏀 <b>{home_team} vs {away_team}</b>",
        f"📅 {league_name} | {time_label}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{signal_icon} <b>СИГНАЛ: {bet_signal}</b>",
        *([f"<i>{no_bet_reason}</i>"] if no_bet_reason else []),
        "",
        f"🎯 <b>Ставка:</b> Победа {fav}",
        f"📊 <b>Вероятность:</b> {round(fav_prob*100)}%  (андердог: {round(und_prob*100)}%)",
        f"💰 <b>Кэф:</b> {fav} @ <b>{fav_odds}</b>  |  {und} @ {und_odds}",
        f"📈 <b>EV:</b> {fav_ev:+.1f}%   <code>{ev_bar}</code>",
    ]
    if kelly > 0:
        lines.append(f"🎲 <b>Kelly:</b> {kelly:.1f}% от банка")

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

    if consensus_block or form_block or b2b_block:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━━"]
        if consensus_block:
            lines.append(consensus_block.strip())
        if form_block:
            lines.append(form_block.strip())
        if b2b_block:
            lines.append(b2b_block.strip())

    if total_block:
        lines.append(total_block.strip())

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 ELO: {home_team} <b>{analysis.get('elo_home','?')}</b>  vs  {away_team} <b>{analysis.get('elo_away','?')}</b>",
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
