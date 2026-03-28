# -*- coding: utf-8 -*-
"""
historical_movement.py — Движение линий через Historical Odds API
==================================================================
Сравниваем текущие коэффициенты Pinnacle с коэффициентами 24 часа назад.
Если шарп-букмекер (Pinnacle) двинул линию в нашу сторону → подтверждение.
Если против нас → предупреждение.

Стоимость: 10 кредитов за снапшот лиги (все матчи сразу).
Кеш: файловый, TTL 1 час — один снапшот на всех пользователей.

Публичный API:
  get_line_movement(sport_key, match_id, home_team, away_team, current_odds)
    → dict: {signal, home_move, draw_move, away_move, label}
"""

import os
import json
import time
import threading
import requests
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

try:
    from config import THE_ODDS_API_KEY as _API_KEY
except ImportError:
    _API_KEY = os.getenv("THE_ODDS_API_KEY", "")

BASE_URL  = "https://api.the-odds-api.com/v4"
SNAP_FILE = "historical_odds_cache.json"  # {sport_key::hours_ago → {ts, data}}
SNAP_TTL  = 7200   # 2 часа — снапшот 24h-назад не меняется, кешируем

# ─── Шарп-букмекеры (Pinnacle лучший, затем остальные) ────────────────────────
SHARP_PRIORITY = ["pinnacle", "betfair_ex", "betfair", "matchbook", "marathonbet"]

# ─── In-memory кеш + блокировка ───────────────────────────────────────────────
# Предотвращает параллельные API-вызовы из нескольких потоков для одной лиги
_mem_cache: dict = {}
_mem_lock  = threading.Lock()
_fetching:  set  = set()   # ключи, которые уже в процессе загрузки

# ─── Файловый кеш снапшотов ───────────────────────────────────────────────────

def _snap_load() -> dict:
    try:
        if os.path.exists(SNAP_FILE):
            with open(SNAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Чистим устаревшие записи (старше 48 часов)
            cutoff = time.time() - 172800
            return {k: v for k, v in data.items() if v.get("ts", 0) > cutoff}
    except Exception:
        pass
    return {}


def _snap_save(data: dict):
    try:
        tmp = SNAP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, SNAP_FILE)
    except Exception as e:
        logger.warning(f"[HistoricalMov] Ошибка сохранения: {e}")


def _get_snapshot(sport_key: str, hours_ago: int) -> dict:
    """
    Получает снапшот коэффициентов для лиги N часов назад.
    Возвращает {match_id: {"pinnacle_h":x, "pinnacle_d":x, "pinnacle_a":x}} или {}
    Стоимость: 10 кредитов API если нет кеша.
    In-memory кеш предотвращает параллельные запросы из разных потоков.
    """
    cache_key = f"{sport_key}::{hours_ago}h"

    # Шаг 1: Проверяем in-memory кеш (общий для всех потоков)
    with _mem_lock:
        mem_entry = _mem_cache.get(cache_key)
        if mem_entry and (time.time() - mem_entry["ts"]) < SNAP_TTL:
            return mem_entry["data"]
        # Если другой поток уже загружает этот ключ — возвращаем устаревшее
        if cache_key in _fetching:
            return mem_entry["data"] if mem_entry else {}
        _fetching.add(cache_key)

    try:
        # Шаг 2: Проверяем файловый кеш (восстановление после перезапуска)
        snap_cache = _snap_load()
        entry = snap_cache.get(cache_key)
        if entry and (time.time() - entry["ts"]) < SNAP_TTL:
            with _mem_lock:
                _mem_cache[cache_key] = entry
            return entry.get("data", {})

        # Шаг 3: Запрашиваем API
        snap_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        snap_ts = snap_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        r = requests.get(
            f"{BASE_URL}/historical/sports/{sport_key}/odds/",
            params={
                "apiKey":     _API_KEY,
                "date":       snap_ts,
                "regions":    "eu,uk",
                "markets":    "h2h",
                "oddsFormat": "decimal",
            },
            timeout=15,
        )
        remaining = r.headers.get("x-requests-remaining", "?")
        cost = r.headers.get("x-requests-last", "?")
        logger.info(f"[HistoricalMov] {sport_key} {hours_ago}h → cost={cost} remaining={remaining}")

        if r.status_code == 404 or r.status_code == 422:
            # Лига не поддерживается в historical — кешируем пустой результат
            empty_entry = {"ts": time.time(), "data": {}}
            snap_cache[cache_key] = empty_entry
            _snap_save(snap_cache)
            with _mem_lock:
                _mem_cache[cache_key] = empty_entry
            return {}

        if not r.ok:
            logger.warning(f"[HistoricalMov] HTTP {r.status_code} для {sport_key}")
            return {}

        raw = r.json()
        events = raw.get("data", [])

        result = {}
        for event in events:
            mid   = event.get("id", "")
            home  = event.get("home_team", "")
            away  = event.get("away_team", "")
            bookmakers = event.get("bookmakers", [])

            ph = pd = pa = 0.0
            for priority_key in SHARP_PRIORITY:
                for bm in bookmakers:
                    if priority_key not in bm.get("key", "").lower():
                        continue
                    for market in bm.get("markets", []):
                        if market.get("key") != "h2h":
                            continue
                        oc = {o["name"]: float(o.get("price", 0) or 0)
                              for o in market.get("outcomes", [])}
                        h = oc.get(home, 0)
                        a = oc.get(away, 0)
                        d = oc.get("Draw", 0)
                        if h >= 1.02 and a >= 1.02:
                            ph, pd, pa = h, d, a
                            break
                    if ph:
                        break
                if ph:
                    break

            if ph:
                result[mid] = {
                    "pinnacle_h": round(ph, 3),
                    "pinnacle_d": round(pd, 3),
                    "pinnacle_a": round(pa, 3),
                    "home_team":  home,
                    "away_team":  away,
                }

        new_entry = {"ts": time.time(), "data": result}
        snap_cache[cache_key] = new_entry
        _snap_save(snap_cache)
        with _mem_lock:
            _mem_cache[cache_key] = new_entry
        logger.info(f"[HistoricalMov] {sport_key} {hours_ago}h: {len(result)} матчей")
        return result

    except Exception as e:
        logger.warning(f"[HistoricalMov] Ошибка get_snapshot({sport_key}, {hours_ago}h): {e}")
        return {}
    finally:
        with _mem_lock:
            _fetching.discard(cache_key)


# ─── Публичный API ─────────────────────────────────────────────────────────────

def get_line_movement(
    sport_key: str,
    match_id:  str,
    home_team: str,
    away_team: str,
    current_pinnacle_home: float = 0.0,
    current_pinnacle_away: float = 0.0,
    current_pinnacle_draw: float = 0.0,
) -> dict:
    """
    Анализирует движение линии Pinnacle за последние 24 часа.

    Возвращает:
    {
      "signal":    "sharp_home" | "sharp_away" | "sharp_draw" | "neutral" | "unknown",
      "home_move": +0.05,   # изменение вероятности P1 (+ = движение к P1, - = от P1)
      "away_move": -0.03,
      "draw_move": -0.02,
      "label":     "📈 Шарп деньги на Хозяев (+5%)",
      "score_boost": +8,   # добавка к CHIMERA Score
      "data_age_hours": 24,
    }
    """
    empty = {
        "signal": "unknown", "home_move": 0.0, "away_move": 0.0, "draw_move": 0.0,
        "label": "", "score_boost": 0, "data_age_hours": 0,
    }

    if not current_pinnacle_home or not current_pinnacle_away:
        return empty

    # Снапшот 24 часа назад
    snap_24h = _get_snapshot(sport_key, 24)
    snap_6h  = _get_snapshot(sport_key, 6)

    # Ищем матч в снапшотах — по ID или по названиям команд
    def _find_match(snap: dict) -> dict:
        if match_id and match_id in snap:
            return snap[match_id]
        h_low = home_team.lower()
        a_low = away_team.lower()
        for v in snap.values():
            if (v.get("home_team", "").lower() == h_low and
                    v.get("away_team", "").lower() == a_low):
                return v
        return {}

    hist = _find_match(snap_24h)
    if not hist:
        hist = _find_match(snap_6h)
        hours = 6
    else:
        hours = 24

    if not hist or not hist.get("pinnacle_h"):
        return empty

    # Конвертируем коэффициенты в no-vig вероятности
    def _to_novig(h_odd, d_odd, a_odd):
        if not h_odd:
            return 0, 0, 0
        ih = 1 / h_odd
        ia = 1 / a_odd
        total = ih + ia
        if d_odd and d_odd >= 1.02:
            id_ = 1 / d_odd
            total = ih + id_ + ia
            return ih / total, id_ / total, ia / total
        return ih / total, 0, ia / total

    curr_ph, curr_pd, curr_pa = _to_novig(
        current_pinnacle_home,
        current_pinnacle_away,
        current_pinnacle_draw,
    )
    hist_ph, hist_pd, hist_pa = _to_novig(
        hist["pinnacle_h"],
        hist.get("pinnacle_a", 0),
        hist.get("pinnacle_d", 0),
    )

    home_move = round(curr_ph - hist_ph, 4)  # + = шарп деньги на хозяев
    away_move = round(curr_pa - hist_pa, 4)
    draw_move = round(curr_pd - hist_pd, 4)

    # Порог значимого движения
    THRESHOLD = 0.025  # 2.5% сдвиг вероятности = значимо

    max_move = max(abs(home_move), abs(away_move), abs(draw_move))

    if max_move < THRESHOLD:
        signal = "neutral"
        label = "↔️ Линия стабильна"
        boost = 0
    elif abs(home_move) == max_move and home_move > 0:
        pct = round(home_move * 100, 1)
        signal = "sharp_home"
        label  = f"📈 Шарп деньги на хозяев (+{pct}%)"
        boost  = min(12, int(home_move * 200))   # +4..+12 pts
    elif abs(away_move) == max_move and away_move > 0:
        pct = round(away_move * 100, 1)
        signal = "sharp_away"
        label  = f"📈 Шарп деньги на гостей (+{pct}%)"
        boost  = min(12, int(away_move * 200))
    elif abs(draw_move) == max_move and draw_move > 0:
        pct = round(draw_move * 100, 1)
        signal = "sharp_draw"
        label  = f"📈 Шарп деньги на ничью (+{pct}%)"
        boost  = min(8, int(draw_move * 200))
    else:
        # Линия движется против всех исходов (нет доминирующего направления)
        signal = "fade"
        label  = "📉 Линия сдвинулась против"
        boost  = -6

    return {
        "signal":         signal,
        "home_move":      home_move,
        "away_move":      away_move,
        "draw_move":      draw_move,
        "label":          label,
        "score_boost":    boost,
        "data_age_hours": hours,
    }


def prefetch_snapshots(sport_keys: list, hours_list: list = None):
    """
    Предзагрузка снапшотов в фоне для списка лиг.
    Вызывается перед CHIMERA сканом чтобы снапшоты уже были в кеше.
    """
    if hours_list is None:
        hours_list = [24, 6]
    import threading
    def _fetch():
        for sk in sport_keys:
            for h in hours_list:
                try:
                    _get_snapshot(sk, h)
                except Exception:
                    pass
    threading.Thread(target=_fetch, daemon=True).start()
