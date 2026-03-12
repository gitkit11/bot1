import json
import os

# Базовая структура мап-пула
MAP_POOL = ["Mirage", "Nuke", "Inferno", "Overpass", "Ancient", "Anubis", "Vertigo"]

def calculate_map_winrate_prob(home_map_stats, away_map_stats):
    """
    Рассчитывает вероятность победы на основе винрейтов на каждой карте.
    home_map_stats: dict {map_name: winrate_percentage}
    """
    home_score = 0
    away_score = 0
    
    # Сравниваем каждую карту из пула
    for map_name in MAP_POOL:
        h_wr = home_map_stats.get(map_name, 50)
        a_wr = away_map_stats.get(map_name, 50)
        
        if h_wr > a_wr:
            home_score += (h_wr - a_wr) / 100
        else:
            away_score += (a_wr - h_wr) / 100
            
    # Нормализация вероятностей
    total = home_score + away_score
    if total == 0:
        return 0.5, 0.5
    
    prob_home = home_score / total
    prob_away = away_score / total
    
    return round(prob_home, 2), round(prob_away, 2)

def get_cs2_elo_win_prob(rating_home, rating_away):
    """Классическая формула ELO для CS2 команд."""
    return 1 / (1 + 10 ** ((rating_away - rating_home) / 400))

def format_cs2_math_report(home_team, away_team, prob_home, prob_away, map_analysis=""):
    """Форматирует отчет для Telegram бота."""
    report = f"📊 **Математический анализ CS2: {home_team} vs {away_team}**\n\n"
    report += f"📈 Вероятность победы (MapPool + ELO):\n"
    report += f"🔹 {home_team}: {int(prob_home * 100)}%\n"
    report += f"🔸 {away_team}: {int(prob_away * 100)}%\n\n"
    
    if map_analysis:
        report += f"🗺 **Анализ карт:**\n{map_analysis}\n"
        
    return report

# Пример данных для тестирования (Mock)
MOCK_TEAMS_STATS = {
    "Natus Vincere": {
        "Mirage": 75, "Nuke": 60, "Inferno": 55, "Ancient": 80, "Anubis": 65, "Vertigo": 40, "Overpass": 50,
        "elo": 1850
    },
    "Team Vitality": {
        "Mirage": 60, "Nuke": 85, "Inferno": 70, "Ancient": 50, "Anubis": 75, "Vertigo": 65, "Overpass": 60,
        "elo": 1820
    }
}
