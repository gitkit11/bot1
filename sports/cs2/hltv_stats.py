"""
HLTV Stats — Автоматически обновляемые данные
Дата обновления: 2026-03-14
"""

MAP_STATS: dict[str, dict[str, float]] = {
    "Team Vitality": {"Inferno": 77.8, "Dust2": 90.9, "Mirage": 67.4, "Nuke": 70.7, "Train": 68.2, "Overpass": 77.8, "Anubis": 75.0, "Ancient": 50.0},
    "G2 Esports": {"Inferno": 55.6, "Dust2": 60.0, "Mirage": 66.7, "Nuke": 50.0, "Overpass": 57.1, "Anubis": 62.5, "Ancient": 45.0},
    "FaZe Clan": {"Inferno": 50.0, "Dust2": 55.6, "Mirage": 52.4, "Nuke": 47.1, "Overpass": 60.0, "Anubis": 53.3, "Ancient": 50.0},
    "Natus Vincere": {"Inferno": 58.3, "Dust2": 50.0, "Mirage": 61.5, "Nuke": 54.5, "Overpass": 55.6, "Anubis": 57.1, "Ancient": 60.0},
    "Team Spirit": {"Inferno": 65.0, "Dust2": 70.0, "Mirage": 60.0, "Nuke": 72.7, "Overpass": 62.5, "Anubis": 58.3, "Ancient": 55.0},
}

PLAYER_STATS: dict[str, list[dict]] = {
    "Team Vitality": [{"name": "ZywOo", "rating": 1.35}, {"name": "apEX", "rating": 1.05}, {"name": "ropz", "rating": 1.18}, {"name": "mezii", "rating": 1.08}, {"name": "flameZ", "rating": 1.12}],
    "G2 Esports": [{"name": "m0NESY", "rating": 1.28}, {"name": "NiKo", "rating": 1.22}, {"name": "huNter-", "rating": 1.10}, {"name": "jks", "rating": 1.05}, {"name": "HooXi", "rating": 0.98}],
    "FaZe Clan": [{"name": "karrigan", "rating": 0.97}, {"name": "rain", "rating": 1.08}, {"name": "broky", "rating": 1.15}, {"name": "frozen", "rating": 1.12}],
    "Natus Vincere": [{"name": "iM", "rating": 1.05}, {"name": "w0nderful", "rating": 1.18}, {"name": "jL", "rating": 1.10}],
    "Team Spirit": [{"name": "donk", "rating": 1.38}, {"name": "chopper", "rating": 1.02}, {"name": "zont1x", "rating": 1.15}],
}

TEAM_ALIASES: dict[str, str] = {
    "Vitality": "Team Vitality",
    "G2": "G2 Esports",
    "FaZe": "FaZe Clan",
    "NaVi": "Natus Vincere",
    "Spirit": "Team Spirit",
    "mousesports": "MOUZ",
    "Liquid": "Team Liquid",
}
