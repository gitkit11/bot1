# -*- coding: utf-8 -*-
"""
line_movement.py — Отслеживание движения линий (коэффициентов)
=============================================================
Сохраняет первый снимок коэффициентов (открытие) и сравнивает
с текущими. Резкое падение кэфа = профессиональные деньги.

Логика:
  П1 кэф упал 2.20 → 1.75 (-20%) за 6 часов = SHARP MONEY на П1
  Если наш прогноз совпадает → +15 pts к CHIMERA
  Если против → -10 pts (осторожно)
"""

import json
import os
import time
from datetime import datetime

SNAPSHOT_FILE = "odds_snapshots.json"
SHARP_THRESHOLD_PCT = 8.0   # 8%+ движение = умные деньги
MAX_SNAPSHOTS = 1000

_snapshots: dict = {}
_loaded: bool = False


def _load():
    global _snapshots, _loaded
    if _loaded:
        return
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                _snapshots = json.load(f)
        except Exception:
            _snapshots = {}
    _loaded = True


def _save():
    try:
        if len(_snapshots) > MAX_SNAPSHOTS:
            by_age = sorted(_snapshots.keys(), key=lambda k: _snapshots[k].get('ts', 0))
            for old in by_age[:len(_snapshots) - MAX_SNAPSHOTS]:
                del _snapshots[old]
        with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
            json.dump(_snapshots, f, ensure_ascii=False)
    except Exception:
        pass


def make_match_key(home: str, away: str, commence_time: str = "") -> str:
    """Создаёт уникальный ключ матча."""
    date_part = commence_time[:10] if commence_time else datetime.now().strftime("%Y-%m-%d")
    return f"{home.replace(' ', '_')}_{away.replace(' ', '_')}_{date_part}"


def record_odds(match_key: str, odds: dict):
    """
    Записывает ПЕРВЫЙ снимок коэффициентов (открытие).
    Если снимок уже есть — не перезаписывает (нужна точка открытия).
    odds = {"home_win": 2.20, "draw": 3.50, "away_win": 3.20, ...}
    """
    _load()
    if match_key not in _snapshots:
        _snapshots[match_key] = {
            "opening_odds": {k: v for k, v in odds.items() if isinstance(v, (int, float)) and v > 1.0},
            "ts": time.time(),
            "dt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        _save()


def get_movement(match_key: str, current_odds: dict) -> dict:
    """
    Сравнивает текущие кэфы с открытием.
    Возвращает:
    {
      "home_win": {"open": 2.20, "now": 1.75, "chg": -20.5, "dir": "down"},
      "draw":     {"open": 3.50, "now": 3.60, "chg": +2.9,  "dir": "up"},
      "away_win": {"open": 3.20, "now": 4.00, "chg": +25.0, "dir": "up"},
      "sharp_outcome": "home_win",   # исход куда пошли деньги (кэф упал)
      "sharp_pct": -20.5,
      "sharp_strength": "STRONG" / "MODERATE" / None,
      "hours_open": 6.2
    }
    """
    _load()
    if match_key not in _snapshots:
        return {}

    snap = _snapshots[match_key]
    opening = snap["opening_odds"]
    hours_open = (time.time() - snap.get("ts", time.time())) / 3600

    result = {"hours_open": round(hours_open, 1)}

    best_drop_key = None
    best_drop_pct = 0.0

    for key in ["home_win", "draw", "away_win"]:
        o = opening.get(key, 0)
        c = current_odds.get(key, 0)
        if not o or not c or o <= 1.0 or c <= 1.0:
            continue

        chg = (c - o) / o * 100
        result[key] = {
            "open": round(o, 2),
            "now": round(c, 2),
            "chg": round(chg, 1),
            "dir": "down" if chg < 0 else "up",
        }

        if chg < best_drop_pct:
            best_drop_pct = chg
            best_drop_key = key

    if best_drop_key and abs(best_drop_pct) >= SHARP_THRESHOLD_PCT:
        result["sharp_outcome"] = best_drop_key
        result["sharp_pct"] = round(best_drop_pct, 1)
        if abs(best_drop_pct) >= 20.0:
            result["sharp_strength"] = "VERY_STRONG"   # синдикаты / крупные профи
        elif abs(best_drop_pct) >= 15.0:
            result["sharp_strength"] = "STRONG"
        else:
            result["sharp_strength"] = "MODERATE"
    else:
        result["sharp_outcome"] = None
        result["sharp_strength"] = None
        result["sharp_pct"] = 0.0

    return result


def get_movement_score(movement: dict, predicted_key: str) -> float:
    """
    Бонус/штраф к CHIMERA Score на основе движения линии.
    predicted_key: "home_win" / "draw" / "away_win"

    Совпадает с прогнозом:   VERY_STRONG=+20, STRONG=+15, MODERATE=+8
    Против прогноза:         VERY_STRONG=-20, STRONG=-12, MODERATE=-5
    Нет данных/нет сигнала:  0
    """
    if not movement:
        return 0.0
    sharp = movement.get("sharp_outcome")
    strength = movement.get("sharp_strength")
    if not sharp or not strength:
        return 0.0

    if sharp == predicted_key:
        return {"VERY_STRONG": 20.0, "STRONG": 15.0, "MODERATE": 8.0}.get(strength, 8.0)
    else:
        return {"VERY_STRONG": -20.0, "STRONG": -12.0, "MODERATE": -5.0}.get(strength, -5.0)


def format_movement_block(movement: dict) -> str:
    """Строка с движением линий для отображения в боте (plain text / Markdown)."""
    if not movement:
        return ""

    labels = {"home_win": "П1", "draw": "X", "away_win": "П2"}
    lines = ["📉 *Движение линий:*"]

    for key, label in labels.items():
        m = movement.get(key)
        if not m:
            continue
        arrow = "📉" if m["dir"] == "down" else "📈"
        lines.append(f"  {arrow} {label}: {m['open']} → {m['now']} ({m['chg']:+.1f}%)")

    sharp = movement.get("sharp_outcome")
    if sharp:
        _str = movement.get("sharp_strength", "")
        icon = "🚨" if _str == "VERY_STRONG" else ("🔴" if _str == "STRONG" else "🟡")
        lbl = labels.get(sharp, sharp)
        lines.append(
            f"\n{icon} *Sharp money:* {lbl} "
            f"({movement['sharp_pct']:+.1f}% за {movement['hours_open']}ч)"
        )

    return "\n".join(lines)
