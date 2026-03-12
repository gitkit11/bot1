from understatapi import UnderstatClient

print("Подключаюсь к Understat...")

with UnderstatClient() as understat:
    data = understat.league(league='EPL').get_team_data(season='2024')
    print(f"Найдено команд: {len(data)}")
    for team, stats in list(data.items())[:5]:
        history = stats.get('history', [])
        if history:
            # Считаем среднее xG за последние 5 матчей
            last5 = history[-5:]
            avg_xg = sum(float(m.get('xG', 0)) for m in last5) / len(last5)
            avg_xga = sum(float(m.get('xGA', 0)) for m in last5) / len(last5)
            wins = sum(1 for m in history if m.get('wins') == '1')
            print(f"{team}: avg_xG={avg_xg:.2f}, avg_xGA={avg_xga:.2f}, wins={wins}")

print("\nUnderstat работает!")
