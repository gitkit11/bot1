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

def get_team_map_stats(team_name: str) -> dict:
    name = TEAM_ALIASES.get(team_name, team_name)
    return MAP_STATS.get(name, {})

def get_player_stats(team_name: str) -> list:
    name = TEAM_ALIASES.get(team_name, team_name)
    return PLAYER_STATS.get(name, [])

def format_map_stats_for_ai(home_team: str, away_team: str) -> str:
    h_maps = get_team_map_stats(home_team)
    a_maps = get_team_map_stats(away_team)
    
    if not h_maps and not a_maps:
        return "Статистика карт HLTV недоступна."
        
    res = "🗺 Статистика карт (HLTV Winrate):\n"
    all_maps = set(list(h_maps.keys()) + list(a_maps.keys()))
    for m in sorted(all_maps):
        h_wr = h_maps.get(m, "—")
        a_wr = a_maps.get(m, "—")
        res += f"  • {m}: {home_team} {h_wr}% vs {a_wr}% {away_team}\n"
    return res

def format_players_for_ai(home_team: str, away_team: str) -> str:
    h_players = get_player_stats(home_team)
    a_players = get_player_stats(away_team)
    
    if not h_players and not a_players:
        return "Статистика игроков HLTV недоступна."
        
    res = "👥 Ключевые игроки (HLTV Rating):\n"
    if h_players:
        h_str = ", ".join([f"{p['name']} ({p['rating']})" for p in h_players])
        res += f"  🔹 {home_team}: {h_str}\n"
    if a_players:
        a_str = ", ".join([f"{p['name']} ({p['rating']})" for p in a_players])
        res += f"  🔸 {away_team}: {a_str}\n"
    return res
