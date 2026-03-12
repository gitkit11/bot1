"""
Модуль для получения xG статистики команд через Understat.
Работает только с компьютера пользователя (Understat блокирует облачные серверы).
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Кэш: {team_name: (timestamp, data)}
_xg_cache = {}
CACHE_TTL_HOURS = 6

# Маппинг названий команд из The Odds API → Understat
UNDERSTAT_TEAM_MAP = {
    "Manchester City": "Manchester City",
    "Arsenal": "Arsenal",
    "Liverpool": "Liverpool",
    "Chelsea": "Chelsea",
    "Tottenham Hotspur": "Tottenham",
    "Manchester United": "Manchester United",
    "Newcastle United": "Newcastle United",
    "Aston Villa": "Aston Villa",
    "West Ham United": "West Ham",
    "Brighton": "Brighton",
    "Brighton & Hove Albion": "Brighton",
    "Wolves": "Wolverhampton Wanderers",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
    "Fulham": "Fulham",
    "Brentford": "Brentford",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Nottingham Forest": "Nottingham Forest",
    "Bournemouth": "Bournemouth",
    "Leicester City": "Leicester",
    "Leeds United": "Leeds",
    "Southampton": "Southampton",
    "Ipswich Town": "Ipswich",
    "Burnley": "Burnley",
    "Luton Town": "Luton",
    "Sheffield United": "Sheffield United",
}


def _get_all_teams_xg(season='2024'):
    """Получить xG для всех команд АПЛ за сезон."""
    try:
        from understatapi import UnderstatClient
        with UnderstatClient() as understat:
            data = understat.league(league='EPL').get_team_data(season=season)
            return data
    except Exception as e:
        logger.warning(f"[Understat] Ошибка получения данных: {e}")
        return {}


def get_team_xg_stats(team_name: str, season: str = '2024') -> dict | None:
    """
    Получить xG статистику для команды.
    Возвращает словарь с ключами:
    - avg_xg_last5: среднее xG за последние 5 матчей
    - avg_xga_last5: среднее xGA за последние 5 матчей
    - avg_xg_season: среднее xG за весь сезон
    - avg_xga_season: среднее xGA за весь сезон
    - form_last5: форма последних 5 матчей (W/D/L)
    - goals_scored_avg: среднее голов забито за сезон
    - goals_conceded_avg: среднее голов пропущено за сезон
    """
    cache_key = f"{team_name}_{season}"
    now = datetime.now()

    # Проверяем кэш
    if cache_key in _xg_cache:
        ts, cached_data = _xg_cache[cache_key]
        if now - ts < timedelta(hours=CACHE_TTL_HOURS):
            return cached_data

    # Нормализуем название команды
    understat_name = UNDERSTAT_TEAM_MAP.get(team_name, team_name)

    try:
        all_data = _get_all_teams_xg(season)
        if not all_data:
            return None

        # Ищем команду по названию
        team_data = None
        for key, val in all_data.items():
            title = val.get('title', '')
            if title == understat_name or title == team_name:
                team_data = val
                break

        if not team_data:
            # Попробуем частичное совпадение
            for key, val in all_data.items():
                title = val.get('title', '')
                if understat_name.lower() in title.lower() or title.lower() in understat_name.lower():
                    team_data = val
                    break

        if not team_data:
            logger.warning(f"[Understat] Команда не найдена: {team_name} (искал: {understat_name})")
            return None

        history = team_data.get('history', [])
        if not history:
            return None

        # Последние 5 матчей
        last5 = history[-5:]
        avg_xg_last5 = sum(float(m.get('xG', 0)) for m in last5) / len(last5)
        avg_xga_last5 = sum(float(m.get('xGA', 0)) for m in last5) / len(last5)

        # Весь сезон
        avg_xg_season = sum(float(m.get('xG', 0)) for m in history) / len(history)
        avg_xga_season = sum(float(m.get('xGA', 0)) for m in history) / len(history)

        # Голы
        goals_scored_avg = sum(int(m.get('scored', 0)) for m in history) / len(history)
        goals_conceded_avg = sum(int(m.get('missed', 0)) for m in history) / len(history)

        # Форма последних 5
        form = []
        for m in last5:
            scored = int(m.get('scored', 0))
            missed = int(m.get('missed', 0))
            if scored > missed:
                form.append('W')
            elif scored == missed:
                form.append('D')
            else:
                form.append('L')
        form_str = ''.join(form)

        result = {
            'team': team_data.get('title', team_name),
            'avg_xg_last5': round(avg_xg_last5, 2),
            'avg_xga_last5': round(avg_xga_last5, 2),
            'avg_xg_season': round(avg_xg_season, 2),
            'avg_xga_season': round(avg_xga_season, 2),
            'goals_scored_avg': round(goals_scored_avg, 2),
            'goals_conceded_avg': round(goals_conceded_avg, 2),
            'form_last5': form_str,
            'matches_played': len(history),
        }

        # Сохраняем в кэш
        _xg_cache[cache_key] = (now, result)
        logger.info(f"[Understat] {team_name}: xG={avg_xg_last5:.2f}, xGA={avg_xga_last5:.2f}, форма={form_str}")
        return result

    except Exception as e:
        logger.error(f"[Understat] Ошибка для {team_name}: {e}")
        return None


def format_xg_stats(home_team: str, away_team: str, season: str = '2024') -> str:
    """
    Форматирует xG статистику для двух команд в текстовый блок для AI агентов.
    """
    home_stats = get_team_xg_stats(home_team, season)
    away_stats = get_team_xg_stats(away_team, season)

    if not home_stats and not away_stats:
        return ""

    lines = ["📊 xG СТАТИСТИКА (Understat):"]

    if home_stats:
        lines.append(
            f"🏠 {home_team}:\n"
            f"   • xG последние 5 матчей: {home_stats['avg_xg_last5']} (создают)\n"
            f"   • xGA последние 5 матчей: {home_stats['avg_xga_last5']} (допускают)\n"
            f"   • xG за сезон: {home_stats['avg_xg_season']} / xGA: {home_stats['avg_xga_season']}\n"
            f"   • Голов в среднем: {home_stats['goals_scored_avg']} забито / {home_stats['goals_conceded_avg']} пропущено\n"
            f"   • Форма (посл. 5): {home_stats['form_last5']}"
        )
    else:
        lines.append(f"🏠 {home_team}: xG данные недоступны")

    if away_stats:
        lines.append(
            f"✈️ {away_team}:\n"
            f"   • xG последние 5 матчей: {away_stats['avg_xg_last5']} (создают)\n"
            f"   • xGA последние 5 матчей: {away_stats['avg_xga_last5']} (допускают)\n"
            f"   • xG за сезон: {away_stats['avg_xg_season']} / xGA: {away_stats['avg_xga_season']}\n"
            f"   • Голов в среднем: {away_stats['goals_scored_avg']} забито / {away_stats['goals_conceded_avg']} пропущено\n"
            f"   • Форма (посл. 5): {away_stats['form_last5']}"
        )
    else:
        lines.append(f"✈️ {away_team}: xG данные недоступны")

    return "\n".join(lines)
