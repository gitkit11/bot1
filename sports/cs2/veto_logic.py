# -*- coding: utf-8 -*-
import random

# Список официальных карт CS2
ACTIVE_DUTY_POOL = ["Mirage", "Nuke", "Inferno", "Ancient", "Anubis", "Vertigo", "Dust2"]

# База предпочтений команд (Mock-данные для топ-команд)
# 1.0 - всегда играют/пикают, 0.0 - пермабан
TEAM_MAP_PREFERENCES = {
    "Natus Vincere": {"Mirage": 0.9, "Nuke": 0.8, "Inferno": 0.6, "Ancient": 0.9, "Anubis": 0.7, "Vertigo": 0.0, "Dust2": 0.5},
    "Team Vitality": {"Mirage": 0.7, "Nuke": 0.9, "Inferno": 0.8, "Ancient": 0.5, "Anubis": 0.8, "Vertigo": 0.6, "Dust2": 0.7},
    "FaZe Clan": {"Mirage": 0.8, "Nuke": 0.7, "Inferno": 0.9, "Ancient": 0.6, "Anubis": 0.6, "Vertigo": 0.0, "Dust2": 0.8},
    "G2 Esports": {"Mirage": 0.9, "Nuke": 0.6, "Inferno": 0.8, "Ancient": 0.7, "Anubis": 0.7, "Vertigo": 0.4, "Dust2": 0.9},
    "Team Spirit": {"Mirage": 0.8, "Nuke": 0.7, "Inferno": 0.4, "Ancient": 0.9, "Anubis": 0.9, "Vertigo": 0.6, "Dust2": 0.8},
    "MOUZ": {"Mirage": 0.8, "Nuke": 0.8, "Inferno": 0.7, "Ancient": 0.8, "Anubis": 0.6, "Vertigo": 0.9, "Dust2": 0.5},
}

def simulate_bo3_veto(home_team, away_team, team_map_stats=None):
    """
    Симулирует процесс Veto для матча BO3.
    1. Home ban
    2. Away ban
    3. Home pick
    4. Away pick
    5. Home ban
    6. Away ban
    7. Decider
    """
    pool = list(ACTIVE_DUTY_POOL)
    veto_log = []
    
    # Получаем предпочтения (винрейты или mock-данные)
    h_pref = {}
    a_pref = {}
    
    for m in pool:
        # Для хозяев
        if team_map_stats and home_team in team_map_stats and m in team_map_stats[home_team]:
            h_pref[m] = team_map_stats[home_team][m] / 100.0
        else:
            h_pref[m] = TEAM_MAP_PREFERENCES.get(home_team, {}).get(m, 0.5)
            
        # Для гостей
        if team_map_stats and away_team in team_map_stats and m in team_map_stats[away_team]:
            a_pref[m] = team_map_stats[away_team][m] / 100.0
        else:
            a_pref[m] = TEAM_MAP_PREFERENCES.get(away_team, {}).get(m, 0.5)
    
    # 1. Home ban (самая нелюбимая карта)
    h_ban = min(pool, key=lambda m: h_pref.get(m, 0.5))
    pool.remove(h_ban)
    veto_log.append(f"🚫 {home_team} забанил {h_ban}")
    
    # 2. Away ban
    a_ban = min(pool, key=lambda m: a_pref.get(m, 0.5))
    pool.remove(a_ban)
    veto_log.append(f"🚫 {away_team} забанил {a_ban}")
    
    # 3. Home pick (лучшая карта против соперника)
    h_pick = max(pool, key=lambda m: h_pref.get(m, 0.5) - a_pref.get(m, 0.5))
    pool.remove(h_pick)
    veto_log.append(f"✅ {home_team} выбрал {h_pick}")
    
    # 4. Away pick
    a_pick = max(pool, key=lambda m: a_pref.get(m, 0.5) - h_pref.get(m, 0.5))
    pool.remove(a_pick)
    veto_log.append(f"✅ {away_team} выбрал {a_pick}")
    
    # 5. Home ban (из оставшихся)
    h_ban2 = min(pool, key=lambda m: h_pref.get(m, 0.5))
    pool.remove(h_ban2)
    veto_log.append(f"🚫 {home_team} забанил {h_ban2}")
    
    # 6. Away ban
    a_ban2 = min(pool, key=lambda m: a_pref.get(m, 0.5))
    pool.remove(a_ban2)
    veto_log.append(f"🚫 {away_team} забанил {a_ban2}")
    
    # 7. Decider
    decider = pool[0]
    veto_log.append(f"🎲 Decider: {decider}")
    
    return [h_pick, a_pick, decider], veto_log

def get_map_impact_score(team_name, map_name, team_map_stats):
    """
    Рассчитывает MIS (Map Impact Score) для конкретной команды на карте,
    используя реальные данные HLTV (WinRate).
    """
    # Если есть реальные данные, используем их
    if team_name in team_map_stats and map_name in team_map_stats[team_name]:
        # HLTV возвращает процент, делим на 100 для получения доли
        return team_map_stats[team_name][map_name] / 100.0
    
    # Если нет данных, используем mock-данные (предпочтения)
    pref = TEAM_MAP_PREFERENCES.get(team_name, {}).get(map_name, 0.5)
    return pref
