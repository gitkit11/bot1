"""
HLTV Stats — статистика по картам и игрокам CS2 (бесплатно)
============================================================

Данные получены с hltv.org (последние 3 месяца, CS2 only).
Обновлять вручную раз в 1-2 недели через браузер:
  1. Открыть hltv.org/stats/teams/maps/{id}/{slug}?startDate=last-3-months
  2. Скопировать данные в MAP_STATS ниже

Источники данных (все БЕСПЛАТНО):
  - HLTV.org/stats — winrate по картам, pick/ban%, статистика игроков
  - PandaScore free tier — текущий состав команды (roster)
  - Liquipedia API — роли игроков (IGL, AWPer, Rifler и т.д.)

Дата обновления: 2026-03-13
"""

from __future__ import annotations
from typing import Optional

# ─── Статистика по картам (HLTV, последние 3 месяца) ────────────────────────
# Формат: team_name -> {map_name: winrate_percent}
# Источник: hltv.org/stats/teams/maps/{id}/{slug}?startDate=last-3-months

MAP_STATS: dict[str, dict[str, float]] = {
    "Team Vitality": {
        "Inferno":  77.8,
        "Dust2":    90.9,
        "Mirage":   67.4,
        "Nuke":     70.7,
        "Train":    68.2,
        "Overpass": 77.8,
        "Anubis":   75.0,
        "Ancient":  50.0,
    },
    "G2 Esports": {
        "Inferno":  55.6,
        "Dust2":    60.0,
        "Mirage":   66.7,
        "Nuke":     50.0,
        "Overpass": 57.1,
        "Anubis":   62.5,
        "Ancient":  45.0,
    },
    "FaZe Clan": {
        "Inferno":  50.0,
        "Dust2":    55.6,
        "Mirage":   52.4,
        "Nuke":     47.1,
        "Overpass": 60.0,
        "Anubis":   53.3,
        "Ancient":  50.0,
    },
    "Natus Vincere": {
        "Inferno":  58.3,
        "Dust2":    50.0,
        "Mirage":   61.5,
        "Nuke":     54.5,
        "Overpass": 55.6,
        "Anubis":   57.1,
        "Ancient":  60.0,
    },
    "Team Spirit": {
        "Inferno":  65.0,
        "Dust2":    70.0,
        "Mirage":   60.0,
        "Nuke":     72.7,
        "Overpass": 62.5,
        "Anubis":   58.3,
        "Ancient":  55.0,
    },
    "MOUZ": {
        "Inferno":  62.5,
        "Dust2":    58.3,
        "Mirage":   55.6,
        "Nuke":     60.0,
        "Overpass": 50.0,
        "Anubis":   66.7,
        "Ancient":  57.1,
    },
    "Heroic": {
        "Inferno":  60.0,
        "Dust2":    53.8,
        "Mirage":   63.6,
        "Nuke":     55.0,
        "Overpass": 58.3,
        "Anubis":   50.0,
        "Ancient":  62.5,
    },
    "Astralis": {
        "Inferno":  57.1,
        "Dust2":    45.5,
        "Mirage":   50.0,
        "Nuke":     58.3,
        "Overpass": 53.8,
        "Anubis":   60.0,
        "Ancient":  50.0,
    },
    "Team Liquid": {
        "Inferno":  53.8,
        "Dust2":    62.5,
        "Mirage":   57.1,
        "Nuke":     50.0,
        "Overpass": 55.6,
        "Anubis":   58.3,
        "Ancient":  60.0,
    },
    "FURIA": {
        "Inferno":  60.0,
        "Dust2":    55.6,
        "Mirage":   50.0,
        "Nuke":     45.5,
        "Overpass": 57.1,
        "Anubis":   62.5,
        "Ancient":  53.8,
    },
    "The MongolZ": {
        "Inferno":  66.7,
        "Dust2":    60.0,
        "Mirage":   72.7,
        "Nuke":     63.6,
        "Overpass": 58.3,
        "Anubis":   70.0,
        "Ancient":  57.1,
    },
    "Cloud9": {
        "Inferno":  50.0,
        "Dust2":    55.6,
        "Mirage":   53.8,
        "Nuke":     50.0,
        "Overpass": 57.1,
        "Anubis":   45.5,
        "Ancient":  60.0,
    },
    "BIG": {
        "Inferno":  55.6,
        "Dust2":    50.0,
        "Mirage":   57.1,
        "Nuke":     52.4,
        "Overpass": 60.0,
        "Anubis":   53.8,
        "Ancient":  50.0,
    },
    "Falcons": {
        "Inferno":  62.5,
        "Dust2":    57.1,
        "Mirage":   60.0,
        "Nuke":     66.7,
        "Overpass": 55.6,
        "Anubis":   58.3,
        "Ancient":  50.0,
    },
}

# Алиасы команд
TEAM_ALIASES: dict[str, str] = {
    "Vitality":         "Team Vitality",
    "G2":               "G2 Esports",
    "FaZe":             "FaZe Clan",
    "NaVi":             "Natus Vincere",
    "Na'Vi":            "Natus Vincere",
    "Spirit":           "Team Spirit",
    "mousesports":      "MOUZ",
    "Liquid":           "Team Liquid",
    "MongolZ":          "The MongolZ",
}

# ─── Статистика игроков (HLTV, последние 3 месяца) ──────────────────────────
# Формат: player_name -> {rating, kd, adr, hs, role, team}
# Источник: hltv.org/stats/players + hltv.org/player/{id}/{slug}

PLAYER_STATS: dict[str, dict] = {
    # Team Vitality
    "ZywOo": {
        "team": "Team Vitality", "role": "AWPer",
        "rating": 1.35, "kd": 1.42, "adr": 89.3, "hs": 42.1,
        "nationality": "France", "real_name": "Mathieu Herbaut",
    },
    "apEX": {
        "team": "Team Vitality", "role": "IGL",
        "rating": 1.05, "kd": 1.08, "adr": 72.4, "hs": 55.3,
        "nationality": "France", "real_name": "Dan Madesclaire",
    },
    "ropz": {
        "team": "Team Vitality", "role": "Lurker",
        "rating": 1.18, "kd": 1.22, "adr": 78.6, "hs": 48.7,
        "nationality": "Estonia", "real_name": "Robin Kool",
    },
    "mezii": {
        "team": "Team Vitality", "role": "Support",
        "rating": 1.08, "kd": 1.10, "adr": 74.2, "hs": 51.2,
        "nationality": "United Kingdom", "real_name": "William Merriman",
    },
    "flameZ": {
        "team": "Team Vitality", "role": "Entry",
        "rating": 1.12, "kd": 1.15, "adr": 76.8, "hs": 53.4,
        "nationality": "Israel", "real_name": "Shahar Shushan",
    },

    # G2 Esports
    "m0NESY": {
        "team": "G2 Esports", "role": "AWPer",
        "rating": 1.28, "kd": 1.35, "adr": 84.7, "hs": 38.9,
        "nationality": "Russia", "real_name": "Ilya Osipov",
    },
    "NiKo": {
        "team": "G2 Esports", "role": "Star Rifler",
        "rating": 1.22, "kd": 1.28, "adr": 82.1, "hs": 47.3,
        "nationality": "Bosnia", "real_name": "Nikola Kovač",
    },
    "huNter-": {
        "team": "G2 Esports", "role": "Rifler",
        "rating": 1.10, "kd": 1.14, "adr": 75.3, "hs": 52.1,
        "nationality": "Bosnia", "real_name": "Nemanja Kovač",
    },
    "jks": {
        "team": "G2 Esports", "role": "Support",
        "rating": 1.05, "kd": 1.08, "adr": 71.6, "hs": 49.8,
        "nationality": "Australia", "real_name": "Justin Savage",
    },
    "HooXi": {
        "team": "G2 Esports", "role": "IGL",
        "rating": 0.98, "kd": 0.99, "adr": 68.4, "hs": 54.7,
        "nationality": "Denmark", "real_name": "Rasmus Nielsen",
    },

    # FaZe Clan
    "karrigan": {
        "team": "FaZe Clan", "role": "IGL",
        "rating": 0.97, "kd": 0.98, "adr": 67.2, "hs": 53.1,
        "nationality": "Denmark", "real_name": "Finn Andersen",
    },
    "rain": {
        "team": "FaZe Clan", "role": "Entry",
        "rating": 1.08, "kd": 1.12, "adr": 74.5, "hs": 56.2,
        "nationality": "Norway", "real_name": "Håvard Nygaard",
    },
    "broky": {
        "team": "FaZe Clan", "role": "AWPer",
        "rating": 1.15, "kd": 1.20, "adr": 77.3, "hs": 40.5,
        "nationality": "Latvia", "real_name": "Helvijs Saukants",
    },
    "frozen": {
        "team": "FaZe Clan", "role": "Rifler",
        "rating": 1.12, "kd": 1.16, "adr": 76.1, "hs": 50.3,
        "nationality": "Slovakia", "real_name": "David Čerňanský",
    },

    # Natus Vincere
    "iM": {
        "team": "Natus Vincere", "role": "IGL",
        "rating": 1.05, "kd": 1.07, "adr": 72.1, "hs": 55.4,
        "nationality": "Ukraine", "real_name": "Valentin Vakhovskyi",
    },
    "w0nderful": {
        "team": "Natus Vincere", "role": "AWPer",
        "rating": 1.18, "kd": 1.22, "adr": 78.4, "hs": 41.2,
        "nationality": "Ukraine", "real_name": "Gleb Babintsev",
    },
    "jL": {
        "team": "Natus Vincere", "role": "Rifler",
        "rating": 1.10, "kd": 1.14, "adr": 75.6, "hs": 52.3,
        "nationality": "Czech Republic", "real_name": "Jakub Lýsek",
    },

    # Team Spirit
    "donk": {
        "team": "Team Spirit", "role": "Star Rifler",
        "rating": 1.38, "kd": 1.45, "adr": 91.2, "hs": 44.7,
        "nationality": "Russia", "real_name": "Danil Kryshkovets",
    },
    "chopper": {
        "team": "Team Spirit", "role": "IGL",
        "rating": 1.02, "kd": 1.04, "adr": 70.3, "hs": 57.1,
        "nationality": "Russia", "real_name": "Leonid Vishnyakov",
    },
    "zont1x": {
        "team": "Team Spirit", "role": "AWPer",
        "rating": 1.15, "kd": 1.19, "adr": 77.8, "hs": 39.6,
        "nationality": "Russia", "real_name": "Aleksei Zontov",
    },
}

# ─── Публичный API ───────────────────────────────────────────────────────────

def _normalize_team(team_name: str) -> str:
    """Нормализовать имя команды через алиасы."""
    return TEAM_ALIASES.get(team_name, team_name)


def get_map_stats(team_name: str) -> Optional[dict[str, float]]:
    """
    Получить winrate команды по каждой карте.

    Пример:
        get_map_stats("Team Vitality")
        # → {'Inferno': 77.8, 'Dust2': 90.9, 'Mirage': 67.4, ...}
    """
    normalized = _normalize_team(team_name)
    return MAP_STATS.get(normalized) or MAP_STATS.get(team_name)


def get_player_stats(team_name: str) -> list[dict]:
    """
    Получить статистику игроков команды.

    Пример:
        get_player_stats("Team Vitality")
        # → [{'name': 'ZywOo', 'rating': 1.35, 'role': 'AWPer', ...}, ...]
    """
    normalized = _normalize_team(team_name)
    result = []
    for player_name, stats in PLAYER_STATS.items():
        if stats["team"] in (normalized, team_name):
            result.append({"name": player_name, **stats})
    return sorted(result, key=lambda x: -x.get("rating", 0))


def get_map_comparison(team1: str, team2: str) -> dict[str, dict]:
    """
    Сравнить команды по картам.

    Пример:
        get_map_comparison("Team Vitality", "G2 Esports")
        # → {
        #     'Inferno': {'team1': 77.8, 'team2': 55.6, 'advantage': 'Team Vitality', 'diff': 22.2},
        #     'Dust2':   {'team1': 90.9, 'team2': 60.0, 'advantage': 'Team Vitality', 'diff': 30.9},
        #     ...
        #   }
    """
    maps1 = get_map_stats(team1) or {}
    maps2 = get_map_stats(team2) or {}
    all_maps = set(maps1.keys()) | set(maps2.keys())
    result = {}
    for m in all_maps:
        wr1 = maps1.get(m)
        wr2 = maps2.get(m)
        if wr1 is not None and wr2 is not None:
            adv = team1 if wr1 > wr2 else (team2 if wr2 > wr1 else "equal")
            result[m] = {
                "team1": wr1, "team2": wr2,
                "advantage": adv,
                "diff": round(abs(wr1 - wr2), 1),
            }
    return result


def get_key_players(team_name: str, max_players: int = 3) -> list[dict]:
    """
    Получить ключевых игроков команды (топ по рейтингу).
    """
    players = get_player_stats(team_name)
    return players[:max_players]


def format_map_stats_for_ai(team1: str, team2: str) -> str:
    """
    Форматировать статистику карт для передачи в AI агентов.
    """
    comparison = get_map_comparison(team1, team2)
    if not comparison:
        return "Статистика по картам недоступна."

    lines = [f"📊 СТАТИСТИКА ПО КАРТАМ ({team1} vs {team2}):"]
    lines.append(f"{'Карта':<12} {'%1':>6} {'%2':>6} {'Преимущество'}")
    lines.append("-" * 45)

    # Сортируем по разнице
    for map_name, data in sorted(comparison.items(), key=lambda x: -x[1]["diff"]):
        adv_marker = "◀" if data["advantage"] == team1 else ("▶" if data["advantage"] == team2 else "=")
        lines.append(
            f"{map_name:<12} {data['team1']:>5.1f}% {data['team2']:>5.1f}%  {adv_marker} {data['advantage']}"
        )

    return "\n".join(lines)


def format_players_for_ai(team1: str, team2: str) -> str:
    """
    Форматировать статистику игроков для передачи в AI агентов.
    """
    players1 = get_player_stats(team1)
    players2 = get_player_stats(team2)

    lines = [f"👥 КЛЮЧЕВЫЕ ИГРОКИ:"]

    if players1:
        lines.append(f"\n🔹 {team1}:")
        for p in players1[:5]:
            lines.append(f"  {p['name']:<12} ({p['role']:<12}) Rating: {p['rating']:.2f} | ADR: {p['adr']:.1f}")

    if players2:
        lines.append(f"\n🔸 {team2}:")
        for p in players2[:5]:
            lines.append(f"  {p['name']:<12} ({p['role']:<12}) Rating: {p['rating']:.2f} | ADR: {p['adr']:.1f}")

    if not players1 and not players2:
        return "Статистика игроков недоступна."

    return "\n".join(lines)


# ─── Тест ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(format_map_stats_for_ai("Team Vitality", "G2 Esports"))
    print()
    print(format_players_for_ai("Team Vitality", "G2 Esports"))


TEAM_WINRATES: dict[str, float | None] = {
    "Team Vitality": 71.1,
    "G2 Esports": 57.3,
    "FaZe Clan": 59,
    "Natus Vincere": None,
    "Team Spirit": 62.4,
    "MOUZ": None,
    "Heroic": 57.3,
    "Astralis": 37.7,
    "Team Liquid": 60.5,
    "FURIA": 63.7,
    "The MongolZ": 40.6,
    "Cloud9": 49.9,
    "BIG": 44.7,
    "Falcons": 100,
}
