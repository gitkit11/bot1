"""
elo_calibrate.py — Пересчёт ELO рейтингов на основе реальных результатов сезона 2024/25.

Источник данных: openfootball/football.json (GitHub, бесплатно, обновляется)
Лиги: АПЛ, Ла Лига, Бундеслига, Серия А, Лига 1

Запуск: python3.11 elo_calibrate.py
Результат: обновляет elo_ratings.json
"""

import requests
import json
import os
from datetime import datetime

# ─── Источники данных ────────────────────────────────────────────────────────

LEAGUE_SOURCES = {
    "soccer_epl": {
        "url": "https://raw.githubusercontent.com/openfootball/football.json/master/2024-25/en.1.json",
        "name": "АПЛ",
    },
    "soccer_spain_la_liga": {
        "url": "https://raw.githubusercontent.com/openfootball/football.json/master/2024-25/es.1.json",
        "name": "Ла Лига",
    },
    "soccer_germany_bundesliga": {
        "url": "https://raw.githubusercontent.com/openfootball/football.json/master/2024-25/de.1.json",
        "name": "Бундеслига",
    },
    "soccer_italy_serie_a": {
        "url": "https://raw.githubusercontent.com/openfootball/football.json/master/2024-25/it.1.json",
        "name": "Серия А",
    },
    "soccer_france_ligue_one": {
        "url": "https://raw.githubusercontent.com/openfootball/football.json/master/2024-25/fr.1.json",
        "name": "Лига 1",
    },
}

# Нормализация названий команд (openfootball → The Odds API)
TEAM_NAME_MAP = {
    # АПЛ
    "Manchester United FC": "Manchester United",
    "Fulham FC": "Fulham",
    "Ipswich Town FC": "Ipswich Town",
    "Liverpool FC": "Liverpool",
    "Arsenal FC": "Arsenal",
    "Wolverhampton Wanderers FC": "Wolverhampton Wanderers",
    "Everton FC": "Everton",
    "Brighton & Hove Albion FC": "Brighton and Hove Albion",
    "Newcastle United FC": "Newcastle United",
    "Southampton FC": "Southampton",
    "Nottingham Forest FC": "Nottingham Forest",
    "West Ham United FC": "West Ham United",
    "Aston Villa FC": "Aston Villa",
    "Brentford FC": "Brentford",
    "Chelsea FC": "Chelsea",
    "Crystal Palace FC": "Crystal Palace",
    "Manchester City FC": "Manchester City",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Leicester City FC": "Leicester City",
    "AFC Bournemouth": "Bournemouth",
    # Ла Лига
    "FC Barcelona": "Barcelona",
    "Real Madrid CF": "Real Madrid",
    "Atlético de Madrid": "Atletico Madrid",
    "Athletic Club": "Athletic Club",
    "Real Sociedad de Fútbol": "Real Sociedad",
    "Villarreal CF": "Villarreal",
    "Real Betis Balompié": "Real Betis",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Rayo Vallecano de Madrid": "Rayo Vallecano",
    "Getafe CF": "Getafe",
    "RC Celta de Vigo": "Celta Vigo",
    "CA Osasuna": "Osasuna",
    "Girona FC": "Girona",
    "UD Las Palmas": "Las Palmas",
    "RCD Mallorca": "Mallorca",
    "Deportivo Alavés": "Alaves",
    "CD Leganés": "Leganes",
    "RCD Espanyol de Barcelona": "Espanyol",
    "Real Valladolid CF": "Valladolid",
    # Бундеслига
    "FC Bayern München": "Bayern Munich",
    "Borussia Dortmund": "Borussia Dortmund",
    "Bayer 04 Leverkusen": "Bayer Leverkusen",
    "RB Leipzig": "RB Leipzig",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "VfL Wolfsburg": "Wolfsburg",
    "SC Freiburg": "Freiburg",
    "1. FC Union Berlin": "Union Berlin",
    "Borussia Mönchengladbach": "Borussia Monchengladbach",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "VfB Stuttgart": "Stuttgart",
    "1. FSV Mainz 05": "Mainz 05",
    "FC Augsburg": "Augsburg",
    "Werder Bremen": "Werder Bremen",
    "1. FC Heidenheim 1846": "Heidenheim",
    "FC St. Pauli": "St. Pauli",
    "Holstein Kiel": "Holstein Kiel",
    "VfL Bochum 1848": "Bochum",
    # Серия А
    "FC Internazionale Milano": "Inter Milan",
    "AC Milan": "AC Milan",
    "Juventus FC": "Juventus",
    "AS Roma": "AS Roma",
    "SS Lazio": "Lazio",
    "ACF Fiorentina": "Fiorentina",
    "Atalanta BC": "Atalanta",
    "SSC Napoli": "Napoli",
    "Torino FC": "Torino",
    "Bologna FC 1909": "Bologna",
    "Udinese Calcio": "Udinese",
    "Genoa CFC": "Genoa",
    "Cagliari Calcio": "Cagliari",
    "US Lecce": "Lecce",
    "Empoli FC": "Empoli",
    "Hellas Verona FC": "Hellas Verona",
    "Venezia FC": "Venezia",
    "Como 1907": "Como",
    "AC Monza": "Monza",
    "Parma Calcio 1913": "Parma",
    # Лига 1
    "Paris Saint-Germain FC": "Paris Saint-Germain",
    "Olympique de Marseille": "Marseille",
    "AS Monaco FC": "Monaco",
    "Olympique Lyonnais": "Lyon",
    "Stade Rennais FC 1901": "Rennes",
    "RC Lens": "Lens",
    "Lille OSC": "Lille",
    "OGC Nice": "Nice",
    "Montpellier HSC": "Montpellier",
    "Stade de Reims": "Reims",
    "FC Nantes": "Nantes",
    "Stade Brestois 29": "Brest",
    "RC Strasbourg Alsace": "Strasbourg",
    "Toulouse FC": "Toulouse",
    "Le Havre AC": "Le Havre",
    "FC Lorient": "Lorient",
    "Clermont Foot 63": "Clermont Foot",
    "Metz FC": "Metz",
    "AJ Auxerre": "Auxerre",
    "Angers SCO": "Angers",
    "Saint-Étienne": "Saint-Etienne",
}

DEFAULT_ELO = 1500
K_FACTOR = 32
HOME_ADVANTAGE = 100
ELO_FILE = "elo_ratings.json"


def normalize_name(name: str) -> str:
    """Нормализует название команды."""
    return TEAM_NAME_MAP.get(name, name.replace(" FC", "").replace(" CF", "").strip())


def expected_score(elo_a: float, elo_b: float) -> float:
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def update_elo_single(ratings: dict, home: str, away: str, home_goals: int, away_goals: int) -> dict:
    """Обновляет ELO рейтинги после одного матча."""
    elo_h = ratings.get(home, DEFAULT_ELO)
    elo_a = ratings.get(away, DEFAULT_ELO)

    # Домашнее преимущество
    exp_h = expected_score(elo_h + HOME_ADVANTAGE, elo_a)

    if home_goals > away_goals:
        actual_h, actual_a = 1.0, 0.0
    elif home_goals == away_goals:
        actual_h, actual_a = 0.5, 0.5
    else:
        actual_h, actual_a = 0.0, 1.0

    new_ratings = dict(ratings)
    new_ratings[home] = round(elo_h + K_FACTOR * (actual_h - exp_h), 1)
    new_ratings[away] = round(elo_a + K_FACTOR * (actual_a - (1 - exp_h)), 1)
    return new_ratings


def fetch_league_results(url: str) -> list:
    """Загружает результаты матчей из openfootball."""
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            matches = data.get("matches", [])
            finished = [m for m in matches if m.get("score")]
            return finished
    except Exception as e:
        print(f"  Ошибка загрузки: {e}")
    return []


def calibrate_elo() -> dict:
    """
    Пересчитывает ELO рейтинги по всем лигам сезона 2024/25.
    Возвращает финальные рейтинги.
    """
    # Стартуем с базовых значений (1500 для всех)
    ratings = {}
    all_matches = []

    print("=" * 60)
    print("ELO КАЛИБРОВКА — Сезон 2024/25")
    print("=" * 60)

    for league_key, info in LEAGUE_SOURCES.items():
        print(f"\n[{info['name']}] Загружаю результаты...")
        matches = fetch_league_results(info["url"])
        print(f"  Найдено матчей: {len(matches)}")

        for m in matches:
            home_raw = m.get("team1", "")
            away_raw = m.get("team2", "")
            score = m.get("score", {})
            ft = score.get("ft", [])
            if len(ft) == 2:
                home_goals, away_goals = ft[0], ft[1]
                home = normalize_name(home_raw)
                away = normalize_name(away_raw)
                date = m.get("date", "")
                all_matches.append({
                    "date": date,
                    "home": home,
                    "away": away,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "league": league_key,
                })

    # Сортируем по дате — важно для правильного порядка обновлений
    all_matches.sort(key=lambda x: x["date"])

    print(f"\nВсего матчей для калибровки: {len(all_matches)}")
    print("Пересчёт ELO...")

    for m in all_matches:
        ratings = update_elo_single(ratings, m["home"], m["away"], m["home_goals"], m["away_goals"])

    return ratings


def build_form_tracker(all_matches: list) -> dict:
    """
    Строит трекер формы команд (последние 5 матчей).
    Возвращает dict: {team: [результаты последних 5 матчей]}
    W=победа, D=ничья, L=поражение
    """
    form = {}
    for m in all_matches:
        home, away = m["home"], m["away"]
        hg, ag = m["home_goals"], m["away_goals"]

        if hg > ag:
            h_res, a_res = "W", "L"
        elif hg == ag:
            h_res, a_res = "D", "D"
        else:
            h_res, a_res = "L", "W"

        for team, res in [(home, h_res), (away, a_res)]:
            if team not in form:
                form[team] = []
            form[team].append(res)

    # Оставляем только последние 5
    return {team: results[-5:] for team, results in form.items()}


def form_elo_bonus(form_results: list) -> float:
    """
    Считает бонус/штраф к ELO на основе формы последних 5 матчей.
    W=+8, D=0, L=-8 (максимум ±40 очков)
    """
    bonus = 0
    weights = [0.6, 0.8, 1.0, 1.2, 1.4]  # Последние матчи важнее
    for i, res in enumerate(form_results):
        w = weights[i] if i < len(weights) else 1.0
        if res == "W":
            bonus += 8 * w
        elif res == "L":
            bonus -= 8 * w
    return round(bonus, 1)


def save_calibrated_elo(ratings: dict, form: dict):
    """Сохраняет откалиброванные ELO и форму."""
    # Сохраняем ELO
    with open(ELO_FILE, "w", encoding="utf-8") as f:
        json.dump(ratings, f, ensure_ascii=False, indent=2)
    print(f"\n✅ ELO сохранён в {ELO_FILE} ({len(ratings)} команд)")

    # Сохраняем форму
    with open("team_form.json", "w", encoding="utf-8") as f:
        json.dump(form, f, ensure_ascii=False, indent=2)
    print(f"✅ Форма сохранена в team_form.json ({len(form)} команд)")


def print_top_ratings(ratings: dict, n: int = 20):
    """Выводит топ-N команд по ELO."""
    sorted_teams = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    print(f"\n{'='*60}")
    print(f"ТОП-{n} КОМАНД ПО ELO (сезон 2024/25):")
    print(f"{'='*60}")
    for i, (team, elo) in enumerate(sorted_teams[:n], 1):
        print(f"{i:2}. {team:<35} {elo:.0f}")


if __name__ == "__main__":
    # 1. Загружаем все результаты
    all_matches_list = []
    for league_key, info in LEAGUE_SOURCES.items():
        matches = fetch_league_results(info["url"])
        for m in matches:
            home_raw = m.get("team1", "")
            away_raw = m.get("team2", "")
            score = m.get("score", {})
            ft = score.get("ft", [])
            if len(ft) == 2:
                all_matches_list.append({
                    "date": m.get("date", ""),
                    "home": normalize_name(home_raw),
                    "away": normalize_name(away_raw),
                    "home_goals": ft[0],
                    "away_goals": ft[1],
                    "league": league_key,
                })

    all_matches_list.sort(key=lambda x: x["date"])

    # 2. Пересчитываем ELO
    ratings = {}
    for m in all_matches_list:
        ratings = update_elo_single(ratings, m["home"], m["away"], m["home_goals"], m["away_goals"])

    # 3. Строим трекер формы
    form = build_form_tracker(all_matches_list)

    # 4. Сохраняем
    save_calibrated_elo(ratings, form)
    print_top_ratings(ratings, 30)

    # 5. Показываем форму топ-команд
    print(f"\n{'='*60}")
    print("ФОРМА ПОСЛЕДНИХ 5 МАТЧЕЙ:")
    print(f"{'='*60}")
    top_teams = sorted(ratings.items(), key=lambda x: x[1], reverse=True)[:20]
    for team, elo in top_teams:
        team_form = form.get(team, [])
        form_str = "".join(team_form)
        bonus = form_elo_bonus(team_form)
        bonus_str = f"+{bonus:.0f}" if bonus > 0 else f"{bonus:.0f}"
        print(f"{team:<35} {elo:.0f} | Форма: {form_str:<5} | Бонус ELO: {bonus_str}")
