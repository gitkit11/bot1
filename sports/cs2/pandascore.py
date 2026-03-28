# -*- coding: utf-8 -*-
import os
import requests
import datetime
import time
from difflib import get_close_matches
from dotenv import load_dotenv
from .team_registry import PANDASCORE_IDS, TEAM_ALIASES, normalize_team_name

load_dotenv()

PANDASCORE_BASE = "https://api.pandascore.co/csgo"

# Рабочий кэш — изначально заполнен из team_registry, пополняется при API-запросах
_team_cache: dict[str, int] = dict(PANDASCORE_IDS)
# Negative cache — команды которые не найдены, чтобы не повторять запросы
_team_not_found: set = set()

# Кеш результатов get_team_stats() — один вызов на команду за весь скан
_team_stats_cache: dict = {}   # team_name → (ts, stats_dict)
_TEAM_STATS_TTL = 3600         # 1 час — статистика команды не меняется за час

# _TEAM_REBRANDS — алиас для обратной совместимости; данные в team_registry.TEAM_ALIASES
_TEAM_REBRANDS = TEAM_ALIASES


def _get_headers():
    key = os.getenv("PANDASCORE_API_KEY")
    if not key:
        raise ValueError("PANDASCORE_API_KEY не найден в .env")
    return {"Authorization": f"Bearer {key}"}

def _request_with_retry(url, params=None, retries=3, delay=1.5):
    """Делает GET запрос с retry при SSL/сетевых ошибках."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_get_headers(), params=params, timeout=15)
            return r
        except Exception as e:
            if attempt < retries - 1:
                print(f"[PandaScore] Попытка {attempt+1}/{retries} не удалась: {type(e).__name__}. Повтор через {delay}с...")
                time.sleep(delay)
            else:
                print(f"[PandaScore] Все попытки исчерпаны: {e}")
    return None

def _resolve_team_alias(team_name: str) -> str:
    """Разрешает алиас/ребренд → каноническое имя."""
    return normalize_team_name(team_name)


def get_team_id(team_name):
    """Ищет ID команды по имени. Кэширует результат. Поддерживает fuzzy matching."""
    # Negative cache — не повторяем запросы для команд которые точно не найдены
    if team_name in _team_not_found:
        return None

    # Проверяем кэш напрямую
    if team_name in _team_cache:
        return _team_cache[team_name]

    # Проверяем исторические переименования
    resolved = _resolve_team_alias(team_name)
    if resolved != team_name and resolved in _team_cache:
        _team_cache[team_name] = _team_cache[resolved]
        return _team_cache[team_name]

    # 3. Fuzzy matching по известным именам в кэше (быстро, без API)
    known_names = [k for k, v in _team_cache.items() if isinstance(v, int)]
    close = get_close_matches(team_name, known_names, n=1, cutoff=0.80)
    if close:
        print(f"[PandaScore] Fuzzy match: '{team_name}' → '{close[0]}'")
        _team_cache[team_name] = _team_cache[close[0]]
        return _team_cache[team_name]

    # 1. Поиск по точному имени (filter[name])
    r = _request_with_retry(f"{PANDASCORE_BASE}/teams", params={"filter[name]": team_name})
    if r and r.ok:
        teams = r.json()
        if teams:
            _team_cache[team_name] = teams[0]["id"]
            return teams[0]["id"]

    # 2. Поиск по частичному совпадению (search[name])
    r = _request_with_retry(f"{PANDASCORE_BASE}/teams", params={"search[name]": team_name, "per_page": 5})
    if r and r.ok:
        teams = r.json()
        if teams:
            for t in teams:
                if team_name.lower() in t["name"].lower() or t["name"].lower() in team_name.lower():
                    _team_cache[team_name] = t["id"]
                    return t["id"]
            _team_cache[team_name] = teams[0]["id"]
            return teams[0]["id"]

    # Не нашли — запоминаем чтобы не повторять
    _team_not_found.add(team_name)
    return None

def get_team_stats(team_name, last_n=20):
    """
    Получает реальную статистику команды из истории матчей (с кешем 1 час).
    Возвращает: winrate, wins, losses, last_5_form
    """
    # Кеш — не запрашиваем одну команду больше раза за час
    cached = _team_stats_cache.get(team_name)
    if cached and (time.time() - cached[0]) < _TEAM_STATS_TTL:
        return cached[1]

    team_id = get_team_id(team_name)
    if not team_id:
        return {"winrate": 0.5, "wins": 0, "losses": 0, "form": "?????", "matches": 0}

    r = _request_with_retry(f"{PANDASCORE_BASE}/matches/past",
                             params={"filter[opponent_id]": team_id,
                                     "per_page": last_n,
                                     "sort": "-end_at"})
    if not r or not r.ok:
        return {"winrate": 0.5, "wins": 0, "losses": 0, "form": "?????", "matches": 0}

    matches = r.json()
    wins = 0
    losses = 0
    form_chars = []

    for m in matches:
        if m.get("status") != "finished":
            continue
        winner_id = m.get("winner_id")
        if winner_id == team_id:
            wins += 1
            form_chars.append("W")
        elif winner_id is not None:
            losses += 1
            form_chars.append("L")

    total = wins + losses
    winrate = wins / total if total > 0 else 0.5
    form = "".join(form_chars[-5:]) if form_chars else "?????"

    result = {
        "winrate": round(winrate, 3),
        "wins": wins,
        "losses": losses,
        "form": form,
        "matches": total
    }
    _team_stats_cache[team_name] = (time.time(), result)
    return result

def get_team_map_winrates(team_name: str, last_n: int = 30) -> dict:
    """
    Считает реальный винрейт команды по каждой карте из истории матчей PandaScore.
    Возвращает: {"Inferno": 58.3, "Mirage": 44.0, ...} — винрейт в процентах.
    Если данных нет — возвращает пустой dict.
    """
    team_id = get_team_id(team_name)
    if not team_id:
        return {}

    r = _request_with_retry(
        f"{PANDASCORE_BASE}/matches/past",
        params={"filter[opponent_id]": team_id, "per_page": last_n, "sort": "-end_at"},
    )
    if not r or not r.ok:
        return {}

    map_wins   = {}
    map_total  = {}

    for match in r.json():
        if match.get("status") != "finished":
            continue
        opponents = match.get("opponents", [])
        if len(opponents) < 2:
            continue
        home_id = opponents[0]["opponent"]["id"]
        away_id = opponents[1]["opponent"]["id"]

        for game in match.get("games", []):
            if game.get("status") != "finished":
                continue
            map_data = game.get("map") or {}
            map_name = map_data.get("name", "") if isinstance(map_data, dict) else str(map_data)
            if not map_name or map_name.lower() in ("", "none", "unknown"):
                continue

            winner_obj = game.get("winner") or {}
            winner_id  = winner_obj.get("id") if isinstance(winner_obj, dict) else None

            map_total[map_name] = map_total.get(map_name, 0) + 1
            if winner_id == team_id:
                map_wins[map_name] = map_wins.get(map_name, 0) + 1

    result = {}
    for m, total in map_total.items():
        if total >= 2:  # минимум 2 игры на карте чтобы считать
            result[m] = round(map_wins.get(m, 0) / total * 100, 1)

    return result


def get_head_to_head(team1_name, team2_name, last_n=10):
    """
    Получает статистику личных встреч двух команд.
    Возвращает: team1_wins, team2_wins, total
    """
    team1_id = get_team_id(team1_name)
    team2_id = get_team_id(team2_name)
    if not team1_id or not team2_id:
        return {"team1_wins": 0, "team2_wins": 0, "total": 0}

    r = _request_with_retry(f"{PANDASCORE_BASE}/matches/past",
                             params={"filter[opponent_id]": team1_id,
                                     "per_page": last_n * 3,
                                     "sort": "-end_at"})
    if not r or not r.ok:
        return {"team1_wins": 0, "team2_wins": 0, "total": 0}

    t1_wins = 0
    t2_wins = 0
    matches = r.json()
    for m in matches:
        if m.get("status") != "finished":
            continue
        # Проверяем что оба соперника в матче
        opponent_ids = [o["opponent"]["id"] for o in m.get("opponents", [])]
        if team1_id not in opponent_ids or team2_id not in opponent_ids:
            continue
        winner_id = m.get("winner_id")
        if winner_id == team1_id:
            t1_wins += 1
        elif winner_id == team2_id:
            t2_wins += 1

    return {"team1_wins": t1_wins, "team2_wins": t2_wins, "total": t1_wins + t2_wins}

def get_cs2_matches_pandascore():
    """
    Получает матчи CS2 (включая Tier-2/3) через PandaScore API.
    Автономный модуль: не зависит от config.py.
    """
    key = os.getenv("PANDASCORE_API_KEY")
    if not key:
        print("[PandaScore] Ошибка: PANDASCORE_API_KEY не найден в .env")
        return []

    params = {"per_page": 50}
    matches = []

    r_upcoming = _request_with_retry(f"{PANDASCORE_BASE}/matches/upcoming", params=params)
    if r_upcoming and r_upcoming.status_code == 200:
        for item in r_upcoming.json():
            if item.get('opponents') and len(item['opponents']) >= 2:
                matches.append(parse_pandascore_item(item, status_label="UPCOMING"))

    r_running = _request_with_retry(f"{PANDASCORE_BASE}/matches/running", params=params)
    if r_running and r_running.status_code == 200:
        for item in r_running.json():
            if item.get('opponents') and len(item['opponents']) >= 2:
                matches.append(parse_pandascore_item(item, status_label="LIVE"))

    return matches

def parse_pandascore_item(item, status_label):
    """Парсит один матч из формата PandaScore."""
    opponents = item['opponents']
    home = opponents[0]['opponent']['name']
    away = opponents[1]['opponent']['name']
    home_id = opponents[0]['opponent']['id']
    away_id = opponents[1]['opponent']['id']

    # Кэшируем ID команд
    _team_cache[home] = home_id
    _team_cache[away] = away_id

    start_time = item.get('begin_at')
    time_str = "—"
    if start_time:
        try:
            dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            # Конвертируем в МСК (UTC+3)
            dt_msk = dt + datetime.timedelta(hours=3)
            time_str = dt_msk.strftime("%d.%m %H:%M")
        except Exception:
            pass

    # Формируем статус: если LIVE, то зеленый кружок
    is_live = item.get("status") == "running"
    display_status = "🟢 LIVE" if is_live else time_str

    # Коэффициенты: сначала PandaScore, потом Pinnacle как fallback
    home_odds = 0
    away_odds = 0

    if item.get("market_odds"):
        for market in item["market_odds"]:
            if "winner" in market.get("name", "").lower():
                for selection in market.get("selections", []):
                    if selection.get("name") == home:
                        home_odds = selection.get("odds", 0)
                    elif selection.get("name") == away:
                        away_odds = selection.get("odds", 0)

    if home_odds == 0 and item.get("odds"):
        odds_data = item["odds"]
        if isinstance(odds_data, list):
            for o in odds_data:
                if o.get("name") == home: home_odds = o.get("value", 0)
                if o.get("name") == away: away_odds = o.get("value", 0)
        elif isinstance(odds_data, dict):
            home_odds = odds_data.get("home_win", 0) or odds_data.get("home", 0)
            away_odds = odds_data.get("away_win", 0) or odds_data.get("away", 0)

    # Fallback: берём коэффициенты из Pinnacle (бесплатно, без ключа)
    if home_odds == 0 or away_odds == 0:
        try:
            from .pinnacle_cs2 import get_match_odds
            pin = get_match_odds(home, away)
            if pin:
                home_odds = pin["odds_home"]
                away_odds = pin["odds_away"]
        except Exception:
            pass

    _league_name = item.get('league', {}).get('name', '') if isinstance(item.get('league'), dict) else str(item.get('league', ''))
    _tournament_name = item.get('tournament', {}).get('name', '') if isinstance(item.get('tournament'), dict) else str(item.get('tournament', ''))
    _tier_info = classify_tournament(_league_name, _tournament_name)

    return {
        "id": item['id'],
        "home": home,
        "away": away,
        "home_id": home_id,
        "away_id": away_id,
        "time": display_status,
        "commence_time": start_time,       # ISO UTC — для отображения в отчёте
        "odds": {"home_win": home_odds, "away_win": away_odds},
        "league": _league_name or 'Tier-2/3',
        "match_type": item.get('match_type', 'best_of_3'),
        "tournament": _tournament_name,
        "tier": _tier_info["tier"],        # S/A/B/C
        "tier_label": _tier_info["label"], # 🏆 Major / 🎮 LAN Tier-A / etc.
    }

def get_combined_cs2_matches():
    """Интерфейс для main.py."""
    return get_cs2_matches_pandascore()


# ─── Контекст турнира ────────────────────────────────────────────────────────

# Ключевые слова для классификации
_MAJOR_KW    = ["major", "pgl major", "blast major", "esl major"]
_LAN_S_KW    = ["katowice", "cologne", "esl one", "iem", "blast premier final",
                 "pro league final", "rio", "paris", "copenhagen"]
_LAN_A_KW    = ["blast premier", "pro league", "esl pro league", "navi cup lan",
                 "dreamhack", "weplay", "starladder lan", "lan"]
_ONLINE_KW   = ["online", "regional", "qualifier", "open", "closed", "league season"]

def classify_tournament(league_name: str, tournament_name: str) -> dict:
    """
    Классифицирует турнир: тип (major/lan_s/lan_a/online/regional) и тир (S/A/B/C).
    Возвращает {"type": ..., "tier": ..., "label": ...}
    """
    combined = (league_name + " " + tournament_name).lower()

    if any(kw in combined for kw in _MAJOR_KW):
        return {"type": "major",   "tier": "S", "label": "🏆 Major"}
    if any(kw in combined for kw in _LAN_S_KW):
        return {"type": "lan_s",   "tier": "S", "label": "🎯 LAN Tier-S"}
    if any(kw in combined for kw in _LAN_A_KW):
        return {"type": "lan_a",   "tier": "A", "label": "🎮 LAN Tier-A"}
    if any(kw in combined for kw in _ONLINE_KW):
        return {"type": "online",  "tier": "B", "label": "💻 Online"}
    # По умолчанию — онлайн лига
    return {"type": "online", "tier": "B", "label": "💻 Online"}


# ─── Взвешенная форма (последние 5 важнее) ───────────────────────────────────

def get_team_weighted_form(team_name: str, last_n: int = 20) -> dict:
    """
    Возвращает взвешенный винрейт: последние 5 матчей вес 60%, остальные 40%.
    {'winrate': 0.72, 'winrate_last5': 0.80, 'winrate_old': 0.66, 'form': 'WWLWW', 'matches': 18}
    """
    team_id = get_team_id(team_name)
    if not team_id:
        return {"winrate": 0.5, "winrate_last5": 0.5, "winrate_old": 0.5,
                "form": "?????", "matches": 0, "wins": 0, "losses": 0}

    r = _request_with_retry(
        f"{PANDASCORE_BASE}/matches/past",
        params={"filter[opponent_id]": team_id, "per_page": last_n, "sort": "-end_at"}
    )
    if not r or not r.ok:
        return {"winrate": 0.5, "winrate_last5": 0.5, "winrate_old": 0.5,
                "form": "?????", "matches": 0, "wins": 0, "losses": 0}

    results = []
    for m in r.json():
        if m.get("status") != "finished":
            continue
        winner_id = m.get("winner_id")
        if winner_id is not None:
            results.append(winner_id == team_id)

    if not results:
        return {"winrate": 0.5, "winrate_last5": 0.5, "winrate_old": 0.5,
                "form": "?????", "matches": 0, "wins": 0, "losses": 0}

    wins   = sum(results)
    losses = len(results) - wins
    form   = "".join("W" if r else "L" for r in results[:5])

    # Взвешенный WR: последние 5 × 0.60 + остальные × 0.40
    last5  = results[:5]
    older  = results[5:]
    wr5    = sum(last5) / len(last5)   if last5  else 0.5
    wr_old = sum(older) / len(older)   if older  else wr5
    wr_weighted = wr5 * 0.60 + wr_old * 0.40

    return {
        "winrate":       round(wr_weighted, 3),
        "winrate_last5": round(wr5, 3),
        "winrate_old":   round(wr_old, 3),
        "form":          form,
        "wins":          wins,
        "losses":        losses,
        "matches":       len(results),
    }


# ─── Stand-in детектор ───────────────────────────────────────────────────────

# Известные основные составы (топ-15 команд, 5 игроков)
_KNOWN_ROSTERS: dict = {
    "Team Vitality":  {"ZywOo", "apEX", "flameZ", "mezii", "Spinx"},
    "Team Spirit":    {"donk", "chopper", "magixx", "zont1x", "sh1ro"},
    "Natus Vincere":  {"b1t", "iM", "jL", "w0nderful", "npl"},
    "FaZe Clan":      {"karrigan", "rain", "broky", "ropz", "frozen"},
    "G2 Esports":     {"NiKo", "huNter-", "nexa", "jks", "malbsMd"},
    "MOUZ":           {"torzsi", "xertioN", "JDC", "siuhy", "Brollan"},
    "Heroic":         {"cadiaN", "TeSeS", "jabbi", "stavn", "sjuush"},
    "Team Liquid":    {"NAF", "EliGE", "YEKINDAR", "nitr0", "oSee"},
    "Cloud9":         {"Ax1Le", "HObbit", "Perfecto", "fame", "ICY"},
    "Astralis":       {"device", "blameF", "Lucky", "Buzz", "br0"},
    "ENCE":           {"Snappi", "dycha", "gla1ve", "SunPayus", "NertZ"},
    "FURIA":          {"KSCERATO", "yuurih", "arT", "FalleN", "skullz"},
    "BIG":            {"tabseN", "faveN", "Krimbo", "syrsoN", "prosus"},
}

def check_stand_in(team_name: str) -> dict:
    """
    Проверяет текущий состав через PandaScore API.
    Возвращает {"has_standin": bool, "standin_player": str, "missing_player": str}
    """
    known = _KNOWN_ROSTERS.get(team_name)
    if not known:
        return {"has_standin": False, "standin_player": "", "missing_player": ""}

    team_id = get_team_id(team_name)
    if not team_id:
        return {"has_standin": False, "standin_player": "", "missing_player": ""}

    r = _request_with_retry(f"{PANDASCORE_BASE}/teams/{team_id}")
    if not r or not r.ok:
        return {"has_standin": False, "standin_player": "", "missing_player": ""}

    try:
        data = r.json()
        current_players = {
            p.get("name", "") for p in data.get("players", [])
            if p.get("role", "") not in ("coach", "analyst")
        }
        if not current_players:
            return {"has_standin": False, "standin_player": "", "missing_player": ""}

        # Игроки из известного состава которых нет сейчас
        missing = known - current_players
        # Игроки текущего состава которых нет в известном
        added   = current_players - known

        if missing and added:
            return {
                "has_standin": True,
                "standin_player": next(iter(added)),
                "missing_player":  next(iter(missing)),
            }
    except Exception:
        pass

    return {"has_standin": False, "standin_player": "", "missing_player": ""}
